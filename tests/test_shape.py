"""GEDCOM X shaping: flatten the nesting, reduce the type URIs."""

from __future__ import annotations

from familysearch_mcp.shape import humanize, person, person_name, search_hits


def test_humanize_reduces_a_type_uri():
    """'http://gedcomx.org/Birth' is read by a human as 'Birth'."""
    assert humanize("http://gedcomx.org/Birth") == "Birth"
    assert humanize(None) is None


def test_person_is_flattened(gedcomx_person):
    """Name, sex and facts come out as plain values."""
    out = person(gedcomx_person)
    assert out["name"] == "Ezra Pettibone"
    assert out["sex"] == "Male"
    assert out["facts"][0] == {
        "type": "Birth",
        "date": "23 April 1751",
        "place": "Kaskaskia, Randolph, Illinois",
    }


def test_unnamed_person_is_not_an_error():
    """Records without a name form still shape cleanly."""
    assert person_name({"id": "X"}) is None
    assert person({"id": "X"})["name"] is None


def test_search_hits_carry_score_and_ark(gedcomx_person):
    """A hit needs its relevance and its ark to be worth following up."""
    payload = {
        "entries": [
            {
                "id": "ark:/61903/1:1:XXXX",
                "score": 9.5,
                "content": {"gedcomx": {"persons": [gedcomx_person]}},
            }
        ]
    }
    hits = search_hits(payload)
    assert hits[0]["score"] == 9.5
    assert hits[0]["ark"] == "ark:/61903/1:1:XXXX"
    assert hits[0]["name"] == "Ezra Pettibone"


def test_search_hits_of_an_empty_response():
    """No entries is an empty list, not an exception."""
    assert search_hits({}) == []
