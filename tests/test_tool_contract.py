"""Contract tests over the registered MCP tool surface.

These assert properties of the tools *as a client sees them*: their names,
their JSON schema, and the size of the description block shipped on every
session. The rest of the suite exercises the client and the shaping layer,
which means a ``Field`` typo or a dropped docstring could change the published
contract without failing a single test.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from familysearch_mcp.server import TREE_TOOLS, mcp

from .conftest import call_tool

SNAPSHOT = Path(__file__).parent / "fixtures" / "tool_schema.json"
README = Path(__file__).parent.parent / "README.md"

#: Ceiling on the combined tool descriptions, which are sent to the model on
#: every session. Raise it deliberately, not by accident.
#:
#: 25 tools averaging ~540 characters. The tree tools are the long ones and
#: are meant to be: each carries the shared-tree caveat in full, because a
#: model choosing a tool sees the description and nothing else. Raised from
#: 13,500 when the browse tools landed; the average per tool fell, so the
#: growth was the count rather than prose.
DESCRIPTION_BUDGET = 16_000


async def _tools() -> list:
    return sorted(await mcp.list_tools(), key=lambda t: t.name)


def _params(tool) -> dict:
    return (tool.input_schema or {}).get("properties", {}) or {}


def _documented_in_readme() -> set[str]:
    """Tool names the README's reference table lists."""
    doc = README.read_text()
    documented = set(re.findall(r"\| `([a-z_]+)`", doc))
    for pair in re.findall(r"`([a-z_]+)` / `([a-z_]+)`", doc):
        documented.update(pair)
    return documented


async def test_every_tool_has_a_description():
    """A tool with no description is invisible to the model choosing tools."""
    missing = [t.name for t in await _tools() if not (t.description or "").strip()]
    assert missing == []


async def test_every_parameter_has_a_description():
    """An undescribed parameter gets guessed at, and guesses waste a search."""
    undocumented = [
        f"{t.name}.{name}"
        for t in await _tools()
        for name, spec in _params(t).items()
        if not (spec.get("description") or "").strip()
    ]
    assert undocumented == []


async def test_no_parameter_leaks_a_python_repr():
    """A FieldInfo or PydanticUndefined in a schema means a broken default."""
    leaked = [
        f"{t.name}.{name}"
        for t in await _tools()
        for name, spec in _params(t).items()
        if "FieldInfo" in json.dumps(spec) or "PydanticUndefined" in json.dumps(spec)
    ]
    assert leaked == []


async def test_tool_names_and_parameters_match_the_snapshot():
    """Renaming a tool or a parameter breaks callers; make it a visible diff.

    Regenerate deliberately with::

        uv run --extra dev python -m tests.regen_tool_snapshot
    """
    current = {t.name: sorted(_params(t)) for t in await _tools()}
    expected = json.loads(SNAPSHOT.read_text())
    assert current == expected


async def test_required_parameters_have_no_default():
    """A required parameter with a default is a contradiction in the schema."""
    bad = []
    for tool in await _tools():
        schema = tool.input_schema or {}
        for name in schema.get("required", []):
            if "default" in (schema.get("properties", {}).get(name) or {}):
                bad.append(f"{tool.name}.{name}")
    assert bad == []


async def test_description_block_stays_within_budget():
    """Every byte here is spent on every session, before any work happens."""
    total = sum(len(t.description or "") for t in await _tools())
    assert total <= DESCRIPTION_BUDGET, (
        f"tool descriptions total {total} chars, over the {DESCRIPTION_BUDGET} budget"
    )


async def test_descriptions_are_published_without_source_indentation():
    """Python 3.11 and 3.12 keep a docstring's indentation; 3.13 strips it.

    Published raw, the same tool would cost more on older Pythons, and the
    budget above would pass on one Python and fail on another.
    """
    indented = [
        t.name
        for t in await _tools()
        if (t.description or "") != inspect.cleandoc(t.description or "")
    ]
    assert indented == []


async def test_every_registered_tool_appears_in_the_readme():
    """A tool the README does not list is a tool nobody will find."""
    missing = sorted({t.name for t in await _tools()} - _documented_in_readme())
    assert missing == [], f"tools missing from the README table: {missing}"


async def test_readme_does_not_document_a_tool_that_was_removed():
    """A table entry for a tool that no longer exists is worse than none."""
    names = {t.name for t in await _tools()}
    prefixes = ("get_", "search_", "auth_", "list_")
    stale = sorted(n for n in _documented_in_readme() - names if n.startswith(prefixes))
    assert stale == [], f"README documents tools that do not exist: {stale}"


async def test_no_description_mentions_a_write():
    """This server is read-only; a description implying otherwise invites one."""
    forbidden = re.compile(
        r"\b(create|update|delete|merge|upload|attach|write|edit|modify)\b",
        re.IGNORECASE,
    )
    offenders = [
        t.name
        for t in await _tools()
        if forbidden.search(
            # "community-edited" is the warning, not an offer to edit.
            (t.description or "").replace("community-edited", "")
        )
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "tool_name",
    sorted(TREE_TOOLS),
)
async def test_every_tree_tool_carries_the_shared_tree_warning(tool_name):
    """The failure mode is a caller trusting a profile a tool returned calmly.

    Every tool that reads the community-edited tree has to say so in its own
    description, because a model choosing between tools sees the descriptions
    and nothing else.
    """
    tool = next(t for t in await _tools() if t.name == tool_name)
    description = (tool.description or "").lower()
    assert "community-edited" in description
    assert "not" in description and ("evidence" in description or "source" in description)


@respx.mock
async def test_no_tool_raises_instead_of_returning_an_envelope(monkeypatch):
    """A tool that raises crashes the call; every failure must be a dict.

    Every tool is swept twice -- against a server answering nonsense, and
    against one returning a 500 -- and each must come back as a structured
    error rather than an exception crossing the MCP boundary.
    """
    from familysearch_mcp import server
    from familysearch_mcp.client import FamilySearchClient
    from familysearch_mcp.config import Config

    config = Config(access_token="test-token", environment="production", timeout=5.0)
    monkeypatch.setattr(server.state, "config", config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(config))
    route = respx.route(host="api.familysearch.org")

    samples = {
        "string": "K2ZP-VY1",
        "integer": 1850,
        "number": 1.0,
        "boolean": False,
    }
    for response in (
        httpx.Response(200, json={"unexpected": "nonsense"}),
        httpx.Response(500, text="<html>gateway</html>"),
    ):
        route.mock(return_value=response)
        for tool in await _tools():
            schema = tool.input_schema or {}
            args = {
                name: samples.get(
                    (schema.get("properties", {}).get(name) or {}).get("type"),
                    "K2ZP-VY1",
                )
                for name in schema.get("required", [])
            }
            out = await call_tool(tool.name, **args)
            assert isinstance(out, dict), f"{tool.name} did not return a dict"


def test_no_source_or_fixture_contains_anything_like_a_credential():
    """The package ships no client id and no token, anywhere, ever.

    A plausible-looking credential committed as a fixture or an example is
    how another project's key ends up being used by everyone who installs
    this one. Scanned across the source, the tests and the documentation,
    not just the published descriptions.
    """
    root = Path(__file__).parent.parent
    patterns = (
        # A FamilySearch client id: four-character groups, hyphenated.
        re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b"),
        # A long opaque hex or base64-ish secret.
        re.compile(r"\b[0-9a-fA-F]{32,}\b"),
        # An assignment that actually sets one.
        re.compile(r"FS_(?:CLIENT_ID|ACCESS_TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    )
    offenders = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".py", ".md", ".toml", ".example"}:
            continue
        if any(part in {".venv", ".git", "uv.lock"} for part in path.parts):
            continue
        text = path.read_text(errors="ignore")
        for pattern in patterns:
            for hit in pattern.findall(text):
                offenders.append(f"{path.relative_to(root)}: {hit}")
    assert offenders == [], f"credential-shaped strings found: {offenders}"


def test_the_env_example_ships_no_values():
    """Every credential line in the example must be empty or commented out."""
    example = (Path(__file__).parent.parent / ".env.example").read_text()
    filled = [
        line
        for line in example.splitlines()
        if line.startswith("FS_") and line.split("=", 1)[1].strip()
    ]
    assert filled == []


async def test_no_description_or_schema_contains_anything_like_a_client_id():
    """This package ships no credential, and must never look as if it does.

    A 32-character hex-ish token in a description would be read as a default
    to use. There is no default; there is the operator's own registered
    application.
    """
    blob = json.dumps([{"d": t.description, "s": t.input_schema} for t in await _tools()])
    # FamilySearch record arks are legitimately shaped like a token --
    # "3:1:33SQ-G5LD-93NY" -- and examples of them belong in descriptions.
    # Strip the ark prefix and its id before looking for a credential, so the
    # guard still catches a real one.
    blob = re.sub(r"\d:\d:[A-Z0-9-]+", "<ark>", blob)
    assert re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b", blob) is None
    assert re.search(r"\b[0-9a-fA-F]{32}\b", blob) is None


async def test_no_schema_carries_an_auto_generated_title():
    """Titles are roughly a tenth of the published block and say nothing.

    Pydantic derives one from each field's own name. ``compact_schemas``
    strips them at import; this asserts none creeps back in through a new
    tool.
    """

    def schema_titles(node, path=""):
        """Yield every ``title`` *keyword*, ignoring parameters named title."""
        if isinstance(node, dict):
            if isinstance(node.get("title"), str):
                yield f"{path}.title"
            for keyword, value in node.items():
                if keyword in ("properties", "$defs", "definitions"):
                    if isinstance(value, dict):
                        for name, sub in value.items():
                            yield from schema_titles(sub, f"{path}.{keyword}.{name}")
                elif keyword != "title":
                    yield from schema_titles(value, f"{path}.{keyword}")
        elif isinstance(node, list):
            for item in node:
                yield from schema_titles(item, path)

    found = [
        t for tool in await _tools() for t in schema_titles(tool.input_schema or {}, tool.name)
    ]
    assert found == []


async def test_compaction_actually_removed_something():
    """A no-op optimisation should not be left in place looking like one."""
    from familysearch_mcp.server import SCHEMA_CHARS_SAVED

    assert SCHEMA_CHARS_SAVED > 500


async def test_compaction_is_idempotent():
    """It runs at import; running it again must not corrupt the schemas."""
    from familysearch_mcp.server import compact_schemas

    assert compact_schemas() == 0


# --------------------------------------------------------------------------- #
# Unknown parameters are refused, not dropped
# --------------------------------------------------------------------------- #
@respx.mock
async def test_every_tool_refuses_a_parameter_it_does_not_define():
    """A misnamed argument must fail loudly, on every tool.

    Reported from real use: ``collection_id`` passed to a search tool that
    had no such parameter was accepted, discarded, and answered with
    unscoped results that looked correct. Another server turned a misnamed
    filter into "return everything" the same way.
    """
    from mcp.server.mcpserver.exceptions import ToolError

    from .conftest import valid_args

    # Should the refusal regress, the tools run for real; keep them offline.
    respx.route().mock(return_value=httpx.Response(200, json={}))
    accepted = []
    for tool in await _tools():
        args = valid_args(tool, not_a_parameter="x")
        try:
            await mcp.call_tool(tool.name, args)
        except ToolError as exc:
            assert "not_a_parameter" in str(exc), tool.name
            continue
        accepted.append(tool.name)
    assert accepted == [], f"accepted an undefined parameter: {accepted}"


@respx.mock
async def test_the_refusal_names_what_the_tool_does_take():
    """So a caller that guessed a name can correct itself in one step."""
    from mcp.server.mcpserver.exceptions import ToolError

    respx.route().mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(ToolError) as exc:
        await mcp.call_tool("get_image_links", {"image_ark": "3:1:X", "query": "x"})
    message = str(exc.value)
    assert "has no parameter 'query'" in message
    assert "It takes: image_ark." in message


async def test_every_published_schema_forbids_additional_properties():
    """A client that validates against the schema can refuse before sending."""
    loose = [
        t.name
        for t in await _tools()
        if (t.input_schema or {}).get("additionalProperties") is not False
    ]
    assert loose == []


# --------------------------------------------------------------------------- #
# What a client is told about each tool
# --------------------------------------------------------------------------- #
#: The one tool with a side effect. It creates a local file.
WRITES_LOCALLY = {"download_image"}


async def test_every_tool_declares_its_annotations():
    """A client decides what needs approval from these; absent means unknown."""
    missing = [t.name for t in await _tools() if t.annotations is None]
    assert missing == []


async def test_every_tool_but_the_download_is_marked_read_only():
    """The read-only claim in the README is only useful if the client sees it."""
    wrong = [
        t.name
        for t in await _tools()
        if t.annotations.read_only_hint is not (t.name not in WRITES_LOCALLY)
    ]
    assert wrong == []


async def test_the_download_is_marked_as_writing_but_not_destroying():
    """It creates files, so it is not read-only; it never overwrites one."""
    tool = next(t for t in await _tools() if t.name == "download_image")
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False


async def test_the_server_reports_its_own_version():
    """An empty serverInfo.version leaves a bug report unable to say which."""
    from familysearch_mcp import __version__

    assert mcp.version == __version__
    assert __version__


async def test_no_description_names_a_tool_that_does_not_exist():
    """Descriptions point at each other; a pointer to a removed tool misleads.

    ``search_collections`` once sent callers to ``search_records_advanced``
    for a whole release after that tool had been folded into
    ``search_records``.
    """
    tools = await _tools()
    names = {t.name for t in tools}
    tool_shaped = re.compile(r"\b(?:get|search|browse|download|auth)_[a-z_]+\b")
    stale = sorted(
        f"{t.name} -> {word}"
        for t in tools
        for word in tool_shaped.findall(t.description or "")
        if word not in names
    )
    assert stale == []


#: Tools that place an id argument in a request path, with that argument.
ID_ARGUMENTS = {
    "get_place": "place_id",
    "get_place_jurisdictions": "place_id",
    "get_place_children": "place_id",
    "search_places_at_date": "within_place_id",
    "get_record": "ark",
    "get_record_image": "ark",
    "get_collection": "collection_id",
    "get_collection_fields": "collection_id",
    "browse_waypoints": "waypoint_id",
    "get_records_on_image": "image_ark",
    "get_image_links": "image_ark",
    "get_person": "person_id",
    "get_person_relatives": "person_id",
    "get_ancestry": "person_id",
    "get_descendancy": "person_id",
    "get_person_sources": "person_id",
    "get_person_memories": "person_id",
    "get_person_changes": "person_id",
    "get_matches": "person_id",
    "compare_person": "person_id",
}


async def test_every_id_argument_is_listed_here():
    """A new tool taking an id must join the refusal sweep below.

    ``search_records`` and ``fulltext_search`` are the exceptions: their
    ``collection_id`` is a query parameter, which the HTTP client encodes,
    not part of the path.
    """
    id_names = {"place_id", "within_place_id", "ark", "image_ark", "collection_id"}
    id_names |= {"waypoint_id", "person_id"}
    taking_ids = {t.name for t in await _tools() if id_names & set(_params(t))}
    assert taking_ids - {"search_records", "fulltext_search"} == set(ID_ARGUMENTS)


@pytest.mark.parametrize("tool_name", sorted(ID_ARGUMENTS))
@pytest.mark.parametrize(
    "bad",
    ["K2ZP-VY1/../../users/current", "442?access_token=x", "../..", "K2ZP VY1", ""],
)
@respx.mock
async def test_an_id_that_could_reach_another_route_is_refused_locally(tool_name, bad):
    """An id goes into a request path. A slash or a query must not steer it."""
    from familysearch_mcp import server
    from familysearch_mcp.client import FamilySearchClient
    from familysearch_mcp.config import Config

    from .conftest import valid_args

    config = Config(access_token="test-token", environment="production", timeout=5.0)
    server.state.config = config
    server.state.client = FamilySearchClient(config)
    try:
        tool = next(t for t in await _tools() if t.name == tool_name)
        parameter = ID_ARGUMENTS[tool_name]
        if bad == "" and parameter in {"within_place_id", "waypoint_id"}:
            pytest.skip(f"{parameter} is optional; empty means 'not given'")
        if parameter.endswith("ark") and ("/" in bad[1:] or "?" in bad):
            pytest.skip("an ark may be a URL; see the test after this one")
        out = await call_tool(tool_name, **valid_args(tool, **{parameter: bad}))
    finally:
        server.state.config = None
        server.state.client = None
    assert out["error"] == "invalid_id", out
    assert parameter in out["message"]
    assert not respx.calls


@pytest.mark.parametrize(
    "tool_name", sorted(t for t, p in ID_ARGUMENTS.items() if p.endswith("ark"))
)
@respx.mock
async def test_an_ark_given_as_a_url_is_reduced_to_one_path_segment(tool_name):
    """Arks are copied from the website as URLs, so a URL is accepted, not refused.

    What reaches the request path is the last segment alone: nothing before
    a slash and nothing after a question mark survives to steer the route.
    """
    from familysearch_mcp import server
    from familysearch_mcp.client import FamilySearchClient
    from familysearch_mcp.config import Config

    from .conftest import valid_args

    route = respx.route(host="api.familysearch.org").mock(return_value=httpx.Response(200, json={}))
    config = Config(access_token="test-token", environment="production", timeout=5.0)
    server.state.config = config
    server.state.client = FamilySearchClient(config)
    try:
        tool = next(t for t in await _tools() if t.name == tool_name)
        bad = "https://www.familysearch.org/ark:/61903/../../users/current?access_token=x"
        await call_tool(tool_name, **valid_args(tool, **{ID_ARGUMENTS[tool_name]: bad}))
    finally:
        server.state.config = None
        server.state.client = None
    for call in route.calls:
        assert "/users/" not in call.request.url.path
        assert "access_token" not in str(call.request.url)
