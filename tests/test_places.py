"""The anonymous gazetteer: the part of this server every install can use.

These are the tools that need no credentials, so they carry the most weight.
The historical-jurisdiction behaviour is the reason the section exists: a
record naming a district that was abolished in 1826 is ordinary, and filing
it under the modern county is an error nothing downstream will catch.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient
from familysearch_mcp.config import Config

from .conftest import call_tool

DESCRIPTION = "https://api.familysearch.org/platform/places/description/7344697"
SEARCH = "https://api.familysearch.org/platform/places/search"


@pytest.fixture
def unconfigured(monkeypatch):
    """A server with no token at all, which is what these tools must work on."""
    config = Config(environment="production", timeout=5.0)
    monkeypatch.setattr(server.state, "config", config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(config))
    return config


@respx.mock
async def test_get_place_works_with_no_token(unconfigured, place_description_document):
    """The whole point of the anonymous section: no credentials, real answers."""
    route = respx.get(DESCRIPTION).mock(
        return_value=httpx.Response(200, json=place_description_document)
    )
    out = await call_tool("get_place", place_id="7344697")
    assert "error" not in out
    assert out["name"] == "Pendleton District"
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_get_place_reports_when_the_jurisdiction_ceased_to_exist(
    unconfigured, place_description_document
):
    """The span is the field that stops a record being filed under the wrong county."""
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(200, json=place_description_document))
    out = await call_tool("get_place", place_id="7344697")
    assert out["existed"] == {"original": None, "from": "1785", "to": "1826"}


@respx.mock
async def test_get_place_returns_the_chain_above_it(unconfigured, place_description_document):
    """One read carries the ancestors; the tool must not discard them."""
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(200, json=place_description_document))
    out = await call_tool("get_place", place_id="7344697")
    assert [j["name"] for j in out["jurisdictions"]] == [
        "South Carolina",
        "United States",
    ]


@respx.mock
async def test_get_place_carries_coordinates_when_there_are_any(
    unconfigured, place_description_document
):
    """Coordinates are what a properly-formed place record wants."""
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(200, json=place_description_document))
    out = await call_tool("get_place", place_id="7344697")
    assert out["latitude"] == 34.6 and out["longitude"] == -82.8


@respx.mock
async def test_get_place_of_an_unknown_id_is_not_found(unconfigured):
    """A 404 must read as 'no such place', not as a credential problem."""
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(404, json={}))
    out = await call_tool("get_place", place_id="7344697")
    assert out["error"] == "not_found"


@respx.mock
async def test_get_place_of_an_empty_document_is_not_found(unconfigured):
    """A 200 with no places is still nothing found, and must say so."""
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(200, json={"places": []}))
    assert (await call_tool("get_place", place_id="7344697"))["error"] == "not_found"


@respx.mock
async def test_jurisdictions_are_ordered_innermost_first(unconfigured, place_description_document):
    """Reading order is the place, then the county, then the state, then the country."""
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(200, json=place_description_document))
    out = await call_tool("get_place_jurisdictions", place_id="7344697")
    assert [level["name"] for level in out["chain"]] == [
        "Pendleton District",
        "South Carolina",
        "United States",
    ]
    assert out["depth"] == 3


@respx.mock
async def test_jurisdictions_resolve_fragment_references_not_array_order(
    unconfigured, place_description_document
):
    """The array is flat and unordered; only the references say what contains what.

    Shuffling the ancestors must not change the chain, or the walk is really
    just trusting document order.
    """
    shuffled = {"places": list(reversed(place_description_document["places"]))}
    shuffled["places"] = [
        place_description_document["places"][0],
        *shuffled["places"][:-1],
    ]
    respx.get(DESCRIPTION).mock(return_value=httpx.Response(200, json=shuffled))
    out = await call_tool("get_place_jurisdictions", place_id="7344697")
    assert [level["name"] for level in out["chain"]] == [
        "Pendleton District",
        "South Carolina",
        "United States",
    ]


@respx.mock
async def test_a_circular_jurisdiction_reference_terminates(unconfigured):
    """Bad data must not hang the walk; a cycle ends it."""
    respx.get(DESCRIPTION).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "7344697",
                        "names": [{"value": "A"}],
                        "jurisdiction": {"resource": "#B"},
                    },
                    {
                        "id": "B",
                        "names": [{"value": "B"}],
                        "jurisdiction": {"resource": "#7344697"},
                    },
                ]
            },
        )
    )
    out = await call_tool("get_place_jurisdictions", place_id="7344697")
    assert [level["name"] for level in out["chain"]] == ["A", "B"]


@respx.mock
async def test_jurisdictions_fall_back_to_joining_the_chain_for_a_full_name(
    unconfigured,
):
    """Not every description carries a display block; the chain still reads."""
    respx.get(DESCRIPTION).mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "7344697",
                        "names": [{"value": "Kaskaskia"}],
                        "jurisdiction": {"resource": "#2"},
                    },
                    {"id": "2", "names": [{"value": "Randolph"}]},
                ]
            },
        )
    )
    out = await call_tool("get_place_jurisdictions", place_id="7344697")
    assert out["full_name"] == "Kaskaskia, Randolph"


@respx.mock
async def test_search_places_at_date_asks_for_the_year(unconfigured, place_search_feed):
    """The year has to reach the query, or the answer is the modern jurisdiction.

    FamilySearch spells a required AD year '+date:+1850': the outer plus
    makes the clause required, the inner one marks the era.
    """
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json=place_search_feed))
    out = await call_tool("search_places_at_date", name="Pendleton", year=1850)
    query = route.calls.last.request.url.params["q"]
    assert 'name:"Pendleton"' in query
    assert "+date:+1850" in query
    assert out["as_of_year"] == 1850


@respx.mock
async def test_search_places_at_date_can_be_confined_to_a_jurisdiction(
    unconfigured, place_search_feed
):
    """An ambiguous name needs a region, and '~' means anywhere beneath it."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json=place_search_feed))
    await call_tool("search_places_at_date", name="Kaskaskia", year=1850, within_place_id="1")
    assert "+parentId:1~" in route.calls.last.request.url.params["q"]


@respx.mock
async def test_search_places_at_date_works_with_no_token(unconfigured, place_search_feed):
    """Historical place resolution is available to an install with no setup."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json=place_search_feed))
    out = await call_tool("search_places_at_date", name="Pendleton", year=1850)
    assert out["returned"] == 1
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_place_search_negotiates_the_atom_representation(unconfigured, place_search_feed):
    """The search resource does not offer plain GEDCOM X; asking for it 406s."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json=place_search_feed))
    await call_tool("search_places", name="Kaskaskia")
    assert route.calls.last.request.headers["Accept"] == "application/x-gedcomx-atom+json"


@respx.mock
async def test_a_place_search_returning_no_content_is_an_empty_result(unconfigured):
    """The gazetteer answers 204 when nothing matches; that is not an error."""
    respx.get(SEARCH).mock(return_value=httpx.Response(204))
    out = await call_tool("search_places", name="Nowhere At All")
    assert out["returned"] == 0
    assert out["places"] == []


@respx.mock
async def test_a_quote_in_a_place_name_cannot_break_the_query(unconfigured, place_search_feed):
    """The name is interpolated into a quoted clause; a stray quote would escape it."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json=place_search_feed))
    await call_tool("search_places", name='St. Mary"s +typeId:1')
    query = route.calls.last.request.url.params["q"]
    assert query.count('"') == 2
