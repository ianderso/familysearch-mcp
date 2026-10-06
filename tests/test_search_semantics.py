"""How FamilySearch's search actually behaves, and what this server does about it.

Two behaviours here are surprising enough that they were reported as bugs:
a criterion that does not narrow anything, and a catalogue search that finds
nothing. Neither was a bug in the API. Both are pinned so the handling cannot
quietly regress.
"""

from __future__ import annotations

import json
from pathlib import Path

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
COLLECTION_FIXTURES = Path(__file__).parent / "fixtures" / "collections"


def _catalogue_page(ids: list[str]) -> dict:
    """A page as the listing sends one: the container, then each collection.

    The shape is the recorded ``page-start-0.json``'s, cut to what is read.
    """
    container = {
        "about": "https://www.familysearch.org/platform/records/collections",
        "id": "sd_c",
        "resourceType": "http://familysearch.org/types/resources/Container",
    }
    return {
        "description": "#sd_c",
        "sourceDescriptions": [container]
        + [
            {
                "id": f"sd_c_{i}",
                "about": f"https://api.familysearch.org/platform/records/collections/{i}",
                "resourceType": "http://gedcomx.org/Collection",
                "titles": [{"value": f"Collection {i}"}],
            }
            for i in ids
        ],
    }


EMPTY = {"description": "#sd_c", "sourceDescriptions": []}


def _starts(route) -> list[str | None]:
    return [call.request.url.params.get("start") for call in route.calls]


def _no_disk(monkeypatch) -> list:
    """Keep the walk off the disk cache, and record what would be written."""
    written: list = []
    monkeypatch.setattr(server, "_read_catalogue_cache", lambda: None)
    monkeypatch.setattr(server, "_write_catalogue_cache", lambda e, m: written.append((e, m)))
    return written


@respx.mock
async def test_the_catalogue_is_walked_not_sampled(monkeypatch, anon_config):
    """The old bug: one page was fetched and filtered.

    With ~3,400 collections paged at ninety, matching against the first page
    alone found nothing for most queries -- 'Iowa' among them, which is what
    was reported.
    """
    _wired(monkeypatch, anon_config)
    pages = [_catalogue_page([str(n) for n in range(0, 90)]), _catalogue_page(["iowa1", "iowa2"])]
    respx.get(CATALOGUE).mock(
        side_effect=[httpx.Response(200, json=p) for p in [*pages, EMPTY, EMPTY]]
    )
    _no_disk(monkeypatch)

    out = await call_tool("search_collections", query="Collection iowa1")
    assert out["catalogue"]["collections"] == 92
    assert out["catalogue"]["complete"] is True
    assert out["matched"] == 1


@respx.mock
async def test_the_walk_steps_by_the_window_not_by_what_came_back(monkeypatch, anon_config):
    """A page is 100 slots holding the collections visible in them, 78 to 100.

    The walk used to step ``start`` by the number a page returned, the
    container included. After a full page it stepped 101 and skipped a
    collection: verified live 2026-10-06, a walk that way found 3,826 where
    stepping by 100 found 3,828.
    """
    _wired(monkeypatch, anon_config)
    full = _catalogue_page([str(n) for n in range(100)])
    route = respx.get(CATALOGUE).mock(
        side_effect=[
            httpx.Response(200, json=p) for p in [full, _catalogue_page(["x"]), EMPTY, EMPTY]
        ]
    )
    _no_disk(monkeypatch)
    await call_tool("search_collections")
    assert _starts(route) == [None, "100", "200", "300"]
    assert {call.request.url.params["count"] for call in route.calls} == {"100"}


@respx.mock
async def test_one_empty_window_does_not_end_the_walk(monkeypatch, anon_config):
    """FamilySearch reports no total, so the end is two empty windows in a row."""
    _wired(monkeypatch, anon_config)
    pages = [_catalogue_page(["a"]), EMPTY, _catalogue_page(["b"]), EMPTY, EMPTY]
    respx.get(CATALOGUE).mock(side_effect=[httpx.Response(200, json=p) for p in pages])
    _no_disk(monkeypatch)
    out = await call_tool("search_collections")
    assert [c["id"] for c in out["collections"]] == ["a", "b"]


@respx.mock
async def test_a_walk_cut_short_is_reported_and_not_cached(monkeypatch, anon_config):
    """Reported from real use: a short walk was cached and trusted for a month.

    The cache held 3,443 of 3,827 collections, and nothing in a result said
    so. A walk that stops at the page limit is now marked incomplete, kept
    for this session only, and every result says so.
    """
    _wired(monkeypatch, anon_config)
    monkeypatch.setattr(server, "CATALOGUE_PAGE_LIMIT", 2)
    respx.get(CATALOGUE).mock(
        side_effect=[httpx.Response(200, json=_catalogue_page([f"p{n}"])) for n in range(2)]
    )
    written = _no_disk(monkeypatch)
    out = await call_tool("search_collections")
    assert out["catalogue"]["complete"] is False
    assert "2-page limit" in out["catalogue"]["warning"]
    assert "refresh=true" in out["catalogue"]["warning"]
    assert written and written[0][1]["complete"] is False


@respx.mock
async def test_a_window_repeated_ends_the_walk_incomplete(monkeypatch, anon_config):
    """If ``start`` were ignored, the same page would come back to the limit."""
    _wired(monkeypatch, anon_config)
    respx.get(CATALOGUE).mock(return_value=httpx.Response(200, json=_catalogue_page(["a"])))
    _no_disk(monkeypatch)
    out = await call_tool("search_collections")
    assert out["catalogue"]["complete"] is False
    assert "repeated" in out["catalogue"]["warning"]


async def test_an_incomplete_walk_is_never_written(monkeypatch, tmp_path):
    cache = tmp_path / "collections.json"
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    server._write_catalogue_cache([{"id": "a"}], {"fetched_at": 1.0, "complete": False})
    assert not cache.exists()


@respx.mock
async def test_the_catalogue_is_fetched_once_per_session(monkeypatch, anon_config):
    """Walking it costs about two minutes; doing that per query is not viable."""
    _wired(monkeypatch, anon_config)
    route = respx.get(CATALOGUE).mock(
        side_effect=[
            httpx.Response(200, json=_catalogue_page(["a", "b"])),
            httpx.Response(200, json=EMPTY),
            httpx.Response(200, json=EMPTY),
        ]
    )
    _no_disk(monkeypatch)

    await call_tool("search_collections", query="Collection")
    calls_after_first = route.call_count
    await call_tool("search_collections", query="Collection")
    assert route.call_count == calls_after_first


def _cache(path, *, age: float = 0, **fields) -> None:
    import json as _json
    import time

    body = {
        "version": server.CATALOGUE_CACHE_VERSION,
        "fetched_at": time.time() - age,
        "complete": True,
        "pages": 44,
        "collections": [{"id": "c1", "title": "Iowa, Births"}],
        **fields,
    }
    path.write_text(_json.dumps(body))


async def test_a_stale_disk_cache_is_ignored(monkeypatch, tmp_path):
    """A cached catalogue past its age is refetched rather than trusted."""
    cache = tmp_path / "collections.json"
    _cache(cache, age=server.CATALOGUE_MAX_AGE + 60)
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() is None


async def test_a_fresh_complete_disk_cache_is_used(monkeypatch, tmp_path):
    """The whole point: a restart should not pay the walk again."""
    cache = tmp_path / "collections.json"
    _cache(cache)
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    entries, meta = server._read_catalogue_cache()
    assert entries == [{"id": "c1", "title": "Iowa, Births"}]
    assert meta["complete"] is True


async def test_a_cache_not_marked_complete_is_not_trusted(monkeypatch, tmp_path):
    cache = tmp_path / "collections.json"
    _cache(cache, complete=False)
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() is None


async def test_a_cache_from_an_earlier_release_is_walked_again(monkeypatch, tmp_path):
    """It cannot say whether its walk reached the end, and that walk skipped some."""
    import json as _json
    import time

    cache = tmp_path / "collections.json"
    cache.write_text(_json.dumps({"fetched_at": time.time(), "collections": [{"id": "sd_c_1"}]}))
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() is None


@pytest.mark.parametrize("body", ["not json", '{"collections": []}', "{}", "[]"])
async def test_an_unusable_disk_cache_is_ignored(monkeypatch, tmp_path, body):
    """A corrupt or empty cache must not shadow a real fetch."""
    cache = tmp_path / "collections.json"
    cache.write_text(body)
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    assert server._read_catalogue_cache() is None


@respx.mock
async def test_a_result_says_how_big_and_how_old_the_catalogue_is(monkeypatch, tmp_path):
    """So a title not found can be judged: is the catalogue whole, and how recent?"""
    cache = tmp_path / "collections.json"
    _cache(cache, age=3 * 86400)
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    monkeypatch.setattr(server.state, "catalogue", None)
    out = await call_tool("search_collections", query="iowa")
    assert out["catalogue"]["collections"] == 1
    assert out["catalogue"]["complete"] is True
    assert out["catalogue"]["age_days"] == 3.0
    assert "warning" not in out["catalogue"]
    assert not respx.calls


@respx.mock
async def test_a_walk_is_written_with_its_completeness(monkeypatch, anon_config, tmp_path):
    _wired(monkeypatch, anon_config)
    cache = tmp_path / "collections.json"
    monkeypatch.setattr(server, "CATALOGUE_CACHE", cache)
    respx.get(CATALOGUE).mock(
        side_effect=[httpx.Response(200, json=p) for p in [_catalogue_page(["a"]), EMPTY, EMPTY]]
    )
    await call_tool("search_collections")
    import json as _json

    written = _json.loads(cache.read_text())
    assert written["version"] == server.CATALOGUE_CACHE_VERSION
    assert written["complete"] is True and written["pages"] == 3


@respx.mock
async def test_each_collection_carries_the_id_the_other_tools_take(monkeypatch, anon_config):
    """The listing's ``sd_c_4496122`` is local to it; ``4496122`` is the collection.

    Recorded 2026-10-06 (``collections/page-start-0.json``). Verified live
    that day: the ``sd_c_`` form is a 400 from the search filter and from
    the collection route. The container each page repeats is not a
    collection.
    """
    _wired(monkeypatch, anon_config)
    page = json.loads((COLLECTION_FIXTURES / "page-start-0.json").read_text(encoding="utf-8"))
    respx.get(CATALOGUE).mock(
        side_effect=[httpx.Response(200, json=p) for p in [page, EMPTY, EMPTY]]
    )
    _no_disk(monkeypatch)
    out = await call_tool("search_collections")
    ids = [c["id"] for c in out["collections"]]
    assert ids[0] == "4496122"
    assert all(i.isdigit() for i in ids)
    assert out["catalogue"]["collections"] == len(page["sourceDescriptions"]) - 1


# --------------------------------------------------------------------------- #
# Title words match whole words first
# --------------------------------------------------------------------------- #
@pytest.fixture
def titles(monkeypatch, anon_config):
    """Real catalogue titles, as recorded in the 2026-10-06 walk.

    ``collections/titles-indian-indiana.json`` is one page assembled from
    entries of that walk: collections whose titles hold "Indian" as a word
    or inside "Indiana", and two with "México".
    """
    _wired(monkeypatch, anon_config)
    page = json.loads(
        (COLLECTION_FIXTURES / "titles-indian-indiana.json").read_text(encoding="utf-8")
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.get(CATALOGUE).mock(
            side_effect=[httpx.Response(200, json=p) for p in [page, EMPTY, EMPTY]]
        )
        _no_disk(monkeypatch)
        yield


async def test_a_whole_word_ranks_above_one_found_inside_another(titles):
    """Reported from real use: "Indian" listed the Indiana collections first."""
    out = await call_tool("search_collections", query="Indian")
    shown = [(c["title"].split(",")[0], c.get("partial_match", False)) for c in out["collections"]]
    whole = [t for t, partial in shown if not partial]
    assert out["matched_whole_words"] == 3
    assert whole == ["Washington", "Fiji", "Fiji"]
    assert all(t == "Indiana" for t, partial in shown if partial)
    assert [partial for _, partial in shown] == sorted(partial for _, partial in shown)


async def test_a_whole_word_match_may_differ_by_a_plural(titles):
    """ "Indians" is a whole word for "Indian"; "record" finds "Records"."""
    out = await call_tool("search_collections", query="indian application")
    assert [c["id"] for c in out["collections"]] == ["2300675"]
    assert "partial_match" not in out["collections"][0]
    out = await call_tool("search_collections", query="church record")
    assert sorted(c["id"] for c in out["collections"]) == ["1837908", "2790248"]
    assert out["matched_whole_words"] == 2


async def test_accents_do_not_stop_a_match(titles):
    out = await call_tool("search_collections", query="mexico civil")
    assert [c["title"] for c in out["collections"]] == [
        "Mexico, México, Civil Registration, 1861-1941"
    ]


async def test_a_partial_match_does_not_crowd_out_a_whole_one(titles):
    out = await call_tool("search_collections", query="Indian", count=3)
    assert out["returned"] == 3
    assert not any(c.get("partial_match") for c in out["collections"])


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
