"""The auth boundary, exhaustively.

This is the property the project is built on: the package ships no client id,
so a tool either answers anonymously because FamilySearch allows it, or it
refuses and names the variable to set. Nothing in between, and nothing that
sends a bare request and lets the server produce the confusion.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import ANONYMOUS_PATHS, FamilySearchClient
from familysearch_mcp.config import Config

from .conftest import assert_reached_body, call_tool, valid_args

#: The anonymous path list, pinned. Adding a path here means asserting that
#: FamilySearch answers it without a token; getting that wrong turns a clear
#: refusal into a confusing 401 from the server. Change it deliberately.
#: Deliberately widened on 2026-09-23, each entry after confirming live that
#: it answers with no Authorization header: the record-collection route, the
#: waypoint tree, and the image resource. The image resource carries an
#: exception -- see AUTHENTICATED_SUBPATHS and needs_token.
ANONYMOUS_PATH_SNAPSHOT = (
    "/platform/places/search",
    "/platform/places/description",
    "/platform/records/collections",
    "/platform/records/waypoints",
    "/platform/records/images",
)


#: Search tools reject an empty set of criteria before they reach the network,
#: which is correct but would let them pass an auth sweep without ever
#: testing the auth boundary. These give them something to search for.
async def _all_tools() -> list:
    return sorted(await server.mcp.list_tools(), key=lambda t: t.name)


@pytest.fixture
def unconfigured(monkeypatch):
    """Install a token-free client on the server, as a fresh install has."""
    config = Config(environment="production", timeout=5.0)
    monkeypatch.setattr(server.state, "config", config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(config))
    return config


def test_the_anonymous_path_list_cannot_grow_silently():
    """Each entry is a claim that FamilySearch answers it without a token.

    Widening this list is how an unauthenticated request starts being sent
    and failing as a server-side 401 instead of a local refusal that says
    which variable to set.
    """
    assert ANONYMOUS_PATHS == ANONYMOUS_PATH_SNAPSHOT


def test_anonymous_paths_are_reads_that_carry_no_personal_data():
    """Anonymous access is confined to reference data, never to people.

    The gazetteer and the collection descriptors are catalogues: places and
    field dictionaries. No tree route and no record or persona route belongs
    here, because those carry data about individuals.
    """
    allowed_prefixes = (
        "/platform/places/",
        "/platform/records/collections",
        "/platform/records/waypoints",
        "/platform/records/images",
    )
    assert all(p.startswith(allowed_prefixes) for p in ANONYMOUS_PATHS)
    assert not any("/tree/" in p for p in ANONYMOUS_PATHS)
    assert not any(p.rstrip("/").endswith("personas") for p in ANONYMOUS_PATHS)


async def test_every_authenticated_tool_refuses_cleanly_with_no_token(unconfigured):
    """A refusal has to name FS_ACCESS_TOKEN, or the caller cannot act on it.

    Arguments come from ``valid_args`` and every result passes through
    ``assert_reached_body``, so a tool that refuses the sweep's input before
    ever looking for credentials fails here rather than passing without
    proving anything.
    """
    failures = []
    for tool in await _all_tools():
        if tool.name in server.ANONYMOUS_TOOLS:
            continue
        out = await call_tool(tool.name, **valid_args(tool))
        assert_reached_body(tool.name, out)
        if out.get("error") != "auth_required":
            failures.append(f"{tool.name}: {out.get('error')!r}")
        elif "FS_ACCESS_TOKEN" not in out.get("message", ""):
            failures.append(f"{tool.name}: refusal does not name FS_ACCESS_TOKEN")
    assert failures == []


@respx.mock
async def test_no_request_is_ever_sent_without_authorization_off_the_anon_paths(
    unconfigured,
):
    """The catch-all records every request an unconfigured install makes.

    Any request that escapes without an Authorization header must have gone
    to a path FamilySearch serves anonymously. Anything else is a bare
    request this server promised never to send.
    """
    catch_all = respx.route(host="api.familysearch.org").mock(
        return_value=httpx.Response(200, json={})
    )
    for tool in await _all_tools():
        await call_tool(tool.name, **valid_args(tool))

    sent = [call.request for call in catch_all.calls]
    unauthenticated = [r.url.path for r in sent if "Authorization" not in r.headers]
    assert unauthenticated, "the sweep sent nothing; the test proves nothing"
    assert all(p.startswith(ANONYMOUS_PATHS) for p in unauthenticated), (
        f"unauthenticated requests off the anonymous paths: {unauthenticated}"
    )


async def test_no_token_configured_is_distinct_from_a_rejected_token(unconfigured):
    """'You have not set one' and 'yours was refused' need different fixes."""
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "auth_required"
    assert "status" not in out


@respx.mock
async def test_an_expired_token_reports_token_rejected(monkeypatch, auth_config, tmp_path):
    """A 401 means the token is no longer good, not that none was configured."""
    env = tmp_path / "fs.env"
    env.write_text(f"FS_ACCESS_TOKEN={auth_config.access_token}\n")
    auth_config.env_file = str(env)
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "token_rejected"
    assert out["status"] == 401
    # The message has to say what to do. It used to suggest reconnecting the
    # server, which does not help -- the server now re-reads the env file on
    # a 401, so refreshing that file is the whole fix.
    assert "Refresh" in out["message"]
    assert "docs/AUTH.md" in out["message"]
    assert str(env) in out["message"]


@respx.mock
async def test_a_401_with_no_env_file_says_recovery_is_off(monkeypatch, auth_config):
    """With nothing to re-read, telling the caller to refresh the file is wrong.

    Reported from real use: the launcher sourced the env file and exported
    the token, so the server never learned which file it came from. The 401
    said "re-reading the env file did not produce a different one" when no
    file had been read at all, and a refreshed token sat unused.
    """
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(401, json={})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "token_rejected"
    assert "FS_ENV_FILE" in out["message"]
    assert "Re-reading" not in out["message"]


CURRENT_USER = "https://api.familysearch.org/platform/users/current"


@respx.mock
async def test_auth_status_warns_when_recovery_has_no_file(monkeypatch, auth_config):
    """The checklist must say an expired token will need a restart."""
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(200, json={}))
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert out["token_source"] == "environment only"
    assert "FS_ENV_FILE" in out["note"]


@respx.mock
async def test_auth_status_names_a_missing_env_file(monkeypatch, auth_config, tmp_path):
    """A mistyped FS_ENV_FILE must not read as working recovery."""
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(200, json={}))
    auth_config.env_file = str(tmp_path / "typo.env")
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert "does not exist" in out["note"]


@respx.mock
async def test_auth_status_with_an_env_file_promises_recovery(monkeypatch, auth_config, tmp_path):
    """The happy path still says refreshing the file is enough."""
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(200, json={}))
    env = tmp_path / "fs.env"
    env.write_text("FS_ACCESS_TOKEN=t\n")
    auth_config.env_file = str(env)
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert out["token_source"] == str(env)
    assert "refreshing the file is enough" in out["note"]


# --------------------------------------------------------------------------- #
# auth_status asks whether the token still works
# --------------------------------------------------------------------------- #
@respx.mock
async def test_auth_status_reports_a_token_familysearch_accepts(monkeypatch, auth_config):
    """Configured and accepted are different facts; both are reported."""
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(200, json={}))
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert out["authenticated"] is True
    assert out["token_accepted"] is True
    assert "token_problem" not in out


@respx.mock
async def test_auth_status_reports_an_expired_token(monkeypatch, auth_config):
    """Reported from real use: authenticated, while tools acted tokenless.

    "authenticated" meant only that a token was set. An expired one read the
    same as a good one until a tool failed in a way that blamed something
    else.
    """
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(401, json={}))
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert out["authenticated"] is True
    assert out["token_accepted"] is False
    assert "rejected" in out["token_problem"]


@respx.mock
async def test_auth_status_adopts_a_refreshed_token_while_checking(
    monkeypatch, auth_config, tmp_path
):
    """Checking goes through the ordinary 401 recovery, so it repairs too."""
    env = tmp_path / "fs.env"
    env.write_text("FS_ACCESS_TOKEN=fresh\n")
    auth_config.env_file = str(env)

    def current_user(request):
        fresh = request.headers["authorization"] == "Bearer fresh"
        return httpx.Response(200 if fresh else 401, json={})

    respx.get(CURRENT_USER).mock(side_effect=current_user)
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert out["token_accepted"] is True
    assert auth_config.access_token == "fresh"


@respx.mock
async def test_auth_status_says_when_the_token_could_not_be_checked(monkeypatch, auth_config):
    """Unreachable is not refused; it must not report the token as bad."""
    respx.get(CURRENT_USER).mock(side_effect=httpx.ConnectError("offline"))
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("auth_status")
    assert out["token_accepted"] is None
    assert "Could not reach" in out["token_problem"]


async def test_auth_status_without_a_token_asks_nothing(unconfigured):
    """No token, no request: the checklist works offline."""
    out = await call_tool("auth_status")
    assert "token_accepted" not in out


@respx.mock
async def test_insufficient_scope_reports_forbidden(monkeypatch, auth_config):
    """A 403 is a permissions problem; re-authenticating will not fix it."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "forbidden"
    assert out["status"] == 403


@respx.mock
async def test_the_three_credential_failures_are_three_distinct_errors(monkeypatch, auth_config):
    """No token, rejected token and forbidden must never collapse together."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    route = respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1")

    route.mock(return_value=httpx.Response(401, json={}))
    rejected = (await call_tool("get_person", person_id="K2ZP-VY1"))["error"]
    route.mock(return_value=httpx.Response(403, json={}))
    forbidden = (await call_tool("get_person", person_id="K2ZP-VY1"))["error"]

    anon = Config(environment="production", timeout=5.0)
    monkeypatch.setattr(server.state, "config", anon)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon))
    unset = (await call_tool("get_person", person_id="K2ZP-VY1"))["error"]

    assert len({rejected, forbidden, unset}) == 3


async def test_auth_status_lists_exactly_the_tools_that_need_no_token(unconfigured):
    """The checklist a caller reads must match what the server will actually do."""
    out = await call_tool("auth_status")
    assert set(out["available_without_credentials"]) == set(server.ANONYMOUS_TOOLS)
    assert out["authenticated"] is False


async def test_auth_status_answers_without_a_token(unconfigured):
    """Reporting what is missing must not itself require what is missing."""
    out = await call_tool("auth_status")
    assert "error" not in out
    assert set(out["missing"]) == {"FS_CLIENT_ID", "FS_ACCESS_TOKEN"}


def test_the_image_resource_is_open_but_its_records_are_not():
    """A prefix match cannot express this, so needs_token carves it out.

    Verified live 2026-09-23: /platform/records/images/{ark} answers 200
    with no header, while .../{ark}/records answers 401. Getting this wrong
    would turn a clear local refusal into a confusing 401 from FamilySearch.
    """
    from familysearch_mcp.client import needs_token

    assert needs_token("/platform/records/images/3:1:X") is False
    assert needs_token("/platform/records/images/3:1:X/records") is True


def test_person_and_persona_reads_still_need_a_token():
    """The anonymous carve-outs must not have widened past reference data."""
    from familysearch_mcp.client import needs_token

    assert needs_token("/platform/tree/persons/K2ZP-VY1") is True
    assert needs_token("/platform/records/personas/KX42-QVQ") is True
    assert needs_token("/platform/records/records/9MVG-BPYL") is True


def test_nothing_in_the_repository_signs_in_to_the_website():
    """The repository takes a token; nothing in it obtains one with a password.

    A script that signed in to the FamilySearch website with a username and
    password used to ship here as an example. It was taken out before the
    repository went public: FamilySearch's developer rules say an application
    never handles the user's password. This fails if one comes back.
    """
    root = Path(__file__).parent.parent
    # Split so that this file does not match itself.
    markers = ("ident." + "familysearch.org", "login" + "Error", "auth/" + "familysearch/login")
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".toml", ".yml", ".json"}:
            continue
        if any(part in {".venv", ".git"} for part in path.parts):
            continue
        text = path.read_text(errors="ignore")
        found += [f"{path.relative_to(root)}: {m}" for m in markers if m in text]
    assert found == []
