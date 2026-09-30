"""Browsing: place children, film waypoints, and records on an image.

These three reach what searching cannot. Indexing is incomplete across most
of the archive, so a record that no search finds may still be on an image you
can browse to -- and a page you are already reading usually carries dozens of
people the index never connected to each other.
"""

from __future__ import annotations

import httpx
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient

from .conftest import call_tool

B = "https://api.familysearch.org/platform"


def _anon(monkeypatch, cfg):
    monkeypatch.setattr(server.state, "config", cfg)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(cfg))


# --------------------------------------------------------------------------- #
# get_place_children
# --------------------------------------------------------------------------- #
@respx.mock
async def test_place_children_need_no_token(monkeypatch, anon_config):
    """The downward jurisdiction walk is reference data, so it stays open."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/places/description/442/children").mock(
        return_value=httpx.Response(
            200,
            json={
                "places": [
                    {
                        "id": "10919336",
                        "display": {
                            "fullName": "Los Angeles, Alta California, Mexico",
                            "name": "Los Angeles",
                            "type": "Town",
                        },
                    },
                ]
            },
        )
    )
    out = await call_tool("get_place_children", place_id="442")
    assert out["child_count"] == 1
    assert out["children"][0]["full_name"].startswith("Los Angeles")
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_a_place_with_no_children_is_not_an_error(monkeypatch, anon_config):
    """A town contains nothing; that is a leaf, not a failure."""
    _anon(monkeypatch, anon_config)
    respx.get(f"{B}/places/description/999/children").mock(
        return_value=httpx.Response(200, json={"places": []})
    )
    out = await call_tool("get_place_children", place_id="999")
    assert out["child_count"] == 0


# --------------------------------------------------------------------------- #
# browse_waypoints
# --------------------------------------------------------------------------- #
WAYPOINTS = {
    "sourceDescriptions": [
        {
            "id": "sd_c_1916078",
            "resourceType": "http://gedcomx.org/Collection",
            "titles": [{"value": "California Passenger Lists"}],
        },
        {
            "id": "sd_cr_1916078",
            "resourceType": "http://gedcomx.org/Collection",
            "titles": [{"value": "California Passenger Lists"}],
        },
        {
            "id": "sd_3",
            "resourceType": "http://gedcomx.org/Collection",
            "titles": [{"value": "001 - May 1, 1893 - Feb 7, 1896"}],
        },
        {
            "id": "sd_4",
            "resourceType": "http://gedcomx.org/Collection",
            "titles": [{"value": "002 - Mar 4, 1896 - Oct 2, 1898"}],
        },
    ]
}


@respx.mock
async def test_browsing_a_collection_skips_its_own_entries(monkeypatch, anon_config):
    """The response repeats the node itself twice before its children.

    Reporting those as children would make every level look like it contains
    itself.
    """
    _anon(monkeypatch, anon_config)
    respx.get(f"{B}/records/collections/1916078/waypoints").mock(
        return_value=httpx.Response(200, json=WAYPOINTS)
    )
    out = await call_tool("browse_waypoints", collection_id="1916078")
    assert out["child_count"] == 2
    assert out["children"][0]["title"].startswith("001")
    assert out["level"] == "collection"


@respx.mock
async def test_browsing_a_waypoint_uses_the_waypoint_route(monkeypatch, anon_config):
    """Descending a level is a different endpoint, not the same one."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/waypoints/sd_3").mock(
        return_value=httpx.Response(200, json={"sourceDescriptions": []})
    )
    out = await call_tool("browse_waypoints", waypoint_id="sd_3")
    assert route.called
    assert out["level"] == "waypoint"


@respx.mock
async def test_waypoints_need_no_token(monkeypatch, anon_config):
    """Browsing the film structure is open, which is what makes it useful."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/collections/1916078/waypoints").mock(
        return_value=httpx.Response(200, json=WAYPOINTS)
    )
    await call_tool("browse_waypoints", collection_id="1916078")
    assert "Authorization" not in route.calls.last.request.headers


async def test_browsing_without_a_target_is_refused(monkeypatch, anon_config):
    """One of the two ids is required; neither is not a starting point."""
    _anon(monkeypatch, anon_config)
    out = await call_tool("browse_waypoints")
    assert out["error"] == "no_target"


# --------------------------------------------------------------------------- #
# get_records_on_image
# --------------------------------------------------------------------------- #
IMAGE_RECORDS = {
    "sourceDescriptions": [
        {
            "id": "9MVG-BPYL",
            "about": "https://www.familysearch.org/ark:/61903/1:2:9MVG-BPYL",
            "resourceType": "http://gedcomx.org/Record",
        },
        {
            "id": "9MVG-BPYG",
            "about": "https://www.familysearch.org/ark:/61903/1:2:9MVG-BPYG",
            "resourceType": "http://gedcomx.org/Record",
        },
    ]
}


@respx.mock
async def test_records_on_an_image_are_returned_as_readable_arks(monkeypatch, auth_config):
    """A bare id is not actionable; the 1:2: ark can be fed to get_record.

    Verified live 2026-09-23: a manifest page returned 28 records, each
    carrying only an id, an ark and a link -- no names at all.
    """
    _anon(monkeypatch, auth_config)
    respx.get(f"{B}/records/images/3:1:33SQ-G5LD-93NY/records").mock(
        return_value=httpx.Response(200, json=IMAGE_RECORDS)
    )
    out = await call_tool("get_records_on_image", image_ark="3:1:33SQ-G5LD-93NY")
    assert out["record_count"] == 2
    assert out["records"][0]["ark"] == "1:2:9MVG-BPYL"
    assert "not names" in out["note"]


async def test_records_on_an_image_need_a_token(monkeypatch, anon_config):
    """Unlike the browse routes, this one is gated. Verified live: 401."""
    _anon(monkeypatch, anon_config)
    out = await call_tool("get_records_on_image", image_ark="3:1:33SQ-G5LD-93NY")
    assert out["error"] == "auth_required"
