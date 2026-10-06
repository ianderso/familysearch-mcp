"""search_records says how each criterion was applied, so a negative can be bounded.

Reported from real use, three ways: exact held the names but not the birth
year; a residence of "White, Arkansas" brought hits from other Arkansas
counties; and "Saline District, Cherokee Nation, Indian Territory" found
nothing. With no word on what had been relaxed, a nil result could not be
read as a negative.

What FamilySearch does with each criterion was measured live on 2026-10-06
and is set out in ``docs/API-NOTES.md``. The responses replayed here were
recorded that day from the website search, for the surname Smith and a
residence of White, Arkansas: two hits kept from each, their names replaced
with invented ones, and the place facet cut to a few counties.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import SEARCH_URL, FamilySearchClient
from familysearch_mcp.shape import place_buckets

from .conftest import call_tool

FIXTURES = Path(__file__).parent / "fixtures" / "search"
WHITE_COUNTY = ("f.residencePlace2", "10,Arkansas,White")


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def authenticated(monkeypatch, auth_config):
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))


def _search_answering(**by_filter: str):
    """The search service: the first fixture, or another when a place filter is sent."""

    def answer(request: httpx.Request) -> httpx.Response:
        for value, name in by_filter.items():
            if value != "default" and request.url.params.get(WHITE_COUNTY[0]) == value:
                return httpx.Response(200, json=_fixture(name))
        return httpx.Response(200, json=_fixture(by_filter["default"]))

    return answer


# --------------------------------------------------------------------------- #
# Names and years
# --------------------------------------------------------------------------- #
@respx.mock
async def test_exact_is_sent_on_every_criterion(authenticated):
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    await call_tool(
        "search_records",
        given="Ezra",
        surname="Pettibone",
        birth_year=1751,
        death_year=1826,
        spouse_surname="Chesebrough",
        exact=True,
    )
    params = route.calls.last.request.url.params
    for term in ("givenName", "surname", "birthLikeDate", "deathLikeDate", "spouseSurname"):
        assert params[f"q.{term}.exact"] == "on", term


@respx.mock
async def test_the_result_says_each_criterion_was_applied_exactly(authenticated):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"results": 0}))
    out = await call_tool(
        "search_records", given="Ezra", surname="Pettibone", birth_year=1751, exact=True
    )
    assert set(out["filters"]["exact"]) == {"given", "surname", "birth_year"}
    assert out["filters"]["relaxed"] == {} and out["filters"]["ignored"] == {}
    assert "that year only" in out["filters"]["exact"]["birth_year"]
    assert "no year is left out" in out["filters"]["exact"]["birth_year"]


@respx.mock
async def test_without_exact_the_result_says_how_far_each_was_relaxed(authenticated):
    """A record that gives no birth year at all still matches "born 1751"."""
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"results": 0}))
    out = await call_tool(
        "search_records", given="Ezra", surname="Pettibone", birth_year=1751, spouse_given="Mary"
    )
    relaxed = out["filters"]["relaxed"]
    assert "within 5 years" in relaxed["birth_year"]
    assert "no year is not left out" in relaxed["birth_year"]
    assert "middle name" in relaxed["given"]
    assert relaxed["surname"] == "spelling variants match"
    assert "no such relative is not left out" in relaxed["spouse_given"]
    assert out["filters"]["exact"] == {}


@respx.mock
async def test_loose_says_every_criterion_only_ranks(authenticated):
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool(
        "search_records", surname="Pettibone", residence_place="White, Arkansas", loose=True
    )
    assert set(out["filters"]["ignored"]) == {"surname", "residence_place"}
    assert "need not match" in out["filters"]["ignored"]["surname"]
    assert "c.residencePlace1" not in route.calls.last.request.url.params


@respx.mock
async def test_a_collection_and_a_record_type_are_exact_filters(authenticated):
    """A collection id in the old ``sd_c_`` form is sent as the collection."""
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool(
        "search_records", surname="Pettibone", collection_id="sd_c_1417683", record_type="census"
    )
    assert route.calls.last.request.url.params["f.collectionId"] == "1417683"
    assert set(out["filters"]["exact"]) == {"collection_id", "record_type"}


# --------------------------------------------------------------------------- #
# Places
# --------------------------------------------------------------------------- #
@respx.mock
async def test_an_exact_place_is_held_to_the_county_it_names(authenticated):
    """An exact "White, Arkansas" also matched the White townships of other counties.

    The place facet names each hit's county; its bucket for White County
    carries the filter that selects it, and the search is asked again with
    that filter. Recorded: 10,225 matched the words, 9,231 lived in White
    County.
    """
    route = respx.get(SEARCH_URL).mock(
        side_effect=_search_answering(
            default="residence-exact.json", **{WHITE_COUNTY[1]: "residence-exact-narrowed.json"}
        )
    )
    out = await call_tool(
        "search_records", surname="Smith", residence_place="White, Arkansas", exact=True
    )
    first, second = (call.request.url.params for call in route.calls)
    assert first["c.residencePlace2"] == "on"
    assert WHITE_COUNTY[0] not in first
    assert second[WHITE_COUNTY[0]] == WHITE_COUNTY[1]
    assert out["total"] == 9231
    held = out["filters"]["exact"]["residence_place"]
    assert held.startswith("within White, Arkansas, United States of America")
    assert "994 hits elsewhere were left out" in held


@respx.mock
async def test_a_relaxed_place_says_how_many_hits_are_in_it(authenticated):
    """Of 3,968,744 hits for a residence of White, Arkansas, 9,570 lived there."""
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_fixture("residence-loose.json"))
    )
    out = await call_tool("search_records", surname="Smith", residence_place="White, Arkansas")
    assert route.call_count == 1
    relaxed = out["filters"]["relaxed"]["residence_place"]
    assert "no such place is not left out" in relaxed
    assert "9,570 of 3,968,744 hits are in White, Arkansas, United States of America" in relaxed


@respx.mock
async def test_an_exact_place_no_record_carries_says_a_coarser_one_cannot_match(authenticated):
    """The index gives "Cherokee Nation, Indian Territory", never the district."""
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_fixture("residence-exact-none.json"))
    )
    out = await call_tool(
        "search_records",
        surname="Smith",
        residence_place="Saline District, Cherokee Nation, Indian Territory",
        exact=True,
    )
    assert route.call_count == 1
    assert out["total"] == 0
    assert "coarser place" in out["filters"]["exact"]["residence_place"]


@respx.mock
async def test_a_place_below_the_county_is_held_to_the_county(authenticated):
    """The facet stops at the county; a town below it is matched by its words."""
    route = respx.get(SEARCH_URL).mock(
        side_effect=_search_answering(
            default="residence-exact.json", **{WHITE_COUNTY[1]: "residence-exact-narrowed.json"}
        )
    )
    out = await call_tool(
        "search_records", surname="Smith", residence_place="Beebe, White, Arkansas", exact=True
    )
    assert route.calls.last.request.url.params[WHITE_COUNTY[0]] == WHITE_COUNTY[1]
    assert "below that, by its words" in out["filters"]["exact"]["residence_place"]


@respx.mock
async def test_a_place_every_hit_is_already_in_is_not_asked_again(authenticated):
    """Every hit lived in Arkansas, so holding the search to Arkansas changes nothing."""
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_fixture("residence-exact.json"))
    )
    out = await call_tool("search_records", surname="Smith", residence_place="Arkansas", exact=True)
    assert route.call_count == 1
    assert out["filters"]["exact"]["residence_place"] == (
        "within Arkansas, United States of America, by FamilySearch's place filter"
    )


@respx.mock
async def test_a_place_the_hits_do_not_carry_says_where_they_are(authenticated):
    route = respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_fixture("residence-exact.json"))
    )
    out = await call_tool(
        "search_records", surname="Smith", residence_place="Ontario, Canada", exact=True
    )
    assert route.call_count == 1
    relaxed = out["filters"]["relaxed"]["residence_place"]
    assert "a word it does not recognise is dropped" in relaxed
    assert (
        "the hits giving one are mostly in White, Arkansas, United States of America (9,231)"
        in (relaxed)
    )


@pytest.mark.parametrize(
    "written",
    [
        "White, Arkansas",
        "White County, Arkansas",
        "White Co., Arkansas, USA",
        "white, arkansas, united states",
        "White, Arkansas, United States of America",
    ],
)
def test_the_ways_a_county_is_written_all_find_it(written):
    rows = place_buckets(_fixture("residence-exact.json"), "residencePlace")
    found, below = server._locate_place(rows, written)
    assert found is not None and found["filter"] == WHITE_COUNTY
    assert below == 0


def test_a_country_below_its_region_is_found():
    rows = place_buckets(_fixture("residence-exact.json"), "residencePlace")
    found, _ = server._locate_place(rows, "England")
    assert found is not None and found["filter"] == ("f.residencePlace1", "9,England")


# --------------------------------------------------------------------------- #
# Paging
# --------------------------------------------------------------------------- #
@respx.mock
async def test_a_page_familysearch_did_not_serve_is_refused(authenticated):
    """Asked for offset 1,001, it answered the first page again, index 0, no error.

    Recorded 2026-10-06. The same request had answered from 1,001 minutes
    before, so this cannot be a fixed ceiling; the answer's index is checked.
    """
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(200, json=_fixture("offset-past-the-end.json"))
    )
    out = await call_tool("search_records", surname="Smith", offset=1001)
    assert out["error"] == "offset_ignored"
    assert "answered from 0" in out["message"]


@respx.mock
async def test_a_page_not_served_is_refused_before_a_place_is_held(authenticated):
    """No second request is built on an answer that was the wrong page."""
    unpaged = {**_fixture("residence-exact.json"), "index": 0}
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=unpaged))
    out = await call_tool(
        "search_records", surname="Smith", residence_place="White, Arkansas", exact=True, offset=40
    )
    assert out["error"] == "offset_ignored"
    assert route.call_count == 1
