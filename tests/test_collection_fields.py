"""The collection field dictionary, and the numeric record-type filter.

Indexed records label their values with per-collection codes rather than
words. The decoder lives on the collection descriptor, which answers without
a token -- so record output can be made readable with no credentials at all.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient
from familysearch_mcp.shape import collection_field_labels

from .conftest import call_tool

SEARCH = "https://www.familysearch.org/service/search/hr/v2/personas"

COLLECTION_URL = "https://api.familysearch.org/platform/records/collections/1417683"

#: Trimmed from the live response for collection 1417683 on 2026-09-23.
LIVE_COLLECTION = {
    "collections": [{"title": "United States, Census, 1880", "size": 11354879}],
    "recordDescriptors": [
        {
            "fields": [
                {
                    "values": [
                        {
                            "labelId": "PR_NAME",
                            "displaySortKey": "0",
                            "labels": [{"lang": "en", "value": "Name"}],
                        }
                    ]
                },
                {
                    "values": [
                        {
                            "labelId": "EVENT_TYPE",
                            "displaySortKey": "1",
                            "labels": [{"lang": "en", "value": "Event Type"}],
                        }
                    ]
                },
                {
                    "values": [
                        {
                            "labelId": "PR_FTHR_NAME",
                            "displaySortKey": "2",
                            "labels": [{"lang": "en", "value": "Father's Name"}],
                        }
                    ]
                },
            ]
        }
    ],
}


def test_field_codes_are_decoded_to_labels():
    """PR_FTHR_NAME is meaningless to a reader; "Father's Name" is not."""
    fields = collection_field_labels(LIVE_COLLECTION)
    by_code = {f["code"]: f["label"] for f in fields}
    assert by_code["PR_FTHR_NAME"] == "Father's Name"
    assert by_code["PR_NAME"] == "Name"


def test_duplicate_codes_are_reported_once():
    """Descriptors repeat codes across fields; a decoder should not."""
    payload = {
        "recordDescriptors": [
            {
                "fields": [
                    {"values": [{"labelId": "PR_NAME", "labels": [{"value": "Name"}]}]},
                    {"values": [{"labelId": "PR_NAME", "labels": [{"value": "Name"}]}]},
                ]
            }
        ]
    }
    assert len(collection_field_labels(payload)) == 1


def test_a_collection_without_descriptors_is_empty_not_an_error():
    """Not every collection publishes a dictionary."""
    assert collection_field_labels({"collections": [{"title": "X"}]}) == []


def test_a_code_without_a_label_still_appears():
    """An undecoded code is worth reporting; hiding it loses the field."""
    payload = {"recordDescriptors": [{"fields": [{"values": [{"labelId": "MYSTERY"}]}]}]}
    assert collection_field_labels(payload) == [
        {"code": "MYSTERY", "label": None, "sort_key": None}
    ]


@respx.mock
async def test_collection_fields_need_no_token(monkeypatch, anon_config):
    """The decoder is reachable by an install that has no credentials.

    Verified live on 2026-09-23: this route answers without an Authorization
    header. It is what makes record output readable with no setup.
    """
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    route = respx.get(COLLECTION_URL).mock(return_value=httpx.Response(200, json=LIVE_COLLECTION))
    out = await call_tool("get_collection_fields", collection_id="1417683")
    assert out["field_count"] == 3
    assert out["record_count"] == 11354879
    assert "Authorization" not in route.calls.last.request.headers


# --------------------------------------------------------------------------- #
# f.recordType maps a name to a verified integer
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "code"),
    [("census", "3"), ("birth", "0"), ("probate", "6"), ("other", "7")],
)
@respx.mock
async def test_a_record_type_name_is_sent_as_its_code(monkeypatch, auth_config, name, code):
    """f.recordType takes an integer; a name is rejected with HTTP 400.

    Every code was verified live on 2026-09-23 by filtering on it and
    reading the collections returned -- census gave residence and public
    records, probate gave Australian wills.
    """
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone", record_type=name)
    assert route.calls.last.request.url.params["f.recordType"] == code


async def test_an_unknown_record_type_is_refused_with_the_valid_set(monkeypatch, auth_config):
    """Refusing locally beats a 400 from the API."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("search_records", surname="Pettibone", record_type="baptism")
    assert out["error"] == "unknown_record_type"
    assert "census" in out["message"]


@respx.mock
async def test_the_record_type_facet_is_always_requested(monkeypatch, auth_config):
    """The facet shows which kinds of record a search actually reached.

    On the old endpoint it reported every hit under one code, because that
    index held only immigration records. It now spreads across all eight.
    """
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    route = respx.get(SEARCH).mock(return_value=httpx.Response(200, json={}))
    await call_tool("search_records", surname="Pettibone")
    assert route.calls.last.request.url.params["c.recordType"] == "on"
