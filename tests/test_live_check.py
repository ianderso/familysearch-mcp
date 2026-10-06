"""The live check, run against a mocked FamilySearch that behaves as the notes say.

The script itself needs a token and the network. What can be tested without
either is the part that matters most: that each check passes when
FamilySearch answers the way ``docs/API-NOTES.md`` records, and fails when
it does not. A check that cannot fail is not checking anything.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp.client import BROWSER_UA, FULLTEXT_URL, SEARCH_URL
from tests import live_check
from tests.live_check import (
    BOGUS_TOKEN,
    COLLECTION,
    PLACE,
    SAMPLE_IMAGE,
    TREE_PERSON,
    LiveCheck,
)

WITHHELD_IMAGE = "3:1:WITHHELD-1"

API = "https://api.familysearch.org"
TOKEN = "good-token"
IMAGE = "3:1:IMAGE-1"
DIST = "https://sg30p0.familysearch.org/service/records/storage/das/v2/n/dist.jpg"


def _authorised(request: httpx.Request) -> bool:
    return request.headers.get("Authorization") == f"Bearer {TOKEN}"


def _hit(persona: str, collection: str) -> dict:
    return {
        "id": persona,
        "content": {
            "gedcomx": {
                "persons": [{"principal": True, "names": [{"nameForms": [{"fullText": "A"}]}]}],
                "sourceDescriptions": [
                    {
                        "resourceType": "http://gedcomx.org/Collection",
                        "about": "https://familysearch.org/platform/records/collections/9",
                        "titles": [{"value": collection}],
                    }
                ],
            }
        },
    }


def _search(request: httpx.Request) -> httpx.Response:
    """The website search: token and browser User-Agent, or no answer."""
    if not request.headers.get("Authorization"):
        return httpx.Response(401)
    if request.headers.get("User-Agent") != BROWSER_UA:
        return httpx.Response(403)
    code = request.url.params.get("f.recordType")
    total = 100_000 if code is None else 1_000 + 10 * int(code)
    return httpx.Response(
        200, json={"results": total, "entries": [_hit("PERSONA-1", f"Collection {code}")]}
    )


#: The weak ETag a tree person answers with, on GET and on HEAD alike.
ETAG = 'W/"139769026020400000"'


def _tree_person(request: httpx.Request) -> httpx.Response:
    """A tree person read: a weak ETag, the edit flag, attributed facts."""
    if not _authorised(request):
        return httpx.Response(401)
    body = {
        "persons": [
            {
                "id": TREE_PERSON,
                "personInfo": [{"canUserEdit": False}],
                "facts": [{"id": "c-1", "attribution": {"modified": 1513017742633}}],
            }
        ]
    }
    return httpx.Response(200, json=body, headers={"ETag": ETAG})


#: An image's storage-node name, answered as bare text.
NODE_NAME_URL = "https://sg30p0.familysearch.org/service/records/storage/das/v2/n/name"


def _fulltext(request: httpx.Request) -> httpx.Response:
    """The full-text service: token and browser User-Agent; bare words OR'd."""
    if not request.headers.get("Authorization"):
        return httpx.Response(401)
    if request.headers.get("User-Agent") != BROWSER_UA:
        return httpx.Response(403)
    words = request.url.params.get("q.text", "").split()
    total = 500 if all(w.startswith("+") for w in words) else 50_000
    entry = {
        "id": "3:1:FULLTEXT-1",
        "content": {"textDocument": "Smith sold to Jones", "highlightTexts": ["Smith"]},
    }
    return httpx.Response(200, json={"results": total, "entries": [entry]})


def _image(request: httpx.Request, *, withheld: bool = False) -> httpx.Response:
    """The image resource: links only for a good token, never a 401."""
    rels = {"records": {"href": f"{API}/platform/records/images/x/records"}}
    if _authorised(request) and not withheld:
        rels[live_check.FULL_IMAGE] = {"href": DIST}
        rels["image-name"] = {"href": NODE_NAME_URL}
    return httpx.Response(200, json={"links": rels})


@pytest.fixture
def documented_api():
    """FamilySearch as API-NOTES.md describes it."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{API}/platform/places/search").mock(
            side_effect=lambda r: httpx.Response(
                200 if "atom" in r.headers["Accept"] else 406, json={}
            )
        )
        mock.get(f"{API}/platform/places/description/{PLACE}").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.get(f"{API}/platform/records/collections").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.get(f"{API}/platform/records/collections/{COLLECTION}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "recordDescriptors": [
                        {
                            "fields": [
                                {"values": [{"labelId": "PR_NAME", "labels": [{"value": "Name"}]}]}
                            ]
                        }
                    ]
                },
            )
        )
        mock.get(f"{API}/platform/records/collections/{COLLECTION}/waypoints").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.get(f"{API}/platform/users/current").mock(
            side_effect=lambda r: httpx.Response(200 if _authorised(r) else 401, json={})
        )
        mock.get(SEARCH_URL).mock(side_effect=_search)
        mock.get(f"{API}/platform/records/personas/PERSONA-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "persons": [{"names": [{"nameForms": [{"fullText": "A"}]}]}],
                    "fields": [{"values": [{"labelId": "EVENT_PLACE", "text": "Somewhere"}]}],
                    "sourceDescriptions": [
                        {
                            "resourceType": "http://gedcomx.org/DigitalArtifact",
                            "about": f"https://familysearch.org/ark:/61903/{IMAGE}?cc=1",
                        }
                    ],
                },
            )
        )
        mock.get(url__regex=rf"^{API}/platform/records/images/[^/]+/records$").mock(
            side_effect=lambda r: httpx.Response(200 if _authorised(r) else 401, json={})
        )
        mock.get(f"{API}/platform/records/images/{IMAGE}").mock(side_effect=_image)
        mock.get(f"{API}/platform/records/images/{WITHHELD_IMAGE}").mock(
            side_effect=lambda r: _image(r, withheld=True)
        )
        mock.get(f"{API}/platform/records/images/{SAMPLE_IMAGE}").mock(side_effect=_image)
        mock.get(f"{API}/platform/tree/persons/{TREE_PERSON}").mock(side_effect=_tree_person)
        mock.head(f"{API}/platform/tree/persons/{TREE_PERSON}").mock(
            return_value=httpx.Response(200, headers={"ETag": ETAG})
        )
        mock.get(FULLTEXT_URL).mock(side_effect=_fulltext)
        mock.get(f"{API}/platform/records/images/3:1:FULLTEXT-1").mock(side_effect=_image)
        mock.get(NODE_NAME_URL).mock(
            side_effect=lambda r: httpx.Response(
                200 if _authorised(r) else 401, text="dgs:008190429.008190429_00580"
            )
        )
        yield mock


async def _run(token: str | None) -> LiveCheck:
    async with httpx.AsyncClient() as http:
        live = LiveCheck(http, token, withheld_image=WITHHELD_IMAGE)
        await live.run()
    return live


async def test_every_check_passes_against_the_documented_behaviour(documented_api):
    live = await _run(TOKEN)
    failed = [f"{o.name}: {o.detail}" for o in live.outcomes if o.status != "PASS"]
    assert failed == []
    assert not live.failed
    # Every documented claim is asked about, not only some of them.
    assert len(live.outcomes) >= 25


async def test_without_a_token_the_token_checks_are_skipped_not_failed(documented_api):
    live = await _run(None)
    statuses = {o.status for o in live.outcomes}
    assert statuses == {"PASS", "SKIP"}
    passed = {o.name for o in live.outcomes if o.status == "PASS"}
    assert "places search answers anonymously" in passed
    assert "/platform/users/current says 401 to a bad token" in passed
    # The bogus token goes only where the notes make a claim about it.
    for call in documented_api.calls:
        if call.request.headers.get("Authorization") == f"Bearer {BOGUS_TOKEN}":
            path = call.request.url.path
            assert path.endswith("/users/current") or path.startswith("/platform/records/images/")
            assert not path.endswith("/records")


async def test_a_bad_token_answered_like_a_good_one_is_a_failure(documented_api):
    """If users/current stopped saying 401, recovery on the image route breaks."""
    documented_api.get(f"{API}/platform/users/current").mock(
        return_value=httpx.Response(200, json={})
    )
    live = await _run(TOKEN)
    failed = {o.name for o in live.outcomes if o.status == "FAIL"}
    assert "/platform/users/current says 401 to a bad token" in failed
    assert live.failed


async def test_a_record_type_filter_that_stops_filtering_is_a_failure(documented_api):
    """An ignored filter is silent in the server; this is where it would show."""

    def ignores_the_filter(request: httpx.Request) -> httpx.Response:
        if not _authorised(request) or request.headers.get("User-Agent") != BROWSER_UA:
            return _search(request)
        return httpx.Response(200, json={"results": 100_000, "entries": []})

    documented_api.get(SEARCH_URL).mock(side_effect=ignores_the_filter)
    live = await _run(TOKEN)
    failed = {o.name for o in live.outcomes if o.status == "FAIL"}
    assert "f.recordType=3 (census)" in failed
    assert "every record-type code selects a different set" in failed


async def test_a_search_that_no_longer_needs_a_browser_user_agent_is_reported(documented_api):
    """Not a breakage, but the notes and the server's comment would be wrong."""
    documented_api.get(SEARCH_URL).mock(
        side_effect=lambda r: httpx.Response(
            401 if not r.headers.get("Authorization") else 200, json={"results": 1}
        )
    )
    live = await _run(TOKEN)
    failed = {o.name for o in live.outcomes if o.status == "FAIL"}
    assert "search: a token without a browser User-Agent gets 403" in failed


async def test_a_tree_person_without_an_etag_is_a_failure(documented_api):
    """compare_person reports the ETag so a stale packet can be caught."""
    documented_api.get(f"{API}/platform/tree/persons/{TREE_PERSON}").mock(
        return_value=httpx.Response(200, json={"persons": [{}]})
    )
    live = await _run(TOKEN)
    failed = {o.name for o in live.outcomes if o.status == "FAIL"}
    assert "tree person: the GET carries a weak ETag, the same as HEAD's" in failed
    assert "tree person: personInfo says whether the profile can be changed" in failed


async def test_a_full_text_search_that_requires_every_word_by_default_is_reported(
    documented_api,
):
    """The server adds + to bare words; if the service stopped ORing, the notes are wrong."""
    documented_api.get(FULLTEXT_URL).mock(
        side_effect=lambda r: (
            _fulltext(r)
            if not _authorised(r) or r.headers.get("User-Agent") != BROWSER_UA
            else httpx.Response(
                200,
                json={
                    "results": 500,
                    "entries": [
                        {"id": "3:1:X", "content": {"textDocument": "t", "highlightTexts": []}}
                    ],
                },
            )
        )
    )
    live = await _run(TOKEN)
    failed = {o.name for o in live.outcomes if o.status == "FAIL"}
    assert "full-text: bare words match any one of them, + words all of them" in failed


async def test_an_image_name_that_changed_form_is_a_failure(documented_api):
    """The film and image number are parsed out of it for citations."""
    documented_api.get(NODE_NAME_URL).mock(return_value=httpx.Response(200, text="TH-1-2-3"))
    live = await _run(TOKEN)
    failed = {o.name for o in live.outcomes if o.status == "FAIL"}
    assert "image-name: bare text dgs:{film}.{film}_{image}" in failed


def test_the_report_ends_with_a_count_of_each_status():
    outcomes = [
        live_check.Outcome("PASS", "a", "x"),
        live_check.Outcome("FAIL", "b", "y"),
        live_check.Outcome("SKIP", "c", "z"),
        live_check.Outcome("PASS", "d", "w"),
    ]
    text = live_check.report(outcomes)
    assert text.splitlines()[-1] == "2 pass, 1 fail, 1 skip"
    assert "FAIL  b\n      y" in text


def test_the_script_is_not_collected_as_a_test():
    """It talks to the live API; pytest must never pick it up by name."""
    assert not live_check.__name__.split(".")[-1].startswith("test_")


async def test_an_expired_token_falls_back_to_the_anonymous_checks(documented_api, capsys):
    """An expired token would fail every token check for a reason the API did not cause."""
    async with httpx.AsyncClient() as http:
        assert await live_check.usable_token(http, "expired", "production") is None
        assert await live_check.usable_token(http, TOKEN, "production") == TOKEN
        assert await live_check.usable_token(http, None, "production") is None
    assert "probably expired" in capsys.readouterr().out


async def test_the_withheld_image_check_is_skipped_without_an_ark(documented_api):
    """Which images are withheld depends on the account, so there is no default."""
    async with httpx.AsyncClient() as http:
        live = LiveCheck(http, TOKEN)
        await live.run()
    skipped = {o.name: o.detail for o in live.outcomes if o.status == "SKIP"}
    assert skipped == {
        "image resource: a withheld image gets no links, and the token is good": (
            "no --withheld-image given"
        )
    }


async def test_the_token_in_the_file_beats_a_stale_exported_one(
    documented_api, monkeypatch, tmp_path, capsys
):
    """Sourcing .env exports the token it held; a refresh written later does not reach the shell."""
    env_file = tmp_path / "fs.env"
    env_file.write_text(f"FS_ACCESS_TOKEN={TOKEN}\n")
    monkeypatch.setenv("FS_ENV_FILE", str(env_file))
    monkeypatch.setenv("FS_ACCESS_TOKEN", "expired-and-exported")
    assert await live_check.check(WITHHELD_IMAGE) == 0
    assert "probably expired" not in capsys.readouterr().out
