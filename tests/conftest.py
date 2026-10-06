"""Shared fixtures. Every test runs against a mocked API; no token is needed."""

from __future__ import annotations

import ipaddress
import json
import socket
import tempfile
from pathlib import Path

import pytest

from familysearch_mcp.config import Config


@pytest.fixture
def anon_config() -> Config:
    """Configuration with no token, as an unconfigured install has."""
    return Config(environment="production", timeout=5.0)


@pytest.fixture
def auth_config() -> Config:
    """Configuration carrying a token."""
    return Config(
        access_token="test-token",
        client_id="test-client",
        environment="production",
        timeout=5.0,
    )


@pytest.fixture
def gedcomx_person() -> dict:
    """A GEDCOM X person with a name, sex and a birth fact."""
    return {
        "id": "K2ZP-VY1",
        "living": False,
        "gender": {"type": "http://gedcomx.org/Male"},
        "names": [{"nameForms": [{"fullText": "Ezra Pettibone"}]}],
        "facts": [
            {
                "type": "http://gedcomx.org/Birth",
                "date": {"original": "23 April 1751"},
                "place": {"original": "Kaskaskia, Randolph, Illinois"},
            }
        ],
    }


async def call_tool(tool_name: str, /, **arguments) -> dict:
    """Invoke a tool the way a client does, so Field defaults are resolved.

    Calling a tool function directly in Python hands it ``FieldInfo`` objects
    rather than the declared defaults. The tool name is positional-only so a
    tool parameter called ``name`` does not collide with it.
    """
    from familysearch_mcp import server

    result = await server.mcp.call_tool(tool_name, arguments)
    return json.loads(result.content[0].text)


@pytest.fixture
def gedcomx_messy_person() -> dict:
    """A person with several name forms, an undated fact and a placeless fact.

    Real GEDCOM X is not tidy. A birth name plus an also-known-as, a fact
    carrying neither date nor place, and a place with no coordinates are all
    ordinary, and each has broken a naive shaper at some point.
    """
    return {
        "id": "9XJ2-N3T",
        "living": False,
        "gender": {"type": "http://gedcomx.org/Female"},
        "names": [
            {
                "type": "http://gedcomx.org/BirthName",
                "nameForms": [
                    {
                        "fullText": "Mary Elizabeth Chesebrough",
                        "parts": [
                            {
                                "type": "http://gedcomx.org/Given",
                                "value": "Mary Elizabeth",
                            },
                            {
                                "type": "http://gedcomx.org/Surname",
                                "value": "Chesebrough",
                            },
                        ],
                    }
                ],
            },
            {
                "type": "http://gedcomx.org/MarriedName",
                "nameForms": [{"fullText": "Mary Elizabeth Pettibone"}],
            },
            {
                "type": "http://gedcomx.org/AlsoKnownAs",
                "nameForms": [{"fullText": "Polly Pettibone"}],
            },
        ],
        "facts": [
            {
                "type": "http://gedcomx.org/Birth",
                "place": {"original": "Kaskaskia, Randolph, Illinois"},
            },
            {"type": "http://gedcomx.org/Residence", "date": {"original": "1790"}},
            {"type": "http://gedcomx.org/Death"},
        ],
    }


@pytest.fixture
def gedcomx_living_person() -> dict:
    """A living person as FamilySearch redacts one: a flag and almost nothing.

    Privacy withholding is not a research dead end, and must not shape into
    something that reads like one.
    """
    return {"id": "L4RT-9QP", "living": True}


@pytest.fixture
def gedcomx_place() -> dict:
    """A place description with a jurisdiction reference and a temporal range."""
    return {
        "id": "442",
        "type": "http://gedcomx.org/Town",
        "names": [{"lang": "en", "value": "Kaskaskia"}],
        "latitude": 41.3354,
        "longitude": -71.9059,
        "jurisdiction": {"resourceId": "331", "resource": "/platform/places/331"},
        "temporalDescription": {
            "original": "from 1649",
            "formal": "+1649/",
        },
        "display": {
            "name": "Kaskaskia",
            "fullName": "Kaskaskia, Randolph, Illinois, United States",
            "type": "Town",
        },
    }


@pytest.fixture
def gedcomx_placeless_place() -> dict:
    """A place with no coordinates and no display block.

    Plenty of gazetteer entries carry neither. Shaping must still produce a
    usable name rather than a record of nulls.
    """
    return {
        "id": "9981",
        "names": [{"value": "Pendleton District"}],
        "type": "http://gedcomx.org/Other",
    }


@pytest.fixture
def place_description_document() -> dict:
    """A place description read, with the jurisdictions inlined above it.

    This is the shape FamilySearch documents: one flat ``places`` array whose
    first entry is the place asked for, each entry pointing at its parent by
    a fragment reference. Modelled on the published Paris example, with a
    historical county that no longer exists.
    """
    return {
        "places": [
            {
                "id": "7344697",
                "lang": "en",
                "temporalDescription": {"formal": "+1785/+1826"},
                "latitude": 34.6,
                "longitude": -82.8,
                "jurisdiction": {"resource": "#442102"},
                "names": [{"lang": "en", "value": "Pendleton District"}],
                "display": {
                    "name": "Pendleton District",
                    "fullName": "Pendleton District, South Carolina, United States",
                    "type": "District",
                },
            },
            {
                "id": "442102",
                "jurisdiction": {"resource": "#204"},
                "names": [{"value": "South Carolina"}],
                "display": {"name": "South Carolina", "type": "State"},
            },
            {
                "id": "204",
                "names": [{"lang": "en", "value": "United States"}],
                "display": {"name": "United States", "type": "Country"},
            },
        ]
    }


@pytest.fixture
def place_search_feed(gedcomx_place) -> dict:
    """An Atom-shaped place search response, as the gazetteer returns one."""
    return {
        "results": 1,
        "index": 0,
        "title": "Place Search Results",
        "entries": [
            {
                "id": "442",
                "score": 100.0,
                "content": {"gedcomx": {"places": [gedcomx_place]}},
            }
        ],
    }


@pytest.fixture
def families_document() -> dict:
    """A families read: everyone around one person, tied by reference.

    FamilySearch's ``childAndParentsRelationships`` is its own extension --
    one record binding a child to up to two parents -- and sits alongside
    the base GEDCOM X ``relationships``. Both appear here because both
    appear in real responses.
    """
    return {
        "persons": [
            {"id": "K2ZP-VY1", "names": [{"nameForms": [{"fullText": "Ezra Pettibone"}]}]},
            {"id": "P-FA", "names": [{"nameForms": [{"fullText": "Amos Pettibone"}]}]},
            {"id": "P-MO", "names": [{"nameForms": [{"fullText": "Abigail Thackeray"}]}]},
            {"id": "P-WF", "names": [{"nameForms": [{"fullText": "Mary Chesebrough"}]}]},
            {"id": "P-CH", "names": [{"nameForms": [{"fullText": "Ezra Pettibone Jr"}]}]},
            {"id": "P-SB", "names": [{"nameForms": [{"fullText": "Lydia Pettibone"}]}]},
            {"id": "L4RT-9QP", "living": True},
        ],
        "relationships": [
            {
                "id": "R-1",
                "type": "http://gedcomx.org/Couple",
                "person1": {"resourceId": "K2ZP-VY1"},
                "person2": {"resourceId": "P-WF"},
                "facts": [
                    {
                        "type": "http://gedcomx.org/Marriage",
                        "date": {"original": "12 Nov 1772"},
                    }
                ],
            }
        ],
        "childAndParentsRelationships": [
            {
                "id": "CAP-1",
                "child": {"resourceId": "K2ZP-VY1"},
                "parent1": {"resourceId": "P-FA"},
                "parent2": {"resourceId": "P-MO"},
            },
            {
                "id": "CAP-2",
                "child": {"resourceId": "P-SB"},
                "parent1": {"resourceId": "P-FA"},
                "parent2": {"resourceId": "P-MO"},
            },
            {
                "id": "CAP-3",
                "child": {"resourceId": "P-CH"},
                "parent1": {"resourceId": "K2ZP-VY1"},
                "parent2": {"resourceId": "P-WF"},
            },
            {
                "id": "CAP-4",
                "child": {"resourceId": "L4RT-9QP"},
                "parent1": {"resourceId": "K2ZP-VY1"},
            },
        ],
    }


@pytest.fixture
def ancestry_document() -> dict:
    """An ancestry walk, each person numbered by Ahnentafel position."""
    return {
        "persons": [
            {
                "id": "K2ZP-VY1",
                "names": [{"nameForms": [{"fullText": "Ezra Pettibone"}]}],
                "display": {
                    "name": "Ezra Pettibone",
                    "gender": "Male",
                    "lifespan": "1751-1826",
                    "ascendancyNumber": "1",
                },
            },
            {
                "id": "P-FA",
                "names": [{"nameForms": [{"fullText": "Amos Pettibone"}]}],
                "display": {"lifespan": "1720-1790", "ascendancyNumber": "2"},
            },
            {
                "id": "P-MO",
                "display": {"name": "Abigail Thackeray", "ascendancyNumber": "3"},
            },
        ]
    }


@pytest.fixture
def person_sources_document() -> dict:
    """Attached sources, with the person's reference saying what each supports."""
    return {
        "persons": [
            {
                "id": "K2ZP-VY1",
                "sources": [
                    {
                        "id": "SR-1",
                        "description": "#SD-1",
                        "tags": [
                            {"resource": "http://gedcomx.org/Name"},
                            {"resource": "http://gedcomx.org/Birth"},
                        ],
                    },
                    {"id": "SR-2", "description": "#SD-2"},
                ],
            }
        ],
        "sourceDescriptions": [
            {
                "id": "SD-1",
                "about": "https://familysearch.org/ark:/61903/1:1:XXXX",
                "titles": [{"value": "Kaskaskia Births"}],
                "citations": [{"value": "Kaskaskia, Illinois, births, vol 1"}],
            },
            {
                "id": "SD-2",
                "titles": [{"value": "A note from a cousin"}],
            },
        ],
    }


@pytest.fixture
def change_history_feed() -> dict:
    """A change history, as an Atom feed in JSON form."""
    return {
        "entries": [
            {
                "id": "CH-2",
                "title": "Birth Added",
                "updated": 1543677067759,
                "contributors": [{"name": "Mr. Contributor"}],
                "changeInfo": [
                    {
                        "operation": "http://familysearch.org/v1/Create",
                        "objectType": "http://gedcomx.org/Birth",
                        "reason": "found in the town records",
                    }
                ],
            },
            {
                "id": "CH-1",
                "title": "Person Created",
                "updated": 1443677067759,
                "contributors": [{"name": "Another Contributor"}],
                "changeInfo": [
                    {
                        "operation": "http://familysearch.org/v1/Create",
                        "objectType": "http://gedcomx.org/Person",
                    }
                ],
            },
        ]
    }


@pytest.fixture
def matches_feed(gedcomx_person) -> dict:
    """Duplicate candidates, scored by FamilySearch's own confidence."""
    return {
        "entries": [
            {
                "id": "MATCH-1",
                "score": 4.5,
                "confidence": 4,
                "content": {"gedcomx": {"persons": [gedcomx_person]}},
            }
        ]
    }


@pytest.fixture
def record_document() -> dict:
    """One indexed record: people, and the fields an indexer read off the form."""
    return {
        "persons": [
            {
                "id": "1:1:XXXX-YYY",
                "names": [{"nameForms": [{"fullText": "Ezra Pettibone"}]}],
                "gender": {"type": "http://gedcomx.org/Male"},
                "fields": [
                    {
                        "type": "http://gedcomx.org/Age",
                        "values": [
                            {
                                "type": "http://gedcomx.org/Original",
                                "labelId": "PR_AGE",
                                "text": "49",
                            }
                        ],
                    }
                ],
            }
        ],
        "fields": [
            {
                "type": "http://gedcomx.org/RecordType",
                "values": [{"labelId": "TYPE", "text": "Census"}],
            }
        ],
        "sourceDescriptions": [
            {
                "id": "SD-R",
                "about": "https://familysearch.org/ark:/61903/3:1:ZZZZ",
                "resourceType": "http://gedcomx.org/DigitalArtifact",
                "titles": [{"value": "1800 United States Federal Census"}],
            }
        ],
        "links": {
            "image": {"href": "https://familysearch.org/ark:/61903/3:1:ZZZZ"},
            "self": {"href": "https://api.familysearch.org/platform/records/x"},
        },
    }


# --------------------------------------------------------------------------- #
# Argument building for whole-surface sweeps
# --------------------------------------------------------------------------- #
#: Errors a tool raises from its own input validation, before it does any
#: work. A sweep that receives one of these has not tested what it thinks it
#: has, so :func:`assert_reached_body` treats them as a failure of the sweep
#: rather than of the tool.
LOCAL_VALIDATION_ERRORS = frozenset(
    {
        "no_criteria",
        "no_target",
        "invalid_image_url",
        "invalid_record_type_code",
        "unknown_record_type",
        "no_such_directory",
        "file_exists",
        "invalid_destination",
        "invalid_id",
        "not_configured",
        "no_claims",
        "possibly_living",
        "collection_required",
        "conflicting_collection",
        "offset_out_of_range",
    }
)

#: Escape hatch for a tool whose "pass at least one of these" rule cannot be
#: satisfied from the schema and the parameter names alone.
#:
#: **Currently empty, and that is the point**: :func:`valid_args` reaches the
#: body of every tool unaided. Add an entry only when it stops doing so, and
#: :func:`assert_reached_body` will tell you which tool needs it.
ARGUMENT_HINTS: dict[str, dict] = {}


def _value_for(name: str, spec: dict):
    """Invent a value a tool will accept for one schema property.

    Driven by the property's schema first and its *name* second. Names carry
    meaning the schema does not: an ark has a shape, a record-type code must
    be numeric, a destination must be writable. A generic string satisfies
    none of them, and the tool refuses it before doing any work.
    """
    if spec.get("enum"):
        return spec["enum"][0]

    lowered = name.lower()
    if "image_ark" in lowered:
        return "3:1:33SQ-G5LD-93NY"
    if lowered.endswith("ark") or lowered in {"record_id", "person_id"}:
        return "K2ZP-VY1"
    if "record_type_code" in lowered:
        return "4"
    if lowered.endswith(("_path", "path", "destination")):
        # A real, writable directory: a tool that writes a file checks its
        # parent exists before doing anything else.
        return str(Path(tempfile.gettempdir()) / "fs-sweep-sample.jpg")
    if "url" in lowered:
        return "https://sg30p0.familysearch.org/service/records/sample.jpg"
    if "collection_id" in lowered:
        return "1417683"
    if "catalog_id" in lowered:
        return "3154151"
    if "place_id" in lowered:
        return "442"
    if lowered.endswith("year") or lowered.startswith("year"):
        return 1850

    # A declared default is the tool's own idea of a sensible value, so it
    # beats any generic this builder would invent. An empty-string default is
    # the exception: a search term of "" is exactly what makes a tool answer
    # no_criteria, so fall through to the generic instead.
    default = spec.get("default")
    if default not in (None, ""):
        return default

    kind = spec.get("type")
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return {}
    return "Pettibone"


#: Parameters that satisfy a tool's "at least one of these" rule when it
#: declares everything optional. Tried in order.
_SEARCH_TERMS = (
    "surname",
    "given",
    "name",
    "transcription_text",
    "tag_text",
    "collection_id",
    "waypoint_id",
)


def valid_args(tool, **overrides) -> dict:
    """Build arguments that carry a tool past its own input validation.

    Covers every required property from the schema, adds a search term for a
    tool whose parameters are all optional but which refuses an empty call,
    then applies any :data:`ARGUMENT_HINTS` entry and the caller's overrides.

    Parameters
    ----------
    tool
        A registered tool, as ``mcp.list_tools`` returns it.
    **overrides
        Values to force, beyond what is derived.

    Returns
    -------
    dict
        Arguments to invoke the tool with.
    """
    schema = tool.input_schema or {}
    props = schema.get("properties") or {}
    args = {name: _value_for(name, props.get(name) or {}) for name in schema.get("required") or []}
    if not args:
        for candidate in _SEARCH_TERMS:
            if candidate in props:
                args[candidate] = _value_for(candidate, props[candidate])
                break
    args.update(ARGUMENT_HINTS.get(tool.name, {}))
    args.update(overrides)
    return args


def assert_reached_body(tool_name: str, result) -> None:
    """Fail if a sweep stopped at input validation instead of the tool's body.

    Without this a sweep quietly stops proving anything the moment a tool
    grows a new argument check: the tool returns a tidy error envelope, the
    assertion that "an envelope came back" passes, and the behaviour under
    test is never exercised.
    """
    if isinstance(result, dict) and result.get("error") in LOCAL_VALIDATION_ERRORS:
        raise AssertionError(
            f"{tool_name} rejected the sweep's arguments with "
            f"{result['error']!r} before doing any work, so this sweep did "
            f"not test it. Add an ARGUMENT_HINTS entry for {tool_name} in "
            f"tests/conftest.py. Message was: {result.get('message')!r}"
        )


@pytest.fixture(autouse=True)
def _isolate_catalogue_cache(tmp_path, monkeypatch):
    """Keep the collection catalogue out of the developer's real cache.

    ``search_collections`` persists the catalogue to
    ``~/.cache/familysearch-mcp/collections.json`` so a restart does not pay
    the ninety-second walk again. Without this fixture a test would read
    that file -- 3,443 real collections -- and silently ignore its own
    mocked pages, which is exactly how three tests started passing against
    the wrong data.

    Also clears the in-memory copy, so one test cannot seed another.
    """
    from familysearch_mcp import server

    monkeypatch.setattr(server, "CATALOGUE_CACHE", tmp_path / "collections.json", raising=False)
    monkeypatch.setattr(server.state, "catalogue", None, raising=False)
    yield


@pytest.fixture(autouse=True)
def _isolate_env_file(tmp_path, monkeypatch):
    """Keep the developer's own env file out of every test.

    The server looks for ``.env`` from the working directory upward, and the
    suite is usually run from a checkout that has one -- holding a real
    token. Without this, token recovery in a test would quietly read it.
    """
    monkeypatch.delenv("FS_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def slept(monkeypatch) -> list[float]:
    """Record the client's retry waits instead of sleeping through them.

    The client waits before retrying a throttled request. A test that met a
    429 would otherwise really sleep, and the suite would slow down one
    Retry-After at a time. Autouse, so no test can sleep by accident; ask for
    it by name to see the waits.
    """
    waits: list[float] = []

    async def record(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr("familysearch_mcp.client.pause", record)
    return waits


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail any test that opens a real connection.

    Every test is meant to run against a mocked API, and nothing enforced
    it: a tool that grew a network call where a test had no mock sent a
    real request, and the test passed on whatever came back. respx answers
    before a socket is opened, so mocked tests are unaffected.

    Checked at teardown rather than trusted to the raise, because every tool
    catches exceptions into an error envelope -- the refusal alone would be
    swallowed and the test would still pass.

    Every name lookup is refused, and so is a connection to any address that
    is not loopback. A loopback connection is allowed because Windows'
    asyncio builds its event loop's wake-up socket pair by connecting to a
    port on 127.0.0.1 that it has just opened itself; refusing that stops
    every async test before it starts. A request to FamilySearch still has
    to resolve its host name first, so it is caught.
    """
    attempts: list = []
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def loopback(address) -> bool:
        host = address[0] if isinstance(address, tuple) else address
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False  # a name or a path, never allowed

    def refuse(self, address, *args, **kwargs):
        if loopback(address):
            return real_connect(self, address, *args, **kwargs)
        attempts.append(address)
        raise RuntimeError(f"test tried to open a real connection to {address}")

    def refuse_ex(self, address, *args, **kwargs):
        if loopback(address):
            return real_connect_ex(self, address, *args, **kwargs)
        attempts.append(address)
        raise RuntimeError(f"test tried to open a real connection to {address}")

    def refuse_lookup(host, *args, **kwargs):
        attempts.append(host)
        raise RuntimeError(f"test tried to look up {host}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_ex)
    monkeypatch.setattr(socket, "getaddrinfo", refuse_lookup)
    yield attempts
    assert not attempts, f"test tried to reach the network: {attempts}"
