"""get_catalog_entry: a FamilySearch Catalog entry and its films.

Replayed from ``tests/fixtures/catalog/``, recorded live on 2026-10-06 from
catalog 3154151 by ``tests/record_catalog_fixture.py``: the entry cut to its
first 40 films, every person's name in their descriptions replaced with an
invented one, and the storage host's answers for one film the recording
account may view and one it may not.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import BROWSER_UA, CATALOG_URL, DAS_HOST, FamilySearchClient
from familysearch_mcp.config import Config
from familysearch_mcp.shape import description_matches, pad_dgs
from tests.record_catalog_fixture import Scrubber

from .conftest import call_tool

FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
ENTRY = json.loads((FIXTURES / "3154151.json").read_text(encoding="utf-8"))
GROUPS = json.loads((FIXTURES / "3154151-image-groups.json").read_text(encoding="utf-8"))
ENTRY_URL = f"{CATALOG_URL}/3154151"

#: The recorded film the account could view, with its 26 images, and the one
#: it could not.
VIEWABLE = "106063174"
RESTRICTED = "106063176"


def _group(request: httpx.Request) -> httpx.Response:
    """The storage host: the recorded answer, or ten viewable images."""
    dgs = request.url.path.rsplit("dgs:", 1)[1]
    if dgs in GROUPS:
        return httpx.Response(GROUPS[dgs]["status"], json=GROUPS[dgs]["body"])
    return httpx.Response(200, json={"name": dgs, "childCount": 10})


@pytest.fixture
def authenticated(monkeypatch):
    config = Config(access_token="test-token", environment="production", timeout=5.0)
    monkeypatch.setattr(server.state, "config", config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(config))
    return config


@pytest.fixture
def catalog(authenticated):
    """The catalog service answering the recorded entry, and the storage host."""
    with respx.mock(assert_all_called=False) as mock:
        mock.entry = mock.get(ENTRY_URL).mock(return_value=httpx.Response(200, json=ENTRY))
        mock.groups = mock.get(url__startswith=f"{DAS_HOST}/dgs:").mock(side_effect=_group)
        yield mock


def _by_dgs(out: dict) -> dict:
    return {item["dgs"]: item for item in out["items"]}


async def test_it_asks_the_websites_catalog_service_the_way_record_search_does(catalog):
    """The token, and a browser User-Agent: without one the service says 403."""
    await call_tool("get_catalog_entry", catalog_id="3154151")
    request = catalog.entry.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["User-Agent"] == BROWSER_UA
    assert request.headers["Accept"] == "application/json"


async def test_the_entry_is_described(catalog):
    out = await call_tool("get_catalog_entry", catalog_id="3154151")
    assert out["title"] == "Nebraska, Furnas County, probate records, 1806-1952"
    assert out["url"] == "https://www.familysearch.org/search/catalog/3154151"
    assert out["format"] == "Manuscript on Digital Images"
    assert out["authors"] == [
        {"name": "Nebraska Probate Court (Furnas County)", "role": "Main Author"},
        {"name": "Nebraska. County Court (Furnas County)", "role": "Repository"},
    ]
    assert out["places"] == ["United States, Nebraska, Furnas"]
    assert out["languages"] == ["English"]
    assert out["online"] is True
    assert out["items_total"] == 40


async def test_notes_come_back_as_plain_text(catalog):
    """The preliminary-description warning arrives wrapped in a red font tag."""
    out = await call_tool("get_catalog_entry", catalog_id="3154151")
    assert out["notes"][1] == (
        "This is a preliminary description provided to allow immediate online "
        "access. Images have not been reviewed."
    )
    assert not any("<" in note for note in out["notes"])


async def test_each_item_says_how_many_images_it_holds_and_whether_it_can_be_viewed(catalog):
    out = await call_tool("get_catalog_entry", catalog_id="3154151", count=50)
    items = _by_dgs(out)
    assert out["returned"] == 40
    assert items[VIEWABLE]["image_count"] == 26
    assert items[VIEWABLE]["viewable"] is True
    assert items[RESTRICTED]["viewable"] is False
    assert items[RESTRICTED]["access"] == "restricted for this account"
    assert "image_count" not in items[RESTRICTED]
    assert items[RESTRICTED]["catalog_rights"] == "NO_ACC"
    assert items[VIEWABLE]["description"] == (
        "Probate Records, Box 179 #541 - Pettibone A. Thackeray, 1806-1906"
    )


async def test_every_result_carries_the_cautions(catalog):
    """Holdings are not the record; access varies; a DGS is not a film."""
    out = await call_tool("get_catalog_entry", catalog_id="3154151", contains="no such words")
    assert out["items"] == []
    assert out["cautions"] == server.CATALOG_CAUTIONS
    joined = " ".join(out["cautions"])
    assert "not the record" in joined
    assert "never digitised" in joined
    assert "not the microfilm number" in joined


async def test_contains_keeps_items_holding_every_word(catalog):
    out = await call_tool(
        "get_catalog_entry", catalog_id="3154151", contains="box 238 guardianship", count=50
    )
    assert out["items_matched"] == 2
    for item in out["items"]:
        assert "Box 238" in item["description"]
        assert "Guardianship" in item["description"]


async def test_a_number_matches_only_whole(catalog):
    """Case 64 is not case 642: a session asking for one must not get the other."""
    none = await call_tool("get_catalog_entry", catalog_id="3154151", contains="#64")
    assert none["items_matched"] == 0
    one = await call_tool("get_catalog_entry", catalog_id="3154151", contains="642")
    assert [i["dgs"] for i in one["items"]] == [RESTRICTED]


async def test_a_number_inside_a_span_matches(catalog):
    """A file dated 1806-1906 covers 1850, though "1850" appears nowhere in it."""
    out = await call_tool("get_catalog_entry", catalog_id="3154151", contains="1850", count=50)
    assert out["items_matched"] == 6
    assert all(re.search(r"18\d\d-19\d\d", i["description"]) for i in out["items"])
    later = await call_tool("get_catalog_entry", catalog_id="3154151", contains="1990")
    assert {i["dgs"] for i in later["items"]} == {"106063025", "106184935"}


@pytest.mark.parametrize(
    "description, words, expected",
    [
        ("Probate Records, Box 12 #250 - X, 1885", ["#250", "1885"], True),
        ("Probate Records, Box 12 #2500 - X, 1885", ["#250"], False),
        ("Probate Records, Box 12 #150-300 - X, 1885", ["250"], True),
        ("Probate Records, Box 12 #150-#300 - X, 1885", ["#250"], True),
        ("Probate Records, Box 12, 1880-1890", ["1885", "box"], True),
        ("Probate Records, Box 12, 1880-1890", ["1891"], False),
        ("Wills, v. A-C", ["v."], True),
        ("anything", [], True),
    ],
)
def test_description_matching(description, words, expected):
    assert description_matches(description, words) is expected


async def test_items_page_and_only_the_page_costs_requests(catalog):
    first = await call_tool("get_catalog_entry", catalog_id="3154151", count=5)
    assert first["returned"] == 5
    assert first["next_offset"] == 5
    assert catalog.groups.call_count == 5
    last = await call_tool("get_catalog_entry", catalog_id="3154151", count=10, offset=35)
    assert last["returned"] == 5
    assert last["next_offset"] is None
    assert [i["dgs"] for i in last["items"]] == [
        pad_dgs(n["digital_film_no"]) for n in ENTRY["source"]["film_note"][35:]
    ]


async def test_count_is_held_to_fifty(catalog):
    out = await call_tool("get_catalog_entry", catalog_id="3154151", count=500)
    assert out["returned"] == 40
    capped = copy.deepcopy(ENTRY)
    capped["source"]["film_note"] *= 2
    catalog.entry.mock(return_value=httpx.Response(200, json=capped))
    server.state.client._catalog.clear()
    out = await call_tool("get_catalog_entry", catalog_id="3154151", count=500)
    assert out["returned"] == 50


async def test_an_entry_is_read_once_while_it_is_narrowed(catalog):
    """A 3,000-film entry weighs most of a megabyte; narrowing it asks again and again."""
    await call_tool("get_catalog_entry", catalog_id="3154151", contains="1880")
    await call_tool("get_catalog_entry", catalog_id="3154151", contains="guardianship")
    assert catalog.entry.call_count == 1


async def test_a_dgs_keeps_nine_digits_and_a_microfilm_keeps_its_own_number(catalog):
    """The storage host answers dgs:007529219 and not dgs:7529219."""
    entry = copy.deepcopy(ENTRY)
    entry["source"]["film_note"] = [
        {
            "digital_film_no": "7529219",
            "filmno": "476631",
            "items": "Item 4",
            "item_image_start_no": "212",
            "digital_film_rights": "",
            "location": "FamilySearch Library",
            "text": "Also on microfilm.",
        }
    ]
    catalog.entry.mock(return_value=httpx.Response(200, json=entry))
    out = await call_tool("get_catalog_entry", catalog_id="3154151")
    assert out["items"] == [
        {
            "dgs": "007529219",
            "description": "Also on microfilm.",
            "film": "476631",
            "item_on_film": "Item 4",
            "first_image": 212,
            "image_count": 10,
            "viewable": True,
            "access": "viewable",
        }
    ]
    assert catalog.groups.calls.last.request.url.path.endswith("/dgs:007529219")


async def test_a_film_never_digitised_says_so_and_where_it_is(catalog):
    entry = copy.deepcopy(ENTRY)
    entry["source"]["film_note"] = [
        {
            "digital_film_no": "",
            "filmno": "1166067",
            "location": "Granite Mountain Record Vault",
            "text": "Tables de baptêmes, mariages, sépultures 1583-1792",
        }
    ]
    catalog.entry.mock(return_value=httpx.Response(200, json=entry))
    out = await call_tool("get_catalog_entry", catalog_id="3154151")
    (item,) = out["items"]
    assert item["dgs"] is None
    assert item["film"] == "1166067"
    assert item["viewable"] is False
    assert item["access"] == "not digitised"
    assert item["location"] == "Granite Mountain Record Vault"
    assert not catalog.groups.called


async def test_a_storage_host_failure_leaves_viewable_unknown(catalog):
    """The entry still comes back; only the one film's access is in doubt."""
    catalog.groups.mock(return_value=httpx.Response(500, text="gateway"))
    out = await call_tool("get_catalog_entry", catalog_id="3154151", count=1)
    (item,) = out["items"]
    assert item["viewable"] is None
    assert item["access"] == "unknown (HTTP 500)"


async def test_an_unknown_entry_is_not_found(catalog):
    """The service answers an unknown id with 404 and no body."""
    catalog.get(f"{CATALOG_URL}/99999999").mock(return_value=httpx.Response(404))
    out = await call_tool("get_catalog_entry", catalog_id="99999999")
    assert out["error"] == "not_found"


async def test_a_catalog_id_that_is_not_a_number_is_refused_locally(catalog):
    out = await call_tool("get_catalog_entry", catalog_id="search/catalog/3154151")
    assert out["error"] == "invalid_id"
    assert "catalog_id" in out["message"]
    assert not catalog.entry.called


def test_the_recorder_replaces_names_and_keeps_what_is_filtered_on():
    """Box, case number and years survive; the people do not, and stay consistent."""
    scrub = Scrubber()
    first = scrub.description("Probate Records, Box 12 #250 - John Q. Public, 1885-1890")
    second = scrub.description("Probate Records, Box 13 - John Public - Guardianship, 1891")
    assert first.startswith("Probate Records, Box 12 #250 - ")
    assert first.endswith(", 1885-1890")
    assert "John" not in first and "Public" not in first and "Q." not in first
    assert second.startswith("Probate Records, Box 13 - ")
    assert second.endswith(" - Guardianship, 1891")
    assert first.split(" - ")[1].split(",")[0].split()[0] == second.split(" - ")[1].split()[0]
