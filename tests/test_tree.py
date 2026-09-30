"""Tree tools: what they return, and the warning they are obliged to carry.

The shared tree is the part of FamilySearch most likely to be believed and
least likely to be right. These tests pin both halves: that the tools read it
correctly, and that they never present it as settled.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient

from .conftest import call_tool

HOST = "https://api.familysearch.org"
PID = "K2ZP-VY1"


@pytest.fixture
def authenticated(monkeypatch, auth_config):
    """A server carrying a token, since none of these answer without one."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    return auth_config


@respx.mock
async def test_relatives_are_grouped_by_how_they_relate(authenticated, families_document):
    """A flat list of relationships is not an answer; the grouping is."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/families").mock(
        return_value=httpx.Response(200, json=families_document)
    )
    out = await call_tool("get_person_relatives", person_id=PID)
    assert [p["name"] for p in out["parents"]] == ["Amos Pettibone", "Abigail Thackeray"]
    assert [p["name"] for p in out["spouses"]] == ["Mary Chesebrough"]
    assert "Ezra Pettibone Jr" in [p["name"] for p in out["children"]]
    assert [p["name"] for p in out["siblings"]] == ["Lydia Pettibone"]


@respx.mock
async def test_the_subject_is_never_listed_as_their_own_sibling(authenticated, families_document):
    """Sharing parents with yourself is the obvious bug in that computation."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/families").mock(
        return_value=httpx.Response(200, json=families_document)
    )
    out = await call_tool("get_person_relatives", person_id=PID)
    assert PID not in [p["id"] for p in out["siblings"]]


@respx.mock
async def test_a_living_child_comes_back_marked_restricted_not_blank(
    authenticated, families_document
):
    """A redacted child must read as withheld, not as a gap in the family."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/families").mock(
        return_value=httpx.Response(200, json=families_document)
    )
    out = await call_tool("get_person_relatives", person_id=PID)
    living = next(p for p in out["children"] if p["id"] == "L4RT-9QP")
    assert living["restricted"] is True


@respx.mock
async def test_relatives_of_a_person_with_no_family_is_not_an_error(authenticated):
    """A 204 means no families recorded, which is an answer, not a failure."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/families").mock(return_value=httpx.Response(204))
    out = await call_tool("get_person_relatives", person_id=PID)
    assert out["error"] == "not_found"


@respx.mock
async def test_ancestry_keeps_the_ahnentafel_position(authenticated, ancestry_document):
    """Without the number, a pedigree is an unordered list of strangers."""
    respx.get(f"{HOST}/platform/tree/ancestry").mock(
        return_value=httpx.Response(200, json=ancestry_document)
    )
    out = await call_tool("get_ancestry", person_id=PID, generations=3)
    assert [p["position"] for p in out["ancestors"]] == ["1", "2", "3"]
    assert out["ancestors"][0]["lifespan"] == "1751-1826"


@respx.mock
async def test_ancestry_asks_for_the_generations_requested(authenticated, ancestry_document):
    """The parameter has to reach the query or the default silently wins."""
    route = respx.get(f"{HOST}/platform/tree/ancestry").mock(
        return_value=httpx.Response(200, json=ancestry_document)
    )
    await call_tool("get_ancestry", person_id=PID, generations=6)
    params = route.calls.last.request.url.params
    assert params["person"] == PID
    assert params["generations"] == "6"


@respx.mock
async def test_ancestry_generations_are_clamped_to_what_the_api_allows(
    authenticated, ancestry_document
):
    """FamilySearch caps ancestry at 8; asking for 30 should not 400."""
    route = respx.get(f"{HOST}/platform/tree/ancestry").mock(
        return_value=httpx.Response(200, json=ancestry_document)
    )
    out = await call_tool("get_ancestry", person_id=PID, generations=30)
    assert route.calls.last.request.url.params["generations"] == "8"
    assert out["generations"] == 8


@respx.mock
async def test_descendancy_generations_are_clamped_more_tightly(authenticated, ancestry_document):
    """A descendancy fans out, so FamilySearch caps it at 4, not 8."""
    route = respx.get(f"{HOST}/platform/tree/descendancy").mock(
        return_value=httpx.Response(200, json=ancestry_document)
    )
    await call_tool("get_descendancy", person_id=PID, generations=8)
    assert route.calls.last.request.url.params["generations"] == "4"


@respx.mock
async def test_person_sources_say_what_each_source_supports(authenticated, person_sources_document):
    """'Has sources' and 'this fact has a source' are different claims."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/sources").mock(
        return_value=httpx.Response(200, json=person_sources_document)
    )
    out = await call_tool("get_person_sources", person_id=PID)
    first = next(s for s in out["sources"] if s["id"] == "SD-1")
    assert sorted(first["supports"]) == ["Birth", "Name"]
    assert next(s for s in out["sources"] if s["id"] == "SD-2")["supports"] == []


@respx.mock
async def test_person_sources_carry_the_ark_that_leads_out_of_the_tree(
    authenticated, person_sources_document
):
    """The ark is the whole value of this tool: it points at a record."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/sources").mock(
        return_value=httpx.Response(200, json=person_sources_document)
    )
    out = await call_tool("get_person_sources", person_id=PID)
    assert out["sources"][0]["about"].endswith("1:1:XXXX")
    assert out["sources"][0]["citation"].startswith("Kaskaskia")


@respx.mock
async def test_a_person_with_no_sources_says_what_that_means(authenticated):
    """An empty list could be read as 'nothing exists'. It means nothing was attached."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/sources").mock(
        return_value=httpx.Response(200, json={"sourceDescriptions": []})
    )
    out = await call_tool("get_person_sources", person_id=PID)
    assert out["returned"] == 0
    assert "nobody attached any" in out["note"]


@respx.mock
async def test_change_history_names_the_contributor_and_the_reason(
    authenticated, change_history_feed
):
    """Judging a conflation means knowing who changed what, and when."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/changes").mock(
        return_value=httpx.Response(200, json=change_history_feed)
    )
    out = await call_tool("get_person_changes", person_id=PID)
    first = out["changes"][0]
    assert first["title"] == "Birth Added"
    assert first["contributors"] == ["Mr. Contributor"]
    assert first["operation"] == "Create"
    assert first["changed"] == "Birth"
    assert first["reason"] == "found in the town records"


@respx.mock
async def test_change_history_negotiates_the_atom_representation(
    authenticated, change_history_feed
):
    """The change resource serves Atom only; the plain GEDCOM X type 406s."""
    route = respx.get(f"{HOST}/platform/tree/persons/{PID}/changes").mock(
        return_value=httpx.Response(200, json=change_history_feed)
    )
    await call_tool("get_person_changes", person_id=PID)
    assert route.calls.last.request.headers["Accept"] == "application/x-gedcomx-atom+json"


@respx.mock
async def test_memories_come_back_as_described_artifacts(authenticated):
    """A memory is an upload; what it is worth depends on what it is."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/memories").mock(
        return_value=httpx.Response(
            200,
            json={
                "sourceDescriptions": [
                    {
                        "id": "M-1",
                        "mediaType": "image/jpeg",
                        "titles": [{"value": "Headstone, Kaskaskia"}],
                        "about": "https://familysearch.org/ark:/61903/3:1:MMMM",
                    }
                ]
            },
        )
    )
    out = await call_tool("get_person_memories", person_id=PID)
    assert out["memories"][0]["media_type"] == "image/jpeg"
    assert out["memories"][0]["title"] == "Headstone, Kaskaskia"


@respx.mock
async def test_matches_carry_the_score_that_makes_them_judgeable(authenticated, matches_feed):
    """An unscored candidate list cannot be triaged."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/matches").mock(
        return_value=httpx.Response(200, json=matches_feed)
    )
    out = await call_tool("get_matches", person_id=PID)
    assert out["candidates"][0]["score"] == 4.5
    assert out["candidates"][0]["confidence"] == 4
    assert out["candidates"][0]["name"] == "Ezra Pettibone"


@respx.mock
async def test_matches_can_be_asked_for_records_rather_than_tree_profiles(
    authenticated, matches_feed
):
    """Record matches lead out of the tree; tree matches stay inside it."""
    route = respx.get(f"{HOST}/platform/tree/persons/{PID}/matches").mock(
        return_value=httpx.Response(200, json=matches_feed)
    )
    out = await call_tool("get_matches", person_id=PID, collection="records")
    assert route.calls.last.request.url.params["collection"] == "records"
    assert out["collection"] == "records"


@respx.mock
async def test_no_matches_is_an_empty_list_not_an_error(authenticated):
    """FamilySearch answers 204 when it has no candidates."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/matches").mock(return_value=httpx.Response(204))
    out = await call_tool("get_matches", person_id=PID)
    assert out["returned"] == 0 and out["candidates"] == []


@respx.mock
async def test_a_merged_person_surfaces_its_status(authenticated):
    """FamilySearch answers 301 for a person merged away; that is worth saying."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/sources").mock(
        return_value=httpx.Response(301, json={"error": "merged"})
    )
    out = await call_tool("get_person_sources", person_id=PID)
    assert out.get("returned") == 0 or out.get("error")


@respx.mock
async def test_a_record_match_is_kept_even_with_no_person_embedded(authenticated):
    """Record matches carry an ark and a collection, not a person.

    Dropping an entry that has no embedded person would silently discard
    exactly the matches that lead out of the tree towards a document.
    """
    respx.get(f"{HOST}/platform/tree/persons/{PID}/matches").mock(
        return_value=httpx.Response(
            200,
            json={
                "entries": [
                    {
                        "id": "https://familysearch.org/ark:/61903/1:1:MMMM-7P1",
                        "score": 0.9824,
                        "confidence": 4,
                        "title": "FamilySearch Historical Collection 173",
                        "matchInfo": [{"status": "http://familysearch.org/v1/Pending"}],
                        "content": {
                            "gedcomx": {
                                "sourceDescriptions": [
                                    {"resourceType": "http://gedcomx.org/Collection"}
                                ]
                            }
                        },
                    }
                ]
            },
        )
    )
    out = await call_tool("get_matches", person_id=PID, collection="records")
    assert out["returned"] == 1
    candidate = out["candidates"][0]
    assert candidate["match_id"].endswith("1:1:MMMM-7P1")
    assert candidate["status"] == "Pending"
    assert candidate["score"] == 0.9824


@respx.mock
async def test_a_memory_reports_what_kind_of_thing_it_is(authenticated):
    """A headstone photograph and a cousin's typed story are not the same claim."""
    respx.get(f"{HOST}/platform/tree/persons/{PID}/memories").mock(
        return_value=httpx.Response(
            200,
            json={
                "sourceDescriptions": [
                    {
                        "id": "904106",
                        "about": "https://familysearch.org/photos/images/904106",
                        "titles": [{"value": "Missionary Portrait"}],
                        "descriptions": [{"value": "Alma Heaton on a mission."}],
                        "artifactMetadata": [
                            {
                                "filename": "alma-mission.jpg",
                                "qualifiers": [{"name": "http://familysearch.org/v1/Photo"}],
                            }
                        ],
                    }
                ]
            },
        )
    )
    out = await call_tool("get_person_memories", person_id=PID)
    assert out["memories"][0]["kind"] == "Photo"
    assert out["memories"][0]["filename"] == "alma-mission.jpg"
    assert out["memories"][0]["description"] == "Alma Heaton on a mission."


async def test_every_tree_tool_is_registered_as_one():
    """A tree tool left off the register would ship without the warning."""
    assert server.TREE_TOOLS == {
        "get_person",
        "get_person_relatives",
        "get_ancestry",
        "get_descendancy",
        "get_person_sources",
        "get_person_memories",
        "get_person_changes",
        "get_matches",
    }


async def test_no_tree_tool_answers_without_a_token():
    """Nothing in the tree is anonymous, whatever the places tools manage."""
    assert not (server.TREE_TOOLS & server.ANONYMOUS_TOOLS)
