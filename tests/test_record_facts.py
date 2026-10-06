"""A record's facts: the value, what the indexer wrote, and an empty fact said plainly.

Reported from real use: a death index gave a marital status, and get_record
returned the fact with a type and nothing else. Nobody could tell whether
the index was empty or the server had dropped the value. It was the server:
a fact's ``value`` was never read.

Replayed from ``tests/fixtures/records/persona-death-index.json``, recorded
live on 2026-10-06 from a 1911 Tennessee death index persona (collection
1681020): every name replaced with an invented one, every id with a
placeholder, and the record's own fields and citations left out.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import FamilySearchClient
from familysearch_mcp.shape import fact, search_hits

from .conftest import call_tool

PERSONA = json.loads(
    (Path(__file__).parent / "fixtures" / "records" / "persona-death-index.json").read_text(
        encoding="utf-8"
    )
)
ARK = "1:1:XXXX-YYY"
RECORD = f"https://api.familysearch.org/platform/records/personas/{ARK}"


@pytest.fixture
def authenticated(monkeypatch, auth_config):
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))


def _facts(out: dict) -> dict:
    return {f["type"]: f for f in out["persons"][0]["facts"]}


@respx.mock
async def test_a_fact_carries_its_value(authenticated):
    """The reported defect: MaritalStatus came back with no value."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=PERSONA))
    facts = _facts(await call_tool("get_record", ark=ARK))
    assert facts["MaritalStatus"]["value"] == "Single"
    assert facts["Ethnicity"]["value"] == "American"


@respx.mock
async def test_a_fact_carries_what_the_indexer_wrote(authenticated):
    """ "S" on the page, "Single" as FamilySearch reads it; both matter to a citation."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=PERSONA))
    facts = _facts(await call_tool("get_record", ark=ARK))
    assert facts["MaritalStatus"]["original"] == {"PR_MARITAL_STATUS_ORIG": "S"}
    death = facts["Death"]
    assert death["place"] == "Paducah, McCracken, Kentucky, United States"
    assert death["original"]["EVENT_PLACE_ORIG"] == "Paducah, Kentucky"


@respx.mock
async def test_a_date_with_no_original_was_supplied_by_familysearch(authenticated):
    """The birth year was worked out from the age: there is a date, and no date written."""
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=PERSONA))
    birth = _facts(await call_tool("get_record", ark=ARK))["Birth"]
    assert birth["date"] == "1910"
    assert not any("DATE" in label or "YEAR" in label for label in birth["original"])


@respx.mock
async def test_a_fact_sent_empty_is_said_to_be_so(authenticated):
    """Not something the recording holds: the marital status emptied, as FamilySearch could."""
    persona = copy.deepcopy(PERSONA)
    for entry in persona["persons"][0]["facts"]:
        if entry["type"].endswith("/MaritalStatus"):
            entry.pop("value")
            entry.pop("fields")
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=persona))
    out = await call_tool("get_record", ark=ARK)
    status = _facts(out)["MaritalStatus"]
    assert status == {
        "type": "MaritalStatus",
        "value": None,
        "date": None,
        "place": None,
        "sent_empty": True,
    }
    assert "MaritalStatus" in out["note"]
    assert "passes on every value" in out["note"]


@respx.mock
async def test_a_record_with_every_fact_filled_has_no_note(authenticated):
    respx.get(RECORD).mock(return_value=httpx.Response(200, json=PERSONA))
    assert "note" not in await call_tool("get_record", ark=ARK)


def test_a_search_hit_carries_fact_values_too():
    """Search hits are shaped by the same code, and lost the same values."""
    principal = copy.deepcopy(PERSONA["persons"][0])
    payload = {"entries": [{"id": "XXXX-YYY", "content": {"gedcomx": {"persons": [principal]}}}]}
    hit = search_hits(payload)[0]
    assert {f["type"]: f["value"] for f in hit["facts"]}["MaritalStatus"] == "Single"


def test_a_tree_fact_has_a_value_and_no_original():
    """A tree conclusion carries no indexed fields; its value still comes through."""
    shaped = fact({"type": "http://gedcomx.org/Occupation", "value": "Cordwainer"})
    assert shaped == {"type": "Occupation", "value": "Cordwainer", "date": None, "place": None}
