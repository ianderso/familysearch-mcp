"""Browsing: place children, film waypoints, and records on an image.

These three reach what searching cannot. Indexing is incomplete across most
of the archive, so a record that no search finds may still be on an image you
can browse to -- and a page you are already reading usually carries dozens of
people the index never connected to each other.
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
#: Replayed from tests/fixtures/waypoints/, recorded live and anonymously on
#: 2026-10-06 from "Tennessee, Probate Court Books, 1795-1927" (1909088):
#: the collection cut to its first four counties, Grundy County cut to its
#: first four volumes, and one volume read three images at a time from each
#: end. Titles in other languages were dropped. The error bodies are as sent.
WAYPOINT_FIXTURES = Path(__file__).parent / "fixtures" / "waypoints"
TENNESSEE = "1909088"
GRUNDY = "M6QS-12W:179638101"
BONDS = "M6QS-124:179638101,179638102"


def _fixture(name: str) -> dict:
    return json.loads((WAYPOINT_FIXTURES / name).read_text(encoding="utf-8"))


def _recorded(name: str) -> httpx.Response:
    """A recorded error: its status and its body."""
    recorded = _fixture(name)
    return httpx.Response(recorded["status"], json=recorded["body"])


@respx.mock
async def test_a_collection_lists_its_counties_by_the_id_to_descend_with(monkeypatch, anon_config):
    """The ``sd_`` ids are local to one response; the waypoint id is in ``about``.

    Earlier releases returned ``sd_3`` as each child's id, which no route
    takes, and listed the collection's own two entries as children of it.
    """
    _anon(monkeypatch, anon_config)
    respx.get(f"{B}/records/collections/{TENNESSEE}/waypoints").mock(
        return_value=httpx.Response(200, json=_fixture("collection-1909088.json"))
    )
    out = await call_tool("browse_waypoints", collection_id=TENNESSEE)
    assert out["title"] == "Tennessee, Probate Court Books, 1795-1927"
    assert out["path"] == ["Tennessee, Probate Court Books, 1795-1927"]
    assert out["child_count"] == 4
    assert out["children"][0] == {"waypoint_id": "M6QS-YWP:179637801", "title": "Anderson"}
    assert all(not c["waypoint_id"].startswith("sd_") for c in out["children"])


@respx.mock
async def test_descending_sends_the_collection_the_waypoint_was_listed_under(
    monkeypatch, anon_config
):
    """The reported defect: the waypoint route needs ``cc``, and was sent none.

    Verified live 2026-10-06: without it FamilySearch answers 400 "Required
    request parameter 'cc'", with or without a collection_id passed to the
    tool, which ignored it when descending.
    """
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/waypoints/{GRUNDY}").mock(
        side_effect=lambda r: (
            httpx.Response(200, json=_fixture("county-grundy.json"))
            if r.url.params.get("cc") == TENNESSEE
            else _recorded("no-cc-400.json")
        )
    )
    out = await call_tool("browse_waypoints", waypoint_id=GRUNDY, collection_id=TENNESSEE)
    assert route.calls.last.request.url.params["cc"] == TENNESSEE
    assert out["collection_id"] == TENNESSEE
    assert out["path"] == ["Tennessee, Probate Court Books, 1795-1927", "Grundy"]
    assert out["children"][0] == {"waypoint_id": BONDS, "title": "Bonds, Letters, 1901-1948"}
    assert out["child_total"] == 14
    assert "Authorization" not in route.calls.last.request.headers


async def test_descending_without_the_collection_is_refused_before_asking(monkeypatch, anon_config):
    """FamilySearch's answer would be a 400 naming a parameter the caller never saw."""
    _anon(monkeypatch, anon_config)
    with respx.mock(assert_all_called=False) as mock:
        out = await call_tool("browse_waypoints", waypoint_id=GRUNDY)
    assert out["error"] == "collection_required"
    assert "collection_id" in out["message"]
    assert not mock.calls


@respx.mock
async def test_a_volume_lists_its_images_by_ark_and_position(monkeypatch, anon_config):
    """A volume's id holds a comma, which the general id check refused."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/waypoints/{BONDS}").mock(
        return_value=httpx.Response(200, json=_fixture("volume-first-3-images.json"))
    )
    out = await call_tool("browse_waypoints", waypoint_id=BONDS, collection_id=TENNESSEE)
    assert route.called
    assert out["title"] == "Bonds, Letters, 1901-1948"
    assert out["path"][-2:] == ["Grundy", "Bonds, Letters, 1901-1948"]
    assert out["children"][0] == {"position": 1, "image_ark": "3:1:S7WF-SR8W-59"}
    assert out["child_total"] == 576
    assert out["next_offset"] == 3


@respx.mock
async def test_offset_pages_a_long_volume_and_numbers_from_it(monkeypatch, anon_config):
    """A volume answers at most 1,000 children; a longer one was cut short, silently."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/waypoints/{BONDS}").mock(
        return_value=httpx.Response(200, json=_fixture("volume-last-3-images.json"))
    )
    out = await call_tool(
        "browse_waypoints", waypoint_id=BONDS, collection_id=TENNESSEE, offset=573
    )
    assert route.calls.last.request.url.params["start"] == "573"
    assert [c["position"] for c in out["children"]] == [574, 575, 576]
    assert out["next_offset"] is None


@pytest.mark.parametrize(
    "given",
    [
        f"https://api.familysearch.org/platform/records/waypoints/{GRUNDY}?cc={TENNESSEE}",
        "https://www.familysearch.org/ark:/61903/3:1:S7WF-SR8W-59"
        f"?cc={TENNESSEE}&wc=M6QS-12W%3A179638101",
    ],
)
@respx.mock
async def test_a_url_carrying_the_waypoint_brings_its_collection(monkeypatch, anon_config, given):
    """The ``about`` of a waypoint, or a page address, is enough on its own."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/waypoints/{GRUNDY}").mock(
        return_value=httpx.Response(200, json=_fixture("county-grundy.json"))
    )
    out = await call_tool("browse_waypoints", waypoint_id=given)
    assert route.calls.last.request.url.params["cc"] == TENNESSEE
    assert out["title"] == "Grundy"


async def test_a_url_naming_another_collection_is_refused(monkeypatch, anon_config):
    _anon(monkeypatch, anon_config)
    with respx.mock(assert_all_called=False) as mock:
        out = await call_tool(
            "browse_waypoints",
            waypoint_id=f"https://api.familysearch.org/platform/records/waypoints/{GRUNDY}?cc=1",
            collection_id=TENNESSEE,
        )
    assert out["error"] == "conflicting_collection"
    assert not mock.calls


@respx.mock
async def test_a_collection_with_nothing_to_browse_says_so(monkeypatch, anon_config):
    """Its waypoints are a 404, as an unknown collection's are; its description tells.

    Verified live 2026-10-06 on "Iowa, County Death Records, 1880-1992": no
    waypoints link, and the waypoints route answers 404. Reported as an
    unexplained 404 before.
    """
    _anon(monkeypatch, anon_config)
    respx.get(f"{B}/records/collections/2110820/waypoints").mock(
        return_value=_recorded("iowa-2110820-404.json")
    )
    respx.get(f"{B}/records/collections/2110820").mock(
        return_value=httpx.Response(200, json=_fixture("collection-2110820.json"))
    )
    out = await call_tool("browse_waypoints", collection_id="2110820")
    assert out["error"] == "not_browsable"
    assert "Iowa, County Death Records" in out["message"]
    assert "get_record_image" in out["message"]


def test_the_browsable_collection_does_carry_its_waypoints_link():
    """The distinction the explanation relies on, in the recordings themselves."""
    browsable = _fixture("collection-1909088-descriptor.json")
    not_browsable = _fixture("collection-2110820.json")
    assert "waypoints" in (browsable.get("links") or {})
    assert "waypoints" not in (not_browsable.get("links") or {})


@respx.mock
async def test_an_unknown_collection_is_not_found(monkeypatch, anon_config):
    _anon(monkeypatch, anon_config)
    respx.get(f"{B}/records/collections/99999999/waypoints").mock(
        return_value=_recorded("iowa-2110820-404.json")
    )
    respx.get(f"{B}/records/collections/99999999").mock(return_value=httpx.Response(404))
    out = await call_tool("browse_waypoints", collection_id="99999999")
    assert out == {"error": "not_found", "message": "No collection 99999999."}


@respx.mock
async def test_a_waypoint_under_the_wrong_collection_is_called_out(monkeypatch, anon_config):
    """FamilySearch answers it 200 and empty, or 404; neither may read as an empty volume.

    Both were seen live on 2026-10-06 for the same request.
    """
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/waypoints/{GRUNDY}").mock(
        return_value=httpx.Response(200, json=_fixture("county-under-wrong-collection.json"))
    )
    out = await call_tool("browse_waypoints", waypoint_id=GRUNDY, collection_id="2110820")
    assert out["child_count"] == 0
    assert "wrong collection" in out["message"]
    route.mock(return_value=httpx.Response(404, json={"errors": []}))
    out = await call_tool("browse_waypoints", waypoint_id=GRUNDY, collection_id="2110820")
    assert out["error"] == "not_found"
    assert "collection it was listed under" in out["message"]


@respx.mock
async def test_a_collection_id_in_the_old_sd_c_form_is_understood(monkeypatch, anon_config):
    """search_collections used to hand out ``sd_c_1909088``, which no route takes."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/collections/{TENNESSEE}/waypoints").mock(
        return_value=httpx.Response(200, json=_fixture("collection-1909088.json"))
    )
    await call_tool("browse_waypoints", collection_id=f"sd_c_{TENNESSEE}")
    assert route.called


@respx.mock
async def test_waypoints_need_no_token(monkeypatch, anon_config):
    """Browsing the film structure is open, which is what makes it useful."""
    _anon(monkeypatch, anon_config)
    route = respx.get(f"{B}/records/collections/{TENNESSEE}/waypoints").mock(
        return_value=httpx.Response(200, json=_fixture("collection-1909088.json"))
    )
    await call_tool("browse_waypoints", collection_id=TENNESSEE)
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


@respx.mock
async def test_a_browsable_collection_whose_waypoints_failed_is_not_called_unbrowsable(
    monkeypatch, anon_config
):
    """Only a collection that lists no waypoints is said to have nothing to browse."""
    _anon(monkeypatch, anon_config)
    respx.get(f"{B}/records/collections/{TENNESSEE}/waypoints").mock(
        return_value=_recorded("iowa-2110820-404.json")
    )
    respx.get(f"{B}/records/collections/{TENNESSEE}").mock(
        return_value=httpx.Response(200, json=_fixture("collection-1909088-descriptor.json"))
    )
    out = await call_tool("browse_waypoints", collection_id=TENNESSEE)
    assert out["error"] == "not_found"
    assert "Try again" in out["message"]
