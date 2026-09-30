"""How FamilySearch's search actually behaves, and what this server does about it.

Two behaviours here are surprising enough that they were reported as bugs:
a criterion that does not narrow anything, and a catalogue search that finds
nothing. Neither was a bug in the API. Both are pinned so the handling cannot
quietly regress.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient

from .conftest import call_tool

SEARCH = "https://www.familysearch.org/service/search/hr/v2/personas"
CATALOGUE = "https://api.familysearch.org/platform/records/collections"


def _wired(monkeypatch, cfg):
    monkeypatch.setattr(server.state, "config", cfg)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(cfg))
    monkeypatch.setattr(server.state, "catalogue", None)


# --------------------------------------------------------------------------- #
# Criteria are scoring hints unless required
# --------------------------------------------------------------------------- #
@respx.mock
async def test_criteria_are_required_by_default(monkeypatch, auth_config):
    """A search term only narrows results when marked required.

    Verified live 2026-09-23: a name search returned 114,978 either way, and
    adding a death date changed nothing until the global require switch was
    set -- at which point the same search returned 66. A filter that does
    not filter is the surprising behaviour, so requiring is the default.
    """
    _wired(monkeypatch, auth_config)
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", death_year=1823)
    assert route.calls.last.request.url.params["m.queryRequireDefault"] == "on"


@respx.mock
async def test_loose_turns_requiring_off(monkeypatch, auth_config):
    """Ranking by similarity is still available when that is what you want."""
    _wired(monkeypatch, auth_config)
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", loose=True)
    assert "m.queryRequireDefault" not in route.calls.last.request.url.params


@respx.mock
async def test_the_simple_search_requires_by_default_too(monkeypatch, auth_config):
    """Both search tools have to behave the same way about this."""
    _wired(monkeypatch, auth_config)
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", given="Ezra")
    assert route.calls.last.request.url.params["m.queryRequireDefault"] == "on"


@respx.mock
async def test_an_empty_search_sends_no_require_switch(monkeypatch, auth_config):
    """With nothing to require, the switch is noise."""
    _wired(monkeypatch, auth_config)
    respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool("search_records")
    assert out["error"] == "no_criteria"


# --------------------------------------------------------------------------- #
# The catalogue has no search, so it is walked and cached
# --------------------------------------------------------------------------- #
def _catalogue_page(ids: list[str]) -> dict:
    return {
        "sourceDescriptions": [
            {
                "id": f"sd_c_{i}",
                "about": f"https://x/{i}",
                "titles": [{"value": f"Collection {i}"}],
            }
            for i in ids
        ]
    }


@respx.mock
async def test_the_catalogue_is_walked_not_sampled(monkeypatch, anon_config):
    """The old bug: one page was fetched and filtered.

    With ~3,400 collections paged at ninety, matching against the first page
    alone found nothing for most queries -- 'Iowa' among them, which is what
    was reported.
    """
    _wired(monkeypatch, anon_config)
    pages = [
        _catalogue_page([str(n) for n in range(0, 90)]),
        _catalogue_page(["iowa-1", "iowa-2"]),
        {"sourceDescriptions": []},
    ]
    respx.get(CATALOGUE).mock(side_effect=[httpx.Response(200, json=p) for p in pages])
    monkeypatch.setattr(server, "_read_catalogue_cache", lambda: None)
    monkeypatch.setattr(server, "_write_catalogue_cache", lambda entries: None)

    out = await call_tool("search_collections", query="Collection iowa")
    assert out["collections_searched"] == 92
    assert out["matched"] == 2


@respx.mock
async def test_the_catalogue_is_fetched_once_per_session(monkeypatch, anon_config):
    """Walking it costs about ninety seconds; doing that per query is not viable."""
    _wired(monkeypatch, anon_config)
    route = respx.get(CATALOGUE).mock(
        side_effect=[
            httpx.Response(200, json=_catalogue_page(["a", "b"])),
            httpx.Response(200, json={"sourceDescriptions": []}),
        ]
    )
    monkeypatch.setattr(server, "_read_catalogue_cache", lambda: None)
    monkeypatch.setattr(server, "_write_catalogue_cache", lambda entries: None)

    await call_tool("search_collections", query="Collection")
    calls_after_first = route.call_count
    await call_tool("search_collections", query="Collection")
    assert route.call_count == calls_after_first


async def test_a_stale_disk_cache_is_ignored(monkeypatch, tmp_path):
    """A cached catalogue past its age is refetched rather than trusted."""
    import json as _json
    import time

    cache = tmp_path / "collections.json"
    cache.write_text(
        _json.dumps(
            {
                "fetched_at": time.time() - (server.CATALOGUE_MAX_AGE + 60),
                "collections": [{"id": "old", "title": "Stale"}],
            }
        )
    )
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() is None


async def test_a_fresh_disk_cache_is_used(monkeypatch, tmp_path):
    """The whole point: a restart should not pay the walk again."""
    import json as _json
    import time

    cache = tmp_path / "collections.json"
    cache.write_text(
        _json.dumps(
            {
                "fetched_at": time.time(),
                "collections": [{"id": "c1", "title": "Iowa, Births"}],
            }
        )
    )
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() == [{"id": "c1", "title": "Iowa, Births"}]


@pytest.mark.parametrize("body", ["not json", '{"collections": []}', "{}"])
async def test_an_unusable_disk_cache_is_ignored(monkeypatch, tmp_path, body):
    """A corrupt or empty cache must not shadow a real fetch."""
    cache = tmp_path / "collections.json"
    cache.write_text(body)
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() is None


# --------------------------------------------------------------------------- #
# count means records
# --------------------------------------------------------------------------- #
def _entry(ark: str, names: list[str]) -> dict:
    """A search entry listing a principal plus whoever else is on the record."""
    persons = []
    for i, name in enumerate(names):
        person: dict = {"names": [{"nameForms": [{"fullText": name}]}]} if name else {}
        if i == 0:
            person["principal"] = True
        persons.append(person)
    return {"id": ark, "score": 1.0, "content": {"gedcomx": {"persons": persons}}}


@respx.mock
async def test_count_returns_that_many_records(monkeypatch, auth_config):
    """One hit per record, not per person named on it.

    A record lists the person matched plus a household, a spouse or a
    witness. Flattening those made count meaningless: asking for 2 returned
    4, and the extras were mostly unnamed.
    """
    _wired(monkeypatch, auth_config)
    respx.get(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": 99,
                "entries": [
                    _entry("A", ["Ezra Pettibone", None]),
                    _entry("B", ["Ezra Pettybone", None]),
                ],
            },
        )
    )
    out = await call_tool("search_records", surname="Pettibone", count=2)
    assert out["returned"] == 2
    assert [r["ark"] for r in out["results"]] == ["A", "B"]


@respx.mock
async def test_the_principal_is_the_match_not_the_first_person(monkeypatch, auth_config):
    """The matched person is flagged; order is not a reliable stand-in."""
    _wired(monkeypatch, auth_config)
    entry = _entry("A", ["Someone Else", "Ezra Pettibone"])
    entry["content"]["gedcomx"]["persons"][0].pop("principal")
    entry["content"]["gedcomx"]["persons"][1]["principal"] = True
    respx.get(SEARCH).mock(
        return_value=httpx.Response(200, json={"results": 1, "entries": [entry]})
    )
    out = await call_tool("search_records", surname="Pettibone")
    assert out["results"][0]["name"] == "Ezra Pettibone"


@respx.mock
async def test_others_on_the_record_are_reported_not_dropped(monkeypatch, auth_config):
    """Who else a record names is often why it is the right record."""
    _wired(monkeypatch, auth_config)
    respx.get(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": 1,
                "entries": [_entry("A", ["Ezra Pettibone", "Zilpha Pettibone", None])],
            },
        )
    )
    out = await call_tool("search_records", surname="Pettibone")
    assert out["results"][0]["also_on_this_record"] == ["Zilpha Pettibone"]


@respx.mock
async def test_the_total_is_reported(monkeypatch, auth_config):
    """Knowing a search matched 650,000 records is what prompts narrowing."""
    _wired(monkeypatch, auth_config)
    respx.get(SEARCH).mock(
        return_value=httpx.Response(
            200,
            json={
                "results": 652464,
                "entries": [_entry("A", ["Ezra Pettibone"])],
            },
        )
    )
    out = await call_tool("search_records", surname="Pettibone")
    assert out["total"] == 652464


async def test_there_is_only_one_record_search_tool():
    """A second tool with a subset of these parameters is a trap.

    It silently accepted and ignored the filters it did not define, so a
    collection-scoped search through it returned unscoped results and said
    nothing. The subset tool is gone.
    """
    from familysearch_mcp.server import mcp

    names = {t.name for t in await mcp.list_tools()}
    assert "search_records" in names
    assert "search_records_advanced" not in names
