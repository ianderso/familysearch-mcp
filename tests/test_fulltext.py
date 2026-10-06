"""fulltext_search: the handwriting-recognised text of page images.

The response here is invented, in the shape the live service returned on
2026-10-05: one entry per page image, the whole page's text, the matched
terms bare, and no relevance score.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import BROWSER_UA, FULLTEXT_URL, FULLTEXT_URLS, FamilySearchClient
from familysearch_mcp.config import Config
from familysearch_mcp.shape import NAMES_PER_HIT, SNIPPET_LIMIT, fulltext_hits, snippets

from .conftest import call_tool

PAGE = (
    "Deed Book 7 . This Indenture made the 4th day of March 1819 between Ezra "
    "Pettibone of the County of Randolph of the one part and Amos Thackeray of the "
    "other part . Witness Lydia Pettibone , Mary Chesebrough . " + "Recorded . " * 400
)


def _entry(ark: str = "3:1:TEST-PAGE-1", text: str = PAGE) -> dict:
    return {
        "id": ark,
        "sourceUrl": f"https://www.familysearch.org/ark:/61903/{ark}",
        "collectionId": "9999999",
        "collectionTitle": "Illinois, Wills and Deeds, ca. 1700s-2017",
        "content": {
            "recordDate": "1819",
            "recordType": "Deed Book",
            "recordPlace": "Randolph, Illinois, United States",
            "title": "Randolph, Illinois, United States Deed Book 1819",
            "textDocument": text,
            "entities": [
                {"type": "NAME", "value": "Ezra Pettibone"},
                {"type": "NAME", "value": "Amos Thackeray"},
                {"type": "NAME", "value": "Ezra Pettibone"},
                {"type": "PLACE", "value": "Randolph"},
                {"type": "DATE", "value": "4th day of March 1819"},
            ],
            "highlightTexts": ["Ezra Pettibone", "Pettibone"],
        },
    }


RESPONSE = {
    "results": 120,
    "index": 0,
    "links": {"next": {"href": f"{FULLTEXT_URL}?offset=1&count=1"}},
    "entries": [_entry()],
    "facets": [
        {
            "displayName": "Place",
            "params": "c.recordPlace0=on",
            "count": 120,
            "facets": [
                {
                    "displayName": "United States of America",
                    "count": 110,
                    "params": "c.recordPlace1=on&f.recordPlace0=10",
                }
            ],
        }
    ],
}


@pytest.fixture
def authenticated(monkeypatch, auth_config):
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    return auth_config


def _params(route) -> dict:
    return dict(route.calls.last.request.url.params)


@respx.mock
async def test_it_asks_the_websites_service_the_way_record_search_does(authenticated):
    """The token, and a browser User-Agent: without one the service says 403."""
    route = respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    await call_tool("fulltext_search", text="Pettibone")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["User-Agent"] == BROWSER_UA
    assert request.headers["Accept"] == "application/json"
    assert _params(route)["m.queryRequireDefault"] == "on"


@pytest.mark.parametrize(
    "given, sent",
    [
        ("Ezra Pettibone", "+Ezra +Pettibone"),
        ('"Ezra Pettibone" Randolph', '+"Ezra Pettibone" +Randolph'),
        ("+Ezra -Amos Pettib*", "+Ezra -Amos +Pettib*"),
        ("Pettibone OR Pettibon", "Pettibone OR Pettibon"),
    ],
)
@respx.mock
async def test_every_word_must_match_unless_the_query_says_otherwise(authenticated, given, sent):
    """The service ORs bare words: 'Hannah Ball' matched 19.7 million pages live."""
    route = respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    out = await call_tool("fulltext_search", text=given)
    assert _params(route)["q.text"] == sent
    assert out["query_sent"]["q.text"] == sent


@respx.mock
async def test_a_plain_name_is_searched_as_a_phrase(authenticated):
    """Its words belong together; two names on one page are not a match."""
    route = respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    await call_tool("fulltext_search", name="Ezra Pettibone")
    assert _params(route)["q.fullName"] == '"Ezra Pettibone"'
    await call_tool("fulltext_search", name="Mary-Ann O'Brien")
    assert _params(route)["q.fullName"] == '"Mary-Ann O\'Brien"'
    await call_tool("fulltext_search", name='"Ezra Pettibone" OR "E. Pettibone"')
    assert _params(route)["q.fullName"] == '"Ezra Pettibone" OR "E. Pettibone"'


@respx.mock
async def test_one_volume_can_be_searched_by_its_image_group(authenticated):
    """A hit's film number turns into a search of the whole volume."""
    route = respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    await call_tool("fulltext_search", text="Pettibone", image_group="008190429")
    assert _params(route)["q.groupName"] == "008190429"


@respx.mock
async def test_an_image_group_that_is_not_a_number_is_refused_locally(authenticated):
    out = await call_tool("fulltext_search", text="Pettibone", image_group="vol 7")
    assert out["error"] == "invalid_image_group"
    assert not respx.calls


@respx.mock
async def test_a_hit_is_a_page_with_the_passages_that_matched(authenticated):
    """The page text runs to tens of thousands of characters; the passages do not."""
    respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    out = await call_tool("fulltext_search", text="Pettibone")
    hit = out["results"][0]
    assert hit["image_ark"] == "3:1:TEST-PAGE-1"
    assert hit["url"].endswith("/ark:/61903/3:1:TEST-PAGE-1")
    assert hit["collection"].startswith("Illinois")
    assert hit["title"] == "Randolph, Illinois, United States Deed Book 1819"
    assert hit["matched"] == ["Ezra Pettibone", "Pettibone"]
    assert any("Ezra Pettibone of the County of Randolph" in s for s in hit["snippets"])
    assert hit["names_on_page"] == ["Ezra Pettibone", "Amos Thackeray"]
    assert "textDocument" not in hit
    assert sum(len(s) for s in hit["snippets"]) < len(PAGE) / 5


@respx.mock
async def test_paging_is_reported(authenticated):
    respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    out = await call_tool("fulltext_search", text="Pettibone", count=1)
    assert (out["total"], out["returned"], out["has_more"]) == (120, 1, True)


@respx.mock
async def test_facets_carry_the_filter_that_selects_them(authenticated):
    """Places and record types are service ids; the facet is how to learn them."""
    route = respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    out = await call_tool("fulltext_search", text="Pettibone", facets=True)
    assert _params(route)["m.defaultFacets"] == "on"
    bucket = out["facets"][0]["buckets"][0]
    assert bucket == {
        "name": "United States of America",
        "count": 110,
        "filter": "c.recordPlace1=on&f.recordPlace0=10",
    }
    await call_tool("fulltext_search", text="Pettibone", filters=[bucket["filter"]])
    params = _params(route)
    assert params["f.recordPlace0"] == "10"
    assert params["c.recordPlace1"] == "on"


@pytest.mark.parametrize(
    "bad",
    [
        "q.text=anything",
        "f.collectionId=1&access_token=x",
        "f.recordPlace0=10;drop",
        "m.queryRequireDefault=off",
        "f.recordYear1=1820",
    ],
)
@respx.mock
async def test_a_filter_the_search_does_not_take_is_refused_locally(authenticated, bad):
    """Only facet filters pass, so a filter cannot smuggle in another parameter."""
    out = await call_tool("fulltext_search", text="Pettibone", filters=[bad])
    assert out["error"] == "invalid_filter"
    assert not respx.calls


@respx.mock
async def test_every_result_carries_the_cautions(authenticated):
    """A machine reading, partial coverage, and the path to cite the image."""
    respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(200, json=RESPONSE))
    out = await call_tool("fulltext_search", text="Pettibone")
    text = " ".join(out["cautions"])
    assert "machine's reading" in text and "cite the image" in text
    assert "Coverage is partial" in text and "not that no record exists" in text
    assert "film (image group) and image number" in text


@respx.mock
async def test_no_result_is_still_a_result_with_its_cautions(authenticated):
    respx.get(FULLTEXT_URL).mock(
        return_value=httpx.Response(200, json={"results": 0, "entries": [], "facets": []})
    )
    out = await call_tool("fulltext_search", text="Pettibone")
    assert (out["total"], out["results"], out["has_more"]) == (0, [], False)
    assert out["cautions"]


async def test_a_search_with_nothing_to_find_is_refused():
    assert (await call_tool("fulltext_search"))["error"] == "no_criteria"


@respx.mock
async def test_a_query_the_service_cannot_parse_says_why(authenticated):
    """'Validation failed.' alone does not say what to fix; the errors do."""
    respx.get(FULLTEXT_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "message": "Validation failed.",
                "errors": ["Unable to map supplied value=record_year2 to count term"],
            },
        )
    )
    out = await call_tool("fulltext_search", text="Pettibone")
    assert out["error"] == "api_error"
    assert "record_year2" in out["message"]


@respx.mock
async def test_a_refusal_from_the_service_is_reported_as_forbidden(authenticated):
    respx.get(FULLTEXT_URL).mock(return_value=httpx.Response(403, json={"errorCode": 15}))
    out = await call_tool("fulltext_search", text="Pettibone")
    assert out["error"] == "forbidden"


@respx.mock
async def test_the_sandbox_has_its_own_service(monkeypatch):
    config = Config(access_token="t", environment="integration", timeout=5.0)
    monkeypatch.setattr(server.state, "config", config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(config))
    route = respx.get(FULLTEXT_URLS["integration"]).mock(
        return_value=httpx.Response(200, json=RESPONSE)
    )
    await call_tool("fulltext_search", text="Pettibone")
    assert route.called


# --------------------------------------------------------------------------- #
# Snippets
# --------------------------------------------------------------------------- #
def test_a_snippet_is_cut_around_the_match_with_ellipses():
    text = "x " * 200 + "Ezra Pettibone sold the land" + " y" * 200
    found = snippets(text, ["Ezra Pettibone"])
    assert len(found) == 1
    assert found[0].startswith("...") and found[0].endswith("...")
    assert "Ezra Pettibone sold the land" in found[0]


def test_a_page_that_repeats_a_name_does_not_come_back_whole():
    text = "Pettibone and " * 2000
    found = snippets(text, ["Pettibone"])
    assert 1 <= len(found) <= 3
    assert all(len(s) <= SNIPPET_LIMIT + 6 for s in found)


def test_a_match_the_text_does_not_contain_gives_no_snippet():
    assert snippets("nothing here", ["Pettibone"]) == []
    assert snippets("", ["Pettibone"]) == []


def test_recognised_names_are_kept_distinct_and_few():
    entry = _entry()
    entry["content"]["entities"] = [{"type": "NAME", "value": f"Person {i}"} for i in range(40)]
    assert len(fulltext_hits({"entries": [entry]})[0]["names_on_page"]) == NAMES_PER_HIT


def test_an_entry_without_an_ark_is_skipped():
    assert fulltext_hits({"entries": [{"content": {}}]}) == []


# --------------------------------------------------------------------------- #
# The film and image number a citation needs
# --------------------------------------------------------------------------- #
IMAGE = "3:1:TEST-PAGE-1"
NAME_URL = "https://sg30p0.familysearch.org/service/records/storage/dascloud/das/v2/TH-1/name"


def _image_resource() -> dict:
    return {
        "links": {
            "image-name": {"href": NAME_URL},
            "image-stream-image-dist": {"href": NAME_URL.replace("/name", "/dist.jpg")},
            "image-node": {"href": NAME_URL.replace("/name", "")},
        }
    }


@respx.mock
async def test_image_links_name_the_film_and_image_number(authenticated):
    """The node name is bare text, not JSON: dgs:{film}.{film}_{image}."""
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE}").mock(
        return_value=httpx.Response(200, json=_image_resource())
    )
    name = respx.get(NAME_URL).mock(
        return_value=httpx.Response(
            200,
            text="dgs:008190429.008190429_00580",
            headers={"Content-Type": "application/json"},
        )
    )
    out = await call_tool("get_image_links", image_ark=IMAGE)
    assert (out["film_number"], out["image_number"]) == ("008190429", 580)
    assert name.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
async def test_a_film_lookup_that_fails_leaves_the_rest_of_the_answer(authenticated):
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE}").mock(
        return_value=httpx.Response(200, json=_image_resource())
    )
    respx.get(NAME_URL).mock(return_value=httpx.Response(500))
    out = await call_tool("get_image_links", image_ark=IMAGE)
    assert "film_number" not in out
    assert out["full_image"].endswith("/dist.jpg")


@respx.mock
async def test_the_film_lookup_never_sends_the_token_off_familysearch(authenticated):
    resource = _image_resource()
    resource["links"]["image-name"] = {"href": "https://example.com/name"}
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE}").mock(
        return_value=httpx.Response(200, json=resource)
    )
    elsewhere = respx.get("https://example.com/name")
    out = await call_tool("get_image_links", image_ark=IMAGE)
    assert not elsewhere.called
    assert "film_number" not in out
