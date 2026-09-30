"""Shaping against GEDCOM X as it actually arrives, not as it is documented.

The tidy fixture in ``test_shape`` proves the happy path. These pin the
awkward shapes: several name forms, facts missing a date or a place, places
with no coordinates, redacted living people, and relationships that name
their people by reference rather than by value.
"""

from __future__ import annotations

from familysearch_mcp.shape import (
    REDACTED_NOTE,
    names,
    person,
    place,
    places,
    relationship,
    source_description,
    temporal,
)


def test_every_name_form_is_kept_not_just_the_first(gedcomx_messy_person):
    """A record may index her under any of them; dropping forms loses the match."""
    forms = names(gedcomx_messy_person)
    assert [f["text"] for f in forms] == [
        "Mary Elizabeth Chesebrough",
        "Mary Elizabeth Pettibone",
        "Polly Pettibone",
    ]
    assert [f["type"] for f in forms] == ["BirthName", "MarriedName", "AlsoKnownAs"]


def test_a_name_with_only_parts_is_assembled(gedcomx_messy_person):
    """Some name forms carry parts and no fullText; those must still read."""
    form = {"parts": [{"value": "Ezra"}, {"value": "Pettibone"}]}
    assert names({"names": [{"nameForms": [form]}]})[0]["text"] == "Ezra Pettibone"


def test_a_fact_with_no_date_still_shapes(gedcomx_messy_person):
    """'Born at Kaskaskia, date unknown' is a fact, not a malformed record."""
    birth = person(gedcomx_messy_person)["facts"][0]
    assert birth["type"] == "Birth"
    assert birth["date"] is None
    assert birth["place"] == "Kaskaskia, Randolph, Illinois"


def test_a_fact_with_neither_date_nor_place_still_shapes(gedcomx_messy_person):
    """A bare Death type is how the tree records 'he died, we know no more'."""
    death = person(gedcomx_messy_person)["facts"][2]
    assert death == {"type": "Death", "date": None, "place": None}


def test_a_redacted_living_person_says_so(gedcomx_living_person):
    """A wall of nulls reads as a dead end; a privacy flag reads as a wall."""
    out = person(gedcomx_living_person)
    assert out["living"] is True
    assert out["restricted"] is True
    assert out["note"] == REDACTED_NOTE


def test_a_dead_person_with_no_detail_is_not_marked_restricted():
    """Sparse is not the same as withheld, and must not be labelled as it."""
    out = person({"id": "X", "living": False})
    assert "restricted" not in out
    assert "note" not in out


def test_a_place_with_no_coordinates_still_carries_its_name(gedcomx_placeless_place):
    """Most historical jurisdictions have no point; that is not a failure."""
    out = place(gedcomx_placeless_place)
    assert out["name"] == "Pendleton District"
    assert out["full_name"] == "Pendleton District"
    assert out["latitude"] is None and out["longitude"] is None


def test_a_place_carries_its_containing_jurisdiction(gedcomx_place):
    """The parent id is what makes walking the chain upward possible."""
    assert place(gedcomx_place)["jurisdiction_id"] == "331"


def test_a_place_jurisdiction_by_uri_only_still_yields_an_id():
    """Some references carry only a resource URI, with no resourceId beside it."""
    out = place({"id": "1", "jurisdiction": {"resource": "/platform/places/331"}})
    assert out["jurisdiction_id"] == "331"


def test_the_span_a_jurisdiction_existed_is_parsed(gedcomx_place):
    """A county that ceased to exist is why a record names one you cannot find."""
    assert temporal(gedcomx_place) == {
        "original": "from 1649",
        "from": "1649",
        "to": None,
    }


def test_a_closed_jurisdiction_span_has_both_ends():
    """'+1785/+1826' means the jurisdiction was abolished in 1826."""
    out = temporal({"temporalDescription": {"formal": "+1785/+1826"}})
    assert out["from"] == "1785" and out["to"] == "1826"


def test_a_place_with_no_temporal_description_is_not_an_error():
    """Absence of a span means unknown, and must not raise."""
    assert temporal({}) == {"original": None, "from": None, "to": None}


def test_places_reads_both_a_plain_document_and_an_atom_feed(gedcomx_place):
    """The Places API answers in both shapes; one shaper has to take either."""
    plain = places({"places": [gedcomx_place]})
    feed = places({"entries": [{"content": {"gedcomx": {"places": [gedcomx_place]}}}]})
    assert plain == feed
    assert plain[0]["full_name"].startswith("Kaskaskia")


def test_places_of_an_empty_response_is_an_empty_list():
    """No results is a list, not an exception."""
    assert places({}) == []


def test_a_relationship_nested_by_reference_yields_both_person_ids():
    """GEDCOM X names relationship members by reference, never by value."""
    out = relationship(
        {
            "id": "MMM-001",
            "type": "http://gedcomx.org/Couple",
            "person1": {"resourceId": "K2ZP-VY1", "resource": "#K2ZP-VY1"},
            "person2": {
                "resource": ("https://api.familysearch.org/platform/tree/persons/9XJ2-N3T")
            },
            "facts": [
                {
                    "type": "http://gedcomx.org/Marriage",
                    "date": {"original": "12 Nov 1772"},
                }
            ],
        }
    )
    assert out["type"] == "Couple"
    assert out["person1_id"] == "K2ZP-VY1"
    assert out["person2_id"] == "9XJ2-N3T"
    assert out["facts"][0]["date"] == "12 Nov 1772"


def test_a_relationship_missing_a_member_does_not_raise():
    """Half a relationship is still worth returning rather than losing."""
    out = relationship({"type": "http://gedcomx.org/ParentChild"})
    assert out["person1_id"] is None and out["person2_id"] is None


def test_a_source_description_keeps_the_citation_and_what_it_is_about():
    """The citation and the ark are the two things that lead out of the tree."""
    out = source_description(
        {
            "id": "SD-1",
            "about": "https://familysearch.org/ark:/61903/1:1:XXXX",
            "titles": [{"value": "Connecticut Church Records"}],
            "citations": [{"value": "Kaskaskia Congregational Church, vol 1, p 12"}],
            "notes": [{"text": "Baptism entry"}],
        }
    )
    assert out["about"].endswith("1:1:XXXX")
    assert out["citation"].startswith("Kaskaskia Congregational")
    assert out["title"] == "Connecticut Church Records"
    assert out["note"] == "Baptism entry"


def test_a_source_description_with_nothing_but_an_id_shapes_cleanly():
    """Tree sources are often bare; the shaper must not require the good ones."""
    assert source_description({"id": "SD-2"})["id"] == "SD-2"
