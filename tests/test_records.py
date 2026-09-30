"""Record tools: the part a token is worth obtaining for.

A persona is a search summary. A record is the index entry behind it. An
image is the document. These tools walk that chain in the right direction,
and the tests pin the steps that are easy to collapse.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient

from .conftest import call_tool

HOST = "https://api.familysearch.org"
ARK = "1:1:XXXX-YYY"
RECORD = f"{HOST}/platform/records/personas/{ARK}"
SEARCH = "https://www.familysearch.org/service/search/hr/v2/personas"


@pytest.fixture
def authenticated(monkeypatch, auth_config):
    """A server carrying a token; none of the record tools answer without one."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    return auth_config


@respx.mock
async def test_a_record_carries_the_indexed_fields_a_summary_drops(authenticated, record_document):
    """The labelled fields are the reason to read the record and not the hit."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=record_document))
    out = await call_tool("get_record", ark=ARK)
    assert out["persons"][0]["fields"] == [{"type": "Age", "label": "PR_AGE", "value": "49"}]
    assert out["record_fields"] == [{"type": "RecordType", "label": "TYPE", "value": "Census"}]


@pytest.mark.parametrize(
    "supplied",
    [
        "1:1:XXXX-YYY",
        "ark:/61903/1:1:XXXX-YYY",
        "https://www.familysearch.org/ark:/61903/1:1:XXXX-YYY",
        "  1:1:XXXX-YYY  ",
    ],
)
@respx.mock
async def test_any_form_of_an_ark_reaches_the_same_record(authenticated, record_document, supplied):
    """A caller may hold the bare id, the ark, or the URL off a search page."""
    route = respx.get(RECORD).mock(return_value=httpx.Response(200, json=record_document))
    out = await call_tool("get_record", ark=supplied)
    assert route.called
    assert out["persons"][0]["name"] == "Ezra Pettibone"


@respx.mock
async def test_a_record_with_no_persons_is_not_found(authenticated):
    """An empty document is nothing found, and must not read as a blank record."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json={"persons": []}))
    assert (await call_tool("get_record", ark=ARK))["error"] == "not_found"


@respx.mock
async def test_the_image_behind_a_record_is_resolved(authenticated, record_document):
    """The persona is somebody's reading; the image is what was written."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=record_document))
    out = await call_tool("get_record_image", ark=ARK)
    assert out["image_available"] is True
    assert out["image_links"]["image"].endswith("3:1:ZZZZ")


@respx.mock
async def test_an_unrelated_link_is_not_offered_as_an_image(authenticated, record_document):
    """Returning the self link as an image would send the caller in a circle."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=record_document))
    out = await call_tool("get_record_image", ark=ARK)
    assert "self" not in out["image_links"]


@respx.mock
async def test_a_record_with_no_image_says_so_and_says_why(authenticated):
    """'No image' is a real answer about unpublished film, not a failure."""
    respx.get(RECORD).mock(
        return_value=httpx.Response(
            200,
            json={
                "persons": [{"id": ARK}],
                "sourceDescriptions": [{"id": "S", "titles": [{"value": "Index"}]}],
            },
        )
    )
    out = await call_tool("get_record_image", ark=ARK)
    assert out["image_available"] is False
    assert "microfilm" in out["message"]


@respx.mock
async def test_search_sends_the_relationship_criteria(authenticated):
    """Searching a man by his wife's name is the point of the whole tool."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool(
        "search_records",
        surname="Pettibone",
        spouse_given="Mary",
        spouse_surname="Chesebrough",
        father_surname="Pettibone",
    )
    params = route.calls.last.request.url.params
    assert params["q.spouseGivenName"] == "Mary"
    assert params["q.spouseSurname"] == "Chesebrough"
    assert params["q.fatherSurname"] == "Pettibone"
    assert out["relationship_criteria_used"] == [
        "father_surname",
        "spouse_given",
        "spouse_surname",
    ]


@respx.mock
async def test_search_can_be_run_on_relatives_names_alone(authenticated):
    """When his own name is misindexed, hers is the only handle you have."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool("search_records", spouse_surname="Chesebrough", birth_year=1751)
    assert "error" not in out
    assert route.calls.last.request.url.params["q.spouseSurname"] == "Chesebrough"


@respx.mock
async def test_a_search_with_nothing_at_all_is_refused(authenticated):
    """An unqualified search would return the whole index."""
    out = await call_tool("search_records")
    assert out["error"] == "no_criteria"


@respx.mock
async def test_exact_matching_is_off_unless_asked_for(authenticated):
    """Indexed spellings vary; exact matching by default would hide the hit."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Chesebrough")
    assert "q.surname.exact" not in route.calls.last.request.url.params


@respx.mock
async def test_exact_matching_is_applied_to_names_when_asked_for(authenticated):
    """A common name needs the noise cut, and that is what the flag is for."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", exact=True)
    assert route.calls.last.request.url.params["q.surname.exact"] == "on"


@respx.mock
async def test_exact_matching_is_not_applied_to_a_date(authenticated):
    """A date is not a spelling; an exact modifier on one is meaningless."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", birth_year=1751, exact=True)
    assert "q.birthLikeDate.exact" not in route.calls.last.request.url.params


@respx.mock
async def test_a_search_can_be_scoped_to_one_collection(authenticated):
    """Scoping turns a fishing expedition into a lookup of one register."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", collection_id="1234", count=5)
    params = route.calls.last.request.url.params
    assert params["f.collectionId"] == "1234"
    assert params["count"] == "5"


@respx.mock
async def test_an_empty_criterion_is_not_sent_as_an_empty_term(authenticated):
    """An empty q. term is not a wildcard; it is a malformed query."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone")
    sent = route.calls.last.request.url.params
    assert "q.givenName" not in sent
    assert "q.spouseSurname" not in sent


@respx.mock
async def test_collections_are_matched_on_their_titles(authenticated):
    """FamilySearch offers no catalogue search, so the tool has to be one."""
    respx.get(f"{HOST}/platform/records/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "sourceDescriptions": [
                    {
                        "id": "2178",
                        "titles": [{"value": "Connecticut Church Records, 1630-1920"}],
                        "resourceType": "http://gedcomx.org/Collection",
                    },
                    {
                        "id": "3001",
                        "titles": [{"value": "New York State Census, 1855"}],
                    },
                ]
            },
        )
    )
    out = await call_tool("search_collections", query="connecticut church")
    assert [c["id"] for c in out["collections"]] == ["2178"]


@respx.mock
async def test_a_collection_listing_reports_what_each_one_covers(authenticated):
    """Coverage is what turns a nil result into evidence of absence."""
    respx.get(f"{HOST}/platform/records/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "sourceDescriptions": [
                    {
                        "id": "2178",
                        "titles": [{"value": "Connecticut Church Records"}],
                        "coverage": [
                            {
                                "recordType": "http://gedcomx.org/Birth",
                                "spatial": {"original": "Connecticut"},
                                "temporal": {"original": "1630-1920"},
                            }
                        ],
                    }
                ]
            },
        )
    )
    out = await call_tool("search_collections")
    assert out["collections"][0]["coverage"] == [
        {
            "record_type": "Birth",
            "place": "Connecticut",
            "period": "1630-1920",
        }
    ]


@respx.mock
async def test_an_empty_collection_query_lists_what_is_there(authenticated):
    """Browsing is the first step when you do not know the collection's name."""
    respx.get(f"{HOST}/platform/records/collections").mock(
        return_value=httpx.Response(
            200,
            json={
                "sourceDescriptions": [
                    {"id": "1", "titles": [{"value": "A"}]},
                    {"id": "2"},
                ]
            },
        )
    )
    out = await call_tool("search_collections")
    assert out["returned"] == 2


@respx.mock
async def test_a_collection_reports_how_much_of_it_there_is(authenticated):
    """Record count against image count says how much was ever filmed."""
    respx.get(f"{HOST}/platform/records/collections/2178").mock(
        return_value=httpx.Response(
            200,
            json={
                "collections": [
                    {
                        "lang": "en",
                        "title": "Connecticut Church Records, 1630-1920",
                        "size": 1200000,
                        "content": [
                            {
                                "resourceType": "http://gedcomx.org/Record",
                                "count": 1200000,
                            },
                            {
                                "resourceType": ("http://gedcomx.org/DigitalArtifact"),
                                "count": 4000,
                            },
                        ],
                    }
                ]
            },
        )
    )
    out = await call_tool("get_collection", collection_id="2178")
    assert out["id"] == "2178"
    assert out["title"].startswith("Connecticut Church")
    assert out["size"] == 1200000
    assert out["content"] == [
        {"type": "Record", "count": 1200000},
        {"type": "DigitalArtifact", "count": 4000},
    ]


@respx.mock
async def test_an_unknown_collection_is_not_found(authenticated):
    """A 200 with no collections is still nothing found."""
    respx.get(f"{HOST}/platform/records/collections/NOPE").mock(
        return_value=httpx.Response(200, json={"collections": []})
    )
    out = await call_tool("get_collection", collection_id="NOPE")
    assert out["error"] == "not_found"


@respx.mock
async def test_a_record_ark_and_a_persona_ark_read_different_routes(authenticated, record_document):
    """'1:1:' names one person's entry; '1:2:' names the whole record.

    They are separate resources on separate routes, and reading one id
    against the other's route is a 404 that looks like a missing record.
    """
    persona = respx.get(f"{HOST}/platform/records/personas/1:1:AAAA").mock(
        return_value=httpx.Response(200, json=record_document)
    )
    record = respx.get(f"{HOST}/platform/records/records/1:2:BBBB").mock(
        return_value=httpx.Response(200, json=record_document)
    )
    await call_tool("get_record", ark="1:1:AAAA")
    await call_tool("get_record", ark="1:2:BBBB")
    assert persona.called and record.called


@respx.mock
async def test_an_ark_url_with_a_collection_parameter_is_still_read(authenticated, record_document):
    """A URL copied off a FamilySearch page carries '?cc=...' on the end."""
    route = respx.get(RECORD).mock(return_value=httpx.Response(200, json=record_document))
    out = await call_tool(
        "get_record",
        ark=f"https://www.familysearch.org/ark:/61903/{ARK}?cc=1307314&wc=MGDH",
    )
    assert route.called and "error" not in out


@respx.mock
async def test_the_film_number_is_reported_when_there_is_no_image_link(authenticated):
    """For unpublished film the DGS number is the only route to the document."""
    respx.get(RECORD).mock(
        return_value=httpx.Response(
            200,
            json={
                "persons": [
                    {
                        "id": ARK,
                        "fields": [
                            {
                                "type": "http://gedcomx.org/Other",
                                "values": [
                                    {
                                        "labelId": "FS_DIGITAL_FILM_NBR",
                                        "text": "004523991",
                                    },
                                    {"labelId": "FS_IMAGE_NBR", "text": "118"},
                                ],
                            }
                        ],
                    }
                ]
            },
        )
    )
    out = await call_tool("get_record_image", ark=ARK)
    assert out["film"] == {
        "FS_DIGITAL_FILM_NBR": "004523991",
        "FS_IMAGE_NBR": "118",
    }
    assert out["image_available"] is False


@respx.mock
async def test_the_record_search_asks_for_json(authenticated):
    """The website search service speaks JSON, not GEDCOM X Atom.

    The platform endpoint this replaced required the atom media type and
    answered 406 without it. This one is a different service with different
    rules, and it needs a browser User-Agent instead.
    """
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone")
    sent = route.calls.last.request.headers
    assert sent["accept"] == "application/json"
    assert "Mozilla" in sent["user-agent"]


@respx.mock
async def test_reading_a_record_negotiates_gedcomx_not_atom(authenticated, record_document):
    """The read is the mirror case: it 406s on the Atom type."""
    route = respx.get(RECORD).mock(return_value=httpx.Response(200, json=record_document))
    await call_tool("get_record", ark=ARK)
    assert route.calls.last.request.headers["Accept"] == "application/x-gedcomx-v1+json"


@respx.mock
async def test_paging_past_the_api_ceiling_is_clamped(authenticated):
    """FamilySearch rejects an offset over 4999; clamping beats a 400."""
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", offset=90000)
    assert route.calls.last.request.url.params["offset"] == "4999"


async def test_no_tool_reading_a_person_answers_without_a_token():
    """The anonymous boundary is data about people, not the records API.

    Verified live on 2026-09-23: the collection catalogue and its field
    dictionary answer with no Authorization header, so scoping a search and
    decoding field codes need no credentials. Reading a record, a persona or
    an image still does, and must keep doing so -- those carry data about
    individuals.
    """
    person_reading_tools = {
        "get_record",
        "get_record_image",
        "search_records",
    }
    assert not (person_reading_tools & server.ANONYMOUS_TOOLS)


async def test_collection_catalogue_tools_are_anonymous():
    """Scoping a search should not require credentials a caller may not have."""
    catalogue_tools = {"get_collection", "search_collections", "get_collection_fields"}
    assert catalogue_tools <= server.ANONYMOUS_TOOLS
