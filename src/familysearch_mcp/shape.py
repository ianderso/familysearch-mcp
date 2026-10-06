"""Shaping GEDCOM X responses into compact dicts for tool output.

GEDCOM X nests heavily and labels things with type URIs such as
``http://gedcomx.org/Birth``. These helpers flatten the parts a researcher
reads and reduce the URIs to their last segment.
"""

from __future__ import annotations

from typing import Any


def humanize(type_uri: str | None) -> str | None:
    """Reduce a GEDCOM X type URI to its final segment.

    Parameters
    ----------
    type_uri : str or None
        A URI such as ``"http://gedcomx.org/Birth"``.

    Returns
    -------
    str or None
        The last path segment, e.g. ``"Birth"``.
    """
    if not type_uri:
        return None
    return type_uri.rstrip("/").rsplit("/", 1)[-1] or None


def _first(values: Any) -> dict:
    """Return the first mapping in a list, or an empty dict."""
    if isinstance(values, list) and values and isinstance(values[0], dict):
        return values[0]
    return {}


def names(person: dict) -> list[dict]:
    """List every name form a person carries, with its type.

    A tree person often holds a birth name, a married name and one or more
    also-known-as forms. Collapsing them to the first one is how a search on
    the name a record actually used comes back empty.

    Parameters
    ----------
    person : dict
        A GEDCOM X person.

    Returns
    -------
    list of dict
        ``{"type", "text"}`` per name form, in document order.
    """
    out: list[dict] = []
    for name in person.get("names") or []:
        if not isinstance(name, dict):
            continue
        for form in name.get("nameForms") or []:
            text = (form or {}).get("fullText")
            if not text:
                text = " ".join(
                    part.get("value", "")
                    for part in (form or {}).get("parts") or []
                    if isinstance(part, dict)
                ).strip()
            if text:
                out.append({"type": humanize(name.get("type")), "text": text})
    return out


def person_name(person: dict) -> str | None:
    """Extract a person's display name.

    Parameters
    ----------
    person : dict
        A GEDCOM X person.

    Returns
    -------
    str or None
        The first name form's full text, or None if unnamed.
    """
    form = _first(_first(person.get("names")).get("nameForms"))
    return form.get("fullText") or None


def fact(entry: dict) -> dict:
    """Flatten one GEDCOM X fact.

    Parameters
    ----------
    entry : dict
        A fact, carrying ``type``, ``date`` and ``place``.

    Returns
    -------
    dict
        ``{"type", "date", "place"}`` with display values.
    """
    return {
        "type": humanize(entry.get("type")),
        "date": (entry.get("date") or {}).get("original"),
        "place": (entry.get("place") or {}).get("original"),
    }


#: What a caller should understand when FamilySearch withholds a living person.
REDACTED_NOTE = (
    "FamilySearch withholds details of living people. This record is "
    "redacted rather than empty: the person exists and is recorded as "
    "living, and the detail is visible only to the account that holds it. "
    "Do not read it as a dead end in the research."
)


def person(entry: dict) -> dict:
    """Shape a GEDCOM X person for tool output.

    A person the API has redacted for privacy is marked as such, because a
    record of nulls otherwise reads as an exhausted line of enquiry.

    Parameters
    ----------
    entry : dict
        A GEDCOM X person.

    Returns
    -------
    dict
        Id, primary name, every name form, sex, living flag and flattened
        facts. A redacted person additionally carries ``restricted`` and a
        note saying so.
    """
    all_names = names(entry)
    facts = [fact(f) for f in entry.get("facts") or []]
    display = entry.get("display") or {}
    out = {
        "id": entry.get("id"),
        "name": person_name(entry) or display.get("name"),
        "names": all_names,
        "sex": humanize((entry.get("gender") or {}).get("type")) or display.get("gender"),
        "lifespan": display.get("lifespan"),
        "living": entry.get("living"),
        "facts": facts,
    }
    if entry.get("living") and not all_names and not facts:
        out["restricted"] = True
        out["note"] = REDACTED_NOTE
    return out


def temporal(entry: dict) -> dict:
    """Read the span over which a jurisdiction existed.

    Parameters
    ----------
    entry : dict
        A place description, whose ``temporalDescription`` carries the span.

    Returns
    -------
    dict
        ``{"original", "from", "to"}``. ``from`` and ``to`` are taken from
        the GEDCOM X formal form ``+1649/+1881``; an open end is None.
    """
    span = entry.get("temporalDescription") or {}
    formal = span.get("formal") or ""
    start = end = None
    if "/" in formal:
        raw_start, raw_end = formal.split("/", 1)
        start, end = raw_start.strip() or None, raw_end.strip() or None
    elif formal:
        start = formal.strip() or None
    return {
        "original": span.get("original"),
        "from": (start or "").lstrip("+") or None,
        "to": (end or "").lstrip("+") or None,
    }


def place(entry: dict) -> dict:
    """Shape one place description.

    Parameters
    ----------
    entry : dict
        A place description from the gazetteer.

    Returns
    -------
    dict
        Id, name, jurisdictional full name, type, coordinates, the id of the
        containing jurisdiction, and the span over which this jurisdiction
        existed. Coordinates are frequently absent and stay None.
    """
    display = entry.get("display") or {}
    fallback = (_first(entry.get("names")) or {}).get("value")
    jurisdiction = entry.get("jurisdiction") or {}
    return {
        "id": entry.get("id"),
        "name": display.get("name") or fallback,
        "full_name": display.get("fullName") or fallback,
        "type": display.get("type") or humanize(entry.get("type")),
        "latitude": entry.get("latitude"),
        "longitude": entry.get("longitude"),
        "jurisdiction_id": jurisdiction.get("resourceId")
        or _resource_id(jurisdiction.get("resource")),
        "existed": temporal(entry),
    }


def _resource_id(resource: str | None) -> str | None:
    """Take the trailing id off a GEDCOM X resource reference or URI."""
    if not resource:
        return None
    return resource.rstrip("/").rsplit("/", 1)[-1].lstrip("#") or None


def places(payload: dict) -> list[dict]:
    """Pull every place description out of a Places response.

    The Places API answers both as a plain GEDCOM X document carrying
    ``places`` and as an Atom feed nesting them under ``entries``; this
    accepts either.

    Parameters
    ----------
    payload : dict
        A decoded Places response.

    Returns
    -------
    list of dict
        Shaped place descriptions, in document order.
    """
    found = list(payload.get("places") or [])
    for item in payload.get("entries") or []:
        content = ((item or {}).get("content") or {}).get("gedcomx") or {}
        found.extend(content.get("places") or [])
    return [place(p) for p in found if isinstance(p, dict)]


def jurisdiction_chain(payload: dict) -> list[dict]:
    """Order a place-description document into a containment chain.

    A place description read returns the requested place *and every
    jurisdiction above it* in one flat ``places`` array, each linking to its
    parent by a fragment reference such as ``{"resource": "#442102"}``. This
    resolves those references into the order a researcher reads: the place
    first, then the county, then the state, then the country.

    Where a level carries no ``display.fullName`` of its own, one is built
    from the levels above it, so every level reads as a full jurisdictional
    form rather than a bare name.

    Parameters
    ----------
    payload : dict
        A decoded place-description response.

    Returns
    -------
    list of dict
        Shaped places from the requested one upward. An empty list if the
        response carried none. A reference that cannot be resolved ends the
        walk rather than raising, and a cycle cannot loop forever.
    """
    entries = [p for p in payload.get("places") or [] if isinstance(p, dict)]
    if not entries:
        return []
    by_id = {p.get("id"): p for p in entries if p.get("id")}

    ordered: list[dict] = []
    seen: set[str] = set()
    current: dict | None = entries[0]
    while current is not None:
        key = current.get("id")
        if key in seen:
            break
        if key:
            seen.add(key)
        ordered.append(current)
        parent = _reference_id(current.get("jurisdiction"))
        current = by_id.get(parent) if parent else None

    chain = [place(raw) for raw in ordered]
    for index, raw in enumerate(ordered):
        if (raw.get("display") or {}).get("fullName"):
            continue
        above = [level["name"] for level in chain[index:] if level.get("name")]
        if above:
            chain[index]["full_name"] = ", ".join(above)
    return chain


def source_description(entry: dict) -> dict:
    """Shape a GEDCOM X source description.

    This is the structure behind both an attached source and an attached
    memory, so one shaper serves both.

    Parameters
    ----------
    entry : dict
        A ``sourceDescription``.

    Returns
    -------
    dict
        Id, title, citation, what it is about, media type and any note.
    """
    return {
        "id": entry.get("id"),
        "title": (_first(entry.get("titles")) or {}).get("value"),
        "citation": (_first(entry.get("citations")) or {}).get("value"),
        "about": entry.get("about"),
        "resource_type": humanize(entry.get("resourceType")),
        "media_type": entry.get("mediaType"),
        "note": (_first(entry.get("notes")) or {}).get("text"),
    }


def memory(entry: dict) -> dict:
    """Shape one attached memory: a photograph, document, story or obituary.

    A memory is an upload rather than an indexed record, so what it is
    worth depends on what it is. The artifact metadata says which kind was
    uploaded and under what filename.

    Parameters
    ----------
    entry : dict
        A ``sourceDescription`` describing an artifact.

    Returns
    -------
    dict
        The source description, plus the artifact's filename and kind.
    """
    artifact = _first(entry.get("artifactMetadata"))
    return {
        **source_description(entry),
        "description": (_first(entry.get("descriptions")) or {}).get("value"),
        "filename": artifact.get("filename"),
        "kind": humanize((_first(artifact.get("qualifiers")) or {}).get("name")),
    }


def memories(payload: dict) -> list[dict]:
    """Shape every memory in a response.

    Parameters
    ----------
    payload : dict
        A decoded memories response.

    Returns
    -------
    list of dict
        Shaped memories, in document order.
    """
    return [
        memory(entry)
        for entry in payload.get("sourceDescriptions") or []
        if isinstance(entry, dict)
    ]


def relationship(entry: dict) -> dict:
    """Flatten a GEDCOM X relationship, which names its people by reference.

    ``person1`` and ``person2`` are resource references such as
    ``{"resourceId": "K2ZP-VY1"}``, not embedded people, so the ids are
    pulled out for a caller that would otherwise have to resolve them.

    Parameters
    ----------
    entry : dict
        A GEDCOM X relationship.

    Returns
    -------
    dict
        Id, type, both person ids and any relationship facts.
    """
    return {
        "id": entry.get("id"),
        "type": humanize(entry.get("type")),
        "person1_id": _reference_id(entry.get("person1")),
        "person2_id": _reference_id(entry.get("person2")),
        "facts": [fact(f) for f in entry.get("facts") or []],
    }


def _reference_id(ref: Any) -> str | None:
    """Read the person id out of a GEDCOM X resource reference."""
    if not isinstance(ref, dict):
        return None
    return ref.get("resourceId") or _resource_id(ref.get("resource"))


def search_hits(payload: dict) -> list[dict]:
    """Flatten a GEDCOM X Atom search response into per-person hits.

    Parameters
    ----------
    payload : dict
        A search response, nesting results under ``entries``.

    Returns
    -------
    list of dict
        One entry per hit, carrying the relevance score and the person.
    """
    out: list[dict] = []
    for item in payload.get("entries") or []:
        content = ((item or {}).get("content") or {}).get("gedcomx") or {}
        people = [p for p in content.get("persons") or [] if isinstance(p, dict)]
        if not people:
            continue

        # One hit per RECORD, not per person. A record lists the person
        # matched plus whoever else appears on it -- a household, a spouse,
        # a witness -- and flattening those made `count` meaningless: asking
        # for 2 returned 4, and the extras were mostly unnamed.
        principal = next((p for p in people if p.get("principal")), people[0])
        others = [person_name(p) for p in people if p is not principal]
        entry = {
            "score": item.get("score"),
            "confidence": item.get("confidence"),
            "ark": item.get("id"),
            **person(principal),
        }
        entry.update(_hit_collection(content))
        named = [n for n in others if n]
        if named:
            # Who else the record names. Often the reason it is the right
            # record.
            entry["also_on_this_record"] = named
        out.append(entry)
    return out


def _hit_collection(content: dict) -> dict:
    """Name the collection a search hit belongs to.

    Parameters
    ----------
    content : dict
        A hit's ``content.gedcomx`` document.

    Returns
    -------
    dict
        ``collection`` and ``collection_id``, empty when not described.
    """
    for entry in content.get("sourceDescriptions") or []:
        if not (entry.get("resourceType") or "").endswith("Collection"):
            continue
        about = entry.get("about") or ""
        return {
            "collection": (_first(entry.get("titles")) or {}).get("value"),
            "collection_id": about.rstrip("/").rsplit("/", 1)[-1] or None,
        }
    return {}


def pedigree(payload: dict, number_key: str) -> list[dict]:
    """Shape a pedigree walk, keeping each person's position in it.

    Ancestry and descendancy responses carry a positional number on each
    person -- Ahnentafel for an ancestry, d'Aboville for a descendancy --
    and that number is what makes a flat list readable as a tree.

    Parameters
    ----------
    payload : dict
        A decoded ancestry or descendancy response.
    number_key : str
        ``"ascendancyNumber"`` or ``"descendancyNumber"``, whichever the
        resource uses.

    Returns
    -------
    list of dict
        Shaped people, each carrying ``position``, ordered as returned.
    """
    out = []
    for entry in payload.get("persons") or []:
        if not isinstance(entry, dict):
            continue
        shaped = person(entry)
        shaped["position"] = (entry.get("display") or {}).get(number_key)
        out.append(shaped)
    return out


def _couple_partner(rel: dict, person_id: str) -> str | None:
    """Return the other member of a couple relationship, or None."""
    first, second = _reference_id(rel.get("person1")), _reference_id(rel.get("person2"))
    if first == person_id:
        return second
    if second == person_id:
        return first
    return None


def relatives(payload: dict, person_id: str) -> dict:
    """Group a families document into parents, spouses, children and siblings.

    A families read returns every person and every relationship in one
    document, with the relationships naming people by reference. This
    resolves them against the person asked about.

    FamilySearch's ``childAndParentsRelationships`` is its own extension to
    GEDCOM X: one record tying a child to up to two parents, rather than the
    two separate ParentChild relationships the base specification uses. Both
    forms are read here, because responses carry both.

    Parameters
    ----------
    payload : dict
        A decoded families response.
    person_id : str
        The person the document was read for.

    Returns
    -------
    dict
        ``{"parents", "spouses", "children", "siblings"}``, each a list of
        shaped people. A person whose relationship cannot be resolved is
        left out rather than guessed at.
    """
    people = {
        entry.get("id"): person(entry)
        for entry in payload.get("persons") or []
        if isinstance(entry, dict) and entry.get("id")
    }

    parents: list[str] = []
    children: list[str] = []
    spouses: list[str] = []
    siblings: list[str] = []
    parents_of_subject: set[str] = set()

    for rel in payload.get("childAndParentsRelationships") or []:
        if not isinstance(rel, dict):
            continue
        child = _reference_id(rel.get("child"))
        rel_parents = [
            pid
            for pid in (
                _reference_id(rel.get("parent1")),
                _reference_id(rel.get("parent2")),
            )
            if pid
        ]
        if child == person_id:
            parents.extend(rel_parents)
            parents_of_subject.update(rel_parents)
        elif person_id in rel_parents and child:
            children.append(child)

    for rel in payload.get("relationships") or []:
        if not isinstance(rel, dict):
            continue
        kind = humanize(rel.get("type"))
        if kind == "Couple":
            if partner := _couple_partner(rel, person_id):
                spouses.append(partner)
        elif kind == "ParentChild":
            parent, child = (
                _reference_id(rel.get("person1")),
                _reference_id(rel.get("person2")),
            )
            if child == person_id and parent:
                parents.append(parent)
                parents_of_subject.add(parent)
            elif parent == person_id and child:
                children.append(child)

    # A sibling is anyone else sharing a parent with the subject. This has to
    # run after the parents are known, so it is a second pass.
    for rel in payload.get("childAndParentsRelationships") or []:
        if not isinstance(rel, dict):
            continue
        child = _reference_id(rel.get("child"))
        if not child or child == person_id:
            continue
        shared = {
            _reference_id(rel.get("parent1")),
            _reference_id(rel.get("parent2")),
        } & parents_of_subject
        if shared:
            siblings.append(child)

    def resolve(ids: list[str]) -> list[dict]:
        seen: set[str] = set()
        out = []
        for pid in ids:
            if pid in seen or pid not in people:
                continue
            seen.add(pid)
            out.append(people[pid])
        return out

    return {
        "parents": resolve(parents),
        "spouses": resolve(spouses),
        "children": resolve(children),
        "siblings": resolve(siblings),
    }


def person_sources(payload: dict) -> list[dict]:
    """Shape attached sources, keeping what each one is said to support.

    A source reference carries ``tags`` naming the conclusions it backs --
    Name, Birth, Death -- which is the difference between "a source is
    attached" and "the birth date has a source".

    Parameters
    ----------
    payload : dict
        A decoded person-sources response.

    Returns
    -------
    list of dict
        One entry per source description, with any tags from the person's
        reference to it merged in.
    """
    tags_by_id: dict[str, list[str]] = {}
    for entry in payload.get("persons") or []:
        for ref in (entry or {}).get("sources") or []:
            key = (ref.get("description") or "").lstrip("#")
            if not key:
                continue
            tags_by_id.setdefault(key, []).extend(
                humanize(tag.get("resource"))
                for tag in ref.get("tags") or []
                if isinstance(tag, dict)
            )

    out = []
    for entry in payload.get("sourceDescriptions") or []:
        if not isinstance(entry, dict):
            continue
        shaped = source_description(entry)
        shaped["supports"] = [tag for tag in tags_by_id.get(entry.get("id") or "", []) if tag]
        out.append(shaped)
    return out


def source_descriptions(payload: dict) -> list[dict]:
    """Shape every source description in a response.

    Parameters
    ----------
    payload : dict
        A decoded response carrying ``sourceDescriptions``.

    Returns
    -------
    list of dict
        Shaped source descriptions, in document order.
    """
    return [
        source_description(entry)
        for entry in payload.get("sourceDescriptions") or []
        if isinstance(entry, dict)
    ]


def change_entries(payload: dict) -> list[dict]:
    """Flatten a change-history feed.

    Parameters
    ----------
    payload : dict
        A decoded change-history response, an Atom feed in JSON form.

    Returns
    -------
    list of dict
        One entry per change: what changed, who changed it, when, and the
        reason they gave.
    """
    out = []
    for item in payload.get("entries") or []:
        if not isinstance(item, dict):
            continue
        info = _first(item.get("changeInfo"))
        out.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "updated": item.get("updated"),
                "contributors": [
                    c.get("name")
                    for c in item.get("contributors") or []
                    if isinstance(c, dict) and c.get("name")
                ],
                "operation": humanize(info.get("operation")),
                "changed": humanize(info.get("objectType")),
                "reason": info.get("reason"),
            }
        )
    return out


def match_hits(payload: dict) -> list[dict]:
    """Flatten a duplicate-match feed into candidates with their scores.

    A tree match embeds the candidate person. A record match embeds only a
    description of the collection it came from, and names the candidate by
    its ark in the entry id. Both are candidates, so both are returned; an
    entry is never dropped for lacking an embedded person.

    Parameters
    ----------
    payload : dict
        A decoded matches response, an Atom feed in JSON form.

    Returns
    -------
    list of dict
        One entry per candidate, carrying the score, FamilySearch's
        confidence band, the ark or id identifying it, and the person where
        one was embedded.
    """
    out = []
    for item in payload.get("entries") or []:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or {}).get("gedcomx") or {}
        base = {
            "match_id": item.get("id"),
            "title": item.get("title"),
            "score": item.get("score"),
            "confidence": item.get("confidence"),
            "status": humanize(_first(item.get("matchInfo")).get("status")),
        }
        people = [p for p in content.get("persons") or [] if isinstance(p, dict)]
        if people:
            out.extend({**base, **person(p)} for p in people)
        else:
            out.append(base)
    return out


def collection(entry: dict) -> dict:
    """Shape one record collection.

    Parameters
    ----------
    entry : dict
        A GEDCOM X collection.

    Returns
    -------
    dict
        Id, title, size, and the language and attribution if given.
    """
    return {
        "id": entry.get("id"),
        "title": entry.get("title") or (_first(entry.get("titles")) or {}).get("value"),
        "size": entry.get("size"),
        "lang": entry.get("lang"),
        "content": [
            {
                "type": humanize(item.get("resourceType")),
                "count": item.get("count"),
            }
            for item in entry.get("content") or []
            if isinstance(item, dict)
        ],
    }


def collections(payload: dict) -> list[dict]:
    """Shape every collection in a response.

    Parameters
    ----------
    payload : dict
        A decoded collections response.

    Returns
    -------
    list of dict
        Shaped collections, in document order.
    """
    return [
        collection(entry) for entry in payload.get("collections") or [] if isinstance(entry, dict)
    ]


#: Indexed field labels that name the film and image a record was read from.
#: These are the route to the document when no image link is published.
FILM_LABELS = ("FS_DIGITAL_FILM_NBR", "FS_IMAGE_NBR")


def collection_descriptions(payload: dict) -> list[dict]:
    """Shape the sub-collection catalogue, which arrives as source descriptions.

    Listing the record collections does not return GEDCOM X ``collections``;
    it returns a ``sourceDescription`` per collection, carrying the coverage
    statement that says what the collection actually holds.

    Parameters
    ----------
    payload : dict
        A decoded sub-collections response.

    Returns
    -------
    list of dict
        Id, title, citation, and a coverage list of record type, place and
        period. Coverage is what makes a nil result mean anything.
    """
    out = []
    for entry in payload.get("sourceDescriptions") or []:
        if not isinstance(entry, dict):
            continue
        shaped = source_description(entry)
        shaped["description"] = (_first(entry.get("descriptions")) or {}).get("value")
        shaped["coverage"] = [
            {
                "record_type": humanize(item.get("recordType")),
                "place": (item.get("spatial") or {}).get("original"),
                "period": (item.get("temporal") or {}).get("original")
                or (item.get("temporal") or {}).get("formal"),
            }
            for item in entry.get("coverage") or []
            if isinstance(item, dict)
        ]
        out.append(shaped)
    return out


def record_fields(entry: dict) -> list[dict]:
    """Flatten the indexed fields of a record.

    A field is what an indexer actually read off the document, and the
    ``labelId`` names which box on the form it came from. That is the level
    of detail a persona summary throws away.

    Parameters
    ----------
    entry : dict
        Anything carrying GEDCOM X ``fields``: a record, a person, a fact.

    Returns
    -------
    list of dict
        ``{"type", "label", "value"}`` per indexed value.
    """
    out = []
    for field in entry.get("fields") or []:
        if not isinstance(field, dict):
            continue
        kind = humanize(field.get("type"))
        for value in field.get("values") or []:
            if not isinstance(value, dict):
                continue
            text = value.get("text")
            if text is None:
                continue
            out.append(
                {
                    "type": kind,
                    "label": value.get("labelId"),
                    "value": text,
                }
            )
    return out


def record_persons(payload: dict) -> list[dict]:
    """Shape every person on a record, with that person's indexed fields.

    Parameters
    ----------
    payload : dict
        A decoded record response.

    Returns
    -------
    list of dict
        Shaped people, each carrying the fields indexed against them.
    """
    out = []
    for entry in payload.get("persons") or []:
        if not isinstance(entry, dict):
            continue
        shaped = person(entry)
        shaped["fields"] = record_fields(entry)
        out.append(shaped)
    return out


def links(payload: dict) -> dict:
    """Read the ``links`` block, which JSON responses key by relation name.

    Parameters
    ----------
    payload : dict
        Anything carrying a ``links`` block.

    Returns
    -------
    dict
        Relation name to href, dropping anything without one.
    """
    found = payload.get("links")
    if not isinstance(found, dict):
        return {}
    return {
        rel: target.get("href")
        for rel, target in found.items()
        if isinstance(target, dict) and target.get("href")
    }


def collection_field_labels(payload: dict) -> list[dict]:
    """Extract a collection's field-code dictionary.

    An indexed record labels its values with codes such as ``PR_FTHR_NAME``
    rather than words. The codes are per-collection, and the collection
    descriptor carries the decoder in ``recordDescriptors``.

    Parameters
    ----------
    payload : dict
        A ``/platform/records/collections/{id}`` response.

    Returns
    -------
    list of dict
        One ``{"code", "label", "sort_key"}`` per field, in display order.
    """
    out: list[dict] = []
    seen: set[str] = set()
    for descriptor in payload.get("recordDescriptors") or []:
        for field in (descriptor or {}).get("fields") or []:
            for value in (field or {}).get("values") or []:
                code = value.get("labelId")
                if not code or code in seen:
                    continue
                seen.add(code)
                labels = value.get("labels") or []
                label = (labels[0] or {}).get("value") if labels else None
                out.append(
                    {
                        "code": code,
                        "label": label,
                        "sort_key": value.get("displaySortKey"),
                    }
                )
    return out


def record_type_facet(payload: dict) -> list[dict]:
    """Extract the record-type counts from a faceted search response.

    FamilySearch publishes no mapping for ``f.recordType``'s integer codes,
    and a wrong one silently returns nothing. The facet is the only reliable
    way to learn which codes a given result set actually contains.

    Parameters
    ----------
    payload : dict
        A GEDCOM X Atom search response requested with ``c.recordType=on``.

    Returns
    -------
    list of dict
        One ``{"code", "count"}`` per record type present, largest first.
    """
    out: list[dict] = []
    for facet in payload.get("facets") or []:
        if (facet or {}).get("displayName") != "recordType":
            continue
        for bucket in facet.get("facets") or []:
            code = (bucket or {}).get("displayName")
            if code is None:
                continue
            out.append({"code": str(code), "count": bucket.get("count")})
    return sorted(out, key=lambda e: -(e["count"] or 0))


def waypoints(payload: dict, collection_id: str | None = None) -> list[dict]:
    """Extract the child waypoints of a collection or waypoint.

    A waypoint response returns everything as ``sourceDescriptions``: the
    node itself first, then its children. The children of a collection are
    its volumes or date ranges; the children of a waypoint are eventually
    image arks.

    Parameters
    ----------
    payload : dict
        A waypoints response.
    collection_id : str, optional
        The node being browsed, so its own entries can be filtered out.

    Returns
    -------
    list of dict
        One ``{"id", "title", "kind", "about"}`` per child, in order.
    """
    out: list[dict] = []
    skip = {f"sd_c_{collection_id}", f"sd_cr_{collection_id}"} if collection_id else set()
    for entry in payload.get("sourceDescriptions") or []:
        if not isinstance(entry, dict) or entry.get("id") in skip:
            continue
        kind = humanize(entry.get("resourceType"))
        out.append(
            {
                "id": entry.get("id"),
                "title": (_first(entry.get("titles")) or {}).get("value"),
                "kind": kind,
                "about": entry.get("about"),
            }
        )
    return out


def records_on_image(payload: dict) -> list[dict]:
    """Extract the records indexed from one image.

    The entries carry no titles -- verified live 2026-09-23, a manifest page
    returned 28 records each with only an id, an ark and a ``record`` link.
    So the ark is reconstructed in the ``1:2:`` form ``get_record`` accepts,
    which is what makes the result actionable rather than a list of opaque
    ids.

    Parameters
    ----------
    payload : dict
        A ``/platform/records/images/{ark}/records`` response.

    Returns
    -------
    list of dict
        One entry per record, with the ark to read it by.
    """
    out: list[dict] = []
    for entry in payload.get("sourceDescriptions") or []:
        if not isinstance(entry, dict):
            continue
        about = entry.get("about") or ""
        ark = about.split("ark:/61903/")[-1] if "ark:/61903/" in about else None
        out.append(
            {
                "ark": ark or entry.get("id"),
                "record_id": entry.get("id"),
                "resource_type": humanize(entry.get("resourceType")),
                "url": about or None,
            }
        )
    return out


#: Context kept either side of a matched term in a full-text snippet.
SNIPPET_CONTEXT = 120

#: The longest a joined snippet may grow.
SNIPPET_LIMIT = 4 * SNIPPET_CONTEXT

#: Snippets kept per full-text hit.
SNIPPETS_PER_HIT = 3

#: Distinct recognised names kept per full-text hit. A probate file names
#: dozens of people, and the list is a pointer to the page, not a summary.
NAMES_PER_HIT = 12


def snippets(text: str, terms: list[str]) -> list[str]:
    """Cut the passages around matched terms out of a page transcript.

    The service returns the whole page's text -- tens of thousands of
    characters -- and the matched terms bare, with no context. This keeps
    a few windows around the first matches, longest term first, so a
    phrase is preferred over one of its words.

    Parameters
    ----------
    text : str
        The machine-read page text.
    terms : list of str
        The matched terms the service reported.

    Returns
    -------
    list of str
        Up to :data:`SNIPPETS_PER_HIT` passages, in page order, each with an
        ellipsis where it was cut.
    """
    flat = " ".join((text or "").split())
    if not flat:
        return []
    lowered = flat.lower()
    spans: list[tuple[int, int]] = []
    for term in sorted({t for t in terms if t and t.strip()}, key=len, reverse=True):
        start = lowered.find(term.lower())
        while start != -1 and len(spans) < SNIPPETS_PER_HIT * 3:
            spans.append((max(0, start - SNIPPET_CONTEXT), start + len(term) + SNIPPET_CONTEXT))
            start = lowered.find(term.lower(), start + len(term))
    merged: list[tuple[int, int]] = []
    for begin, end in sorted(spans):
        # Overlapping windows join, but only up to one passage's length: a
        # page that repeats a name every line would otherwise come back whole.
        if merged and begin <= merged[-1][1] and end - merged[-1][0] <= SNIPPET_LIMIT:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        elif not merged or begin >= merged[-1][1]:
            merged.append((begin, end))
    out = []
    for begin, end in merged[:SNIPPETS_PER_HIT]:
        piece = flat[begin:end].strip()
        out.append(("..." if begin > 0 else "") + piece + ("..." if end < len(flat) else ""))
    return out


def fulltext_hits(payload: dict) -> list[dict]:
    """Shape full-text search entries into compact hits.

    Each entry is one page image. The service sends no relevance score and
    no snippet: ``highlightTexts`` are the matched terms, bare, and
    ``textDocument`` is the whole page. Verified live 2026-10-05.

    Parameters
    ----------
    payload : dict
        A full-text search response.

    Returns
    -------
    list of dict
        One hit per page: the image ark and its web address, the collection,
        the record's title, type, place and date, the matched terms, passages
        around them, and the names recognised on the page.
    """
    out = []
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        content = entry.get("content") or {}
        matched = [t for t in content.get("highlightTexts") or [] if isinstance(t, str)]
        names_seen: list[str] = []
        for entity in content.get("entities") or []:
            if (entity or {}).get("type") != "NAME":
                continue
            value = (entity.get("value") or "").strip()
            if value and value not in names_seen:
                names_seen.append(value)
        out.append(
            {
                "image_ark": entry.get("id"),
                "url": entry.get("sourceUrl"),
                "collection": entry.get("collectionTitle"),
                "collection_id": entry.get("collectionId"),
                "title": content.get("title"),
                "record_type": content.get("recordType"),
                "place": content.get("recordPlace"),
                "date": content.get("recordDate"),
                "matched": matched,
                "snippets": snippets(content.get("textDocument") or "", matched),
                "names_on_page": names_seen[:NAMES_PER_HIT],
            }
        )
    return out


def fulltext_facets(payload: dict) -> list[dict]:
    """Shape full-text facets, keeping the filter each bucket selects.

    A bucket's ``params`` is the filter to send back to narrow to it, e.g.
    ``c.recordPlace1=on&f.recordPlace0=10``: the ``f.`` part filters and
    the ``c.`` part asks for the next level down. Places, record types and
    collections are named by ids the service assigns, so this is the only
    way to learn them.
    """
    out = []
    for facet in payload.get("facets") or []:
        if not isinstance(facet, dict):
            continue
        out.append(
            {
                "facet": facet.get("displayName"),
                "buckets": [
                    {
                        "name": bucket.get("displayName"),
                        "count": bucket.get("count"),
                        "filter": bucket.get("params"),
                    }
                    for bucket in facet.get("facets") or []
                    if isinstance(bucket, dict)
                ],
            }
        )
    return out
