"""Tool surface: registration, the auth boundary and error shaping.

Tools are invoked through ``mcp.call_tool`` so declared defaults resolve the
way a real client resolves them.
"""

from __future__ import annotations

import httpx
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient

from .conftest import call_tool


async def test_every_tool_is_registered():
    """Each tool is exposed under its documented name, and none by accident.

    The parameter-level snapshot lives in ``test_tool_contract``; this is
    the names alone, so that adding or losing a tool is a one-line diff.
    """
    names = {t.name for t in await server.mcp.list_tools()}
    assert names == {
        "auth_status",
        "compare_person",
        "get_ancestry",
        "get_collection",
        "get_descendancy",
        "get_matches",
        "get_person",
        "get_person_changes",
        "get_person_memories",
        "get_person_relatives",
        "get_person_sources",
        "get_place",
        "get_place_jurisdictions",
        "get_record",
        "get_record_image",
        "search_collections",
        "search_places",
        "search_places_at_date",
        "search_records",
        "fulltext_search",
        "get_collection_fields",
        "get_image_links",
        "download_image",
        "get_place_children",
        "browse_waypoints",
        "get_records_on_image",
        "get_film_image",
        "get_catalog_entry",
    }


async def test_search_records_without_a_name_is_refused():
    """A search with no name would return the whole index."""
    assert (await call_tool("search_records"))["error"] == "no_criteria"


@respx.mock
async def test_gazetteer_answers_without_credentials(monkeypatch, anon_config):
    """An unconfigured install can still resolve place names."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    respx.get("https://api.familysearch.org/platform/places/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "entries": [
                    {
                        "content": {
                            "gedcomx": {
                                "places": [
                                    {
                                        "id": "442",
                                        "names": [{"value": "Kaskaskia"}],
                                        "latitude": 41.3,
                                        "longitude": -71.9,
                                    }
                                ]
                            }
                        }
                    }
                ]
            },
        )
    )
    out = await call_tool("search_places", name="Kaskaskia")
    assert out["places"][0]["name"] == "Kaskaskia"


async def test_authenticated_tool_without_a_token_reports_auth_required(monkeypatch, anon_config):
    """The caller is told what to set, not handed an opaque failure."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "auth_required"
    assert "FS_ACCESS_TOKEN" in out["message"]


@respx.mock
async def test_get_person_shapes_the_result(monkeypatch, auth_config, gedcomx_person):
    """A tree person comes back flattened."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(200, json={"persons": [gedcomx_person]})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["name"] == "Ezra Pettibone"


@respx.mock
async def test_unknown_person_is_not_found(monkeypatch, auth_config):
    """An empty persons list is a clean not_found."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get("https://api.familysearch.org/platform/tree/persons/NOPE").mock(
        return_value=httpx.Response(200, json={"persons": []})
    )
    assert (await call_tool("get_person", person_id="NOPE"))["error"] == "not_found"


async def test_auth_status_names_what_is_missing(monkeypatch, anon_config):
    """An unconfigured install gets a checklist, not a shrug."""
    monkeypatch.setattr(server.state, "config", anon_config)
    out = await call_tool("auth_status")
    assert out["authenticated"] is False
    assert set(out["missing"]) == {"FS_CLIENT_ID", "FS_ACCESS_TOKEN"}
    assert "search_places" in out["available_without_credentials"]
