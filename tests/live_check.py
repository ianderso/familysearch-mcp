"""Re-ask FamilySearch the questions only the live API can answer.

Not part of the test suite: every test there runs mocked, and the mocks were
written from what these checks observed on one day. None of it is documented
by FamilySearch, and any of it can change without notice -- which would leave
the suite green and the server wrong. Run this by hand when that seems
possible::

    uv run python -m tests.live_check

It finds the token the way the server does: ``FS_ENV_FILE``, or the nearest
``.env`` from the working directory upward. Without one, the checks that need
no token still run and the rest are skipped. About fifty requests, all reads.

Each line says PASS, FAIL or SKIP, what was expected, and what came back. A
FAIL means ``docs/API-NOTES.md`` and the code beside the claim are out of
date. The exit status is 1 if anything failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from familysearch_mcp.client import (
    BROWSER_UA,
    CATALOG_URLS,
    CURRENT_USER_PATH,
    DAS_HOST,
    FS_JSON,
    FULLTEXT_URLS,
    GEDCOMX_ATOM_JSON,
    GEDCOMX_JSON,
    SEARCH_URLS,
)
from familysearch_mcp.config import HOSTS, load_config, token_from_env_file
from familysearch_mcp.server import _NODE_NAME, RECORD_TYPE_CODES
from familysearch_mcp.shape import (
    catalog_items,
    catalogue_collections,
    collection_field_labels,
    links,
    place_buckets,
    record_fields,
    record_persons,
    search_hits,
    source_descriptions,
    waypoints,
)

#: A collection with a published field dictionary: the 1880 US census.
COLLECTION = "1417683"

#: A place id with a long jurisdictional history: Alta California.
PLACE = "442"

#: An ordinary image, for the checks that need no token when no record was
#: read to supply one.
SAMPLE_IMAGE = "3:1:33SQ-G5LD-93NY"

#: A surname common enough to fill every record type.
SURNAME = "Smith"

#: The relation that carries the full-resolution page on an image resource.
FULL_IMAGE = "image-stream-image-dist"

#: A token FamilySearch cannot accept.
BOGUS_TOKEN = "live-check-not-a-token"

#: A long-dead public figure's tree profile, for the reads compare_person
#: relies on: George Washington, whose profile FamilySearch keeps read-only.
TREE_PERSON = "KNDX-MKG"

#: A large FamilySearch Catalog entry: one county's probate files, some three
#: thousand of them, each its own DGS, some viewable and some not.
CATALOG = "3154151"

#: A DGS number that starts with zeros: a French parish register film, from
#: catalog 104590.
ZERO_PADDED_DGS = "008126335"

#: A browsable collection of unindexed images: "Tennessee, Probate Court
#: Books, 1795-1927", and in it the waypoint for Grundy County.
BROWSABLE = "1909088"
WAYPOINT = "M6QS-12W:179638101"

#: A collection of indexed records with nothing to browse: "Iowa, County
#: Death Records, 1880-1992".
UNBROWSABLE = "2110820"


@dataclass
class Outcome:
    """One check's result."""

    status: str
    name: str
    detail: str


class LiveCheck:
    """Runs the checks and collects their outcomes.

    Parameters
    ----------
    http : httpx.AsyncClient
        Sends every request. No base URL: the API and the search service are
        on different hosts.
    token : str or None
        A real access token, or None to run only the anonymous checks.
    environment : str
        A key into :data:`familysearch_mcp.config.HOSTS`.
    withheld_image : str or None
        An image ark FamilySearch withholds from the token's account. Which
        images are withheld depends on the account, so there is no default;
        the check is skipped without one.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        token: str | None,
        environment: str = "production",
        withheld_image: str | None = None,
    ):
        self.http = http
        self.token = token
        self.api = HOSTS[environment]
        self.search_url = SEARCH_URLS[environment]
        self.fulltext_url = FULLTEXT_URLS[environment]
        self.catalog_url = CATALOG_URLS[environment]
        self.withheld_image = withheld_image
        self.outcomes: list[Outcome] = []
        #: An image ark found on a real record, for the image checks.
        self.image_ark: str | None = None

    # ------------------------------------------------------------------ #
    # Plumbing
    # ------------------------------------------------------------------ #
    async def get(
        self,
        url: str,
        *,
        accept: str = GEDCOMX_JSON,
        token: str | None = None,
        user_agent: str | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """Send one GET with exactly the headers asked for, and no others."""
        headers = {"Accept": accept}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if user_agent:
            headers["User-Agent"] = user_agent
        target = url if url.startswith("https://") else f"{self.api}{url}"
        return await self.http.get(target, headers=headers, params=params)

    def record(self, name: str, ok: bool, detail: str) -> None:
        """Record a PASS or a FAIL."""
        self.outcomes.append(Outcome("PASS" if ok else "FAIL", name, detail))

    def skip(self, name: str, why: str) -> None:
        """Record a check that could not run."""
        self.outcomes.append(Outcome("SKIP", name, why))

    async def expect_status(self, name: str, expected: int, response: httpx.Response) -> None:
        """Record whether a response carried the status the notes claim."""
        self.record(name, response.status_code == expected, _said(expected, response))

    @property
    def failed(self) -> bool:
        """bool: Whether any check failed."""
        return any(o.status == "FAIL" for o in self.outcomes)

    # ------------------------------------------------------------------ #
    # The checks, in the order API-NOTES.md makes the claims
    # ------------------------------------------------------------------ #
    async def anonymous_routes(self) -> None:
        """The catalogues answer with no Authorization header; records do not."""
        await self.expect_status(
            "places search answers anonymously",
            200,
            await self.get(
                "/platform/places/search",
                accept=GEDCOMX_ATOM_JSON,
                params={"q": 'name:"Boston"', "count": 1},
            ),
        )
        await self.expect_status(
            "places search refuses the plain GEDCOM X type",
            406,
            await self.get("/platform/places/search", params={"q": 'name:"Boston"', "count": 1}),
        )
        await self.expect_status(
            "a place description answers anonymously",
            200,
            await self.get(f"/platform/places/description/{PLACE}", accept=FS_JSON),
        )
        await self.expect_status(
            "the collection catalogue answers anonymously",
            200,
            await self.get("/platform/records/collections", params={"count": 1}),
        )
        response = await self.get(f"/platform/records/collections/{COLLECTION}", accept=FS_JSON)
        labels = collection_field_labels(_json(response))
        self.record(
            "a collection's field dictionary answers anonymously",
            response.status_code == 200 and bool(labels),
            f"HTTP {response.status_code}, {len(labels)} field labels",
        )
        response = await self.get(
            f"/platform/records/collections/{COLLECTION}/waypoints", accept=FS_JSON
        )
        self.record(
            "a collection's waypoints answer anonymously",
            response.status_code not in (401, 403),
            f"expected anything but 401 or 403, got HTTP {response.status_code}",
        )

    async def current_user(self) -> None:
        """The cheapest read that tells a live token from a dead one."""
        await self.expect_status(
            "/platform/users/current says 401 with no token",
            401,
            await self.get(CURRENT_USER_PATH),
        )
        await self.expect_status(
            "/platform/users/current says 401 to a bad token",
            401,
            await self.get(CURRENT_USER_PATH, token=BOGUS_TOKEN),
        )
        if not self.token:
            self.skip("/platform/users/current says 200 to a good token", "no token")
            return
        await self.expect_status(
            "/platform/users/current says 200 to a good token",
            200,
            await self.get(CURRENT_USER_PATH, token=self.token),
        )

    async def search_user_agent(self) -> None:
        """The search service wants the token AND a browser User-Agent."""
        params = {"q.surname": SURNAME, "count": 1}
        await self.expect_status(
            "search: a browser User-Agent without a token gets 401",
            401,
            await self.get(
                self.search_url, accept="application/json", user_agent=BROWSER_UA, params=params
            ),
        )
        if not self.token:
            for name in (
                "search: a token without a browser User-Agent gets 403",
                "search: a token with a browser User-Agent gets 200",
            ):
                self.skip(name, "no token")
            return
        await self.expect_status(
            "search: a token without a browser User-Agent gets 403",
            403,
            await self.get(
                self.search_url,
                accept="application/json",
                token=self.token,
                user_agent=f"python-httpx/{httpx.__version__}",
                params=params,
            ),
        )
        await self.expect_status(
            "search: a token with a browser User-Agent gets 200",
            200,
            await self.search(params),
        )

    async def search(self, params: dict) -> httpx.Response:
        """Search the way the server does."""
        return await self.get(
            self.search_url,
            accept="application/json",
            token=self.token,
            user_agent=BROWSER_UA,
            params=params,
        )

    async def record_types(self) -> None:
        """Each ``f.recordType`` code narrows the search, and to different sets.

        Whether a code still means the kind of record the server says it does
        is for a person to judge, from the collections printed beside it.
        """
        names = [f"f.recordType={code} ({kind})" for kind, code in RECORD_TYPE_CODES.items()]
        if not self.token:
            for name in names:
                self.skip(name, "no token")
            return
        base = {"q.surname": SURNAME, "m.queryRequireDefault": "on", "count": 20}
        unfiltered = _json(await self.search(base)).get("results") or 0
        totals = {}
        for (kind, code), name in zip(RECORD_TYPE_CODES.items(), names, strict=True):
            payload = _json(await self.search({**base, "f.recordType": str(code)}))
            total = payload.get("results") or 0
            totals[kind] = total
            titles = sorted({h.get("collection") or "?" for h in search_hits(payload)})[:3]
            self.record(
                name,
                0 < total < unfiltered,
                f"{total:,} of {unfiltered:,}; collections: {'; '.join(titles) or 'none'}",
            )
        self.record(
            "every record-type code selects a different set",
            len(set(totals.values())) == len(totals),
            ", ".join(f"{kind} {total:,}" for kind, total in totals.items()),
        )

    async def record_shape(self) -> None:
        """A persona read carries persons, record-level fields and sources."""
        name = "get_record: persons, record fields and source descriptions"
        if not self.token:
            self.skip(name, "no token")
            return
        found = search_hits(
            _json(
                await self.search({"q.surname": SURNAME, "f.collectionId": COLLECTION, "count": 1})
            )
        )
        if not found:
            self.record(name, False, f"no search hit in collection {COLLECTION} to read")
            return
        response = await self.get(f"/platform/records/personas/{found[0]['ark']}", token=self.token)
        payload = _json(response)
        people = record_persons(payload)
        fields = record_fields(payload)
        sources = source_descriptions(payload)
        artifacts = [s for s in sources if s.get("resource_type") == "DigitalArtifact"]
        if artifacts:
            about = artifacts[0].get("about") or ""
            self.image_ark = about.split("ark:/61903/")[-1].split("?")[0] or None
        self.record(
            name,
            response.status_code == 200 and bool(people) and bool(fields) and bool(sources),
            f"HTTP {response.status_code}: {len(people)} persons, {len(fields)} record "
            f"fields, {len(sources)} source descriptions, "
            f"{len(artifacts)} DigitalArtifact",
        )
        facts = [f for p in people for f in p["facts"]]
        valued = [f for f in facts if f.get("value") and f.get("original")]
        self.record(
            "get_record: a fact carries its value and what the indexer wrote",
            bool(valued),
            f"{len(valued)} of {len(facts)} facts; e.g. "
            + (
                f"{valued[0]['type']} {valued[0]['value']!r} {valued[0]['original']}"
                if valued
                else "none"
            ),
        )

    async def thin_image_document(self) -> None:
        """The image resource leaves out its image links instead of saying 401.

        The first three checks need no token and hold for any image, so they
        use a sample image when the record check found none.
        """
        ark = self.image_ark or SAMPLE_IMAGE
        path = f"/platform/records/images/{ark}"
        for name, token in (
            ("image resource: no token gets 200 with no image links", None),
            ("image resource: a bad token gets 200 with no image links", BOGUS_TOKEN),
        ):
            response = await self.get(path, token=token)
            self.record(
                name, response.status_code == 200 and not _has_image(response), _saw(response)
            )
        await self.expect_status(
            "the records indexed from an image need a token",
            401,
            await self.get(f"{path}/records", accept=FS_JSON),
        )

        name = "image resource: a good token gets the image links"
        if not self.token or not self.image_ark:
            self.skip(name, "no token" if not self.token else "the record check found no image")
        else:
            response = await self.get(path, token=self.token)
            self.record(name, response.status_code == 200 and _has_image(response), _saw(response))

        name = "image resource: a withheld image gets no links, and the token is good"
        if not self.token or not self.withheld_image:
            self.skip(name, "no token" if not self.token else "no --withheld-image given")
            return
        response = await self.get(
            f"/platform/records/images/{self.withheld_image}", token=self.token
        )
        current = await self.get(CURRENT_USER_PATH, token=self.token)
        self.record(
            name,
            response.status_code == 200 and not _has_image(response) and current.status_code == 200,
            f"{self.withheld_image}: {_saw(response)}; users/current HTTP {current.status_code}",
        )

    async def tree_person(self) -> None:
        """What compare_person reads off a tree profile.

        A weak ETag on the GET itself (so no HEAD is needed) that matches the
        HEAD's; a ``personInfo.canUserEdit`` flag; and conclusions that carry
        their id and an attribution with a modified time.
        """
        names = (
            "tree person: the GET carries a weak ETag, the same as HEAD's",
            "tree person: personInfo says whether the profile can be changed",
            "tree person: each fact carries its conclusion id and when it changed",
        )
        if not self.token:
            for name in names:
                self.skip(name, "no token")
            return
        path = f"/platform/tree/persons/{TREE_PERSON}"
        got = await self.get(path, token=self.token)
        head = await self.http.head(
            f"{self.api}{path}",
            headers={"Accept": GEDCOMX_JSON, "Authorization": f"Bearer {self.token}"},
        )
        etag = got.headers.get("ETag") or ""
        self.record(
            names[0],
            got.status_code == 200 and etag.startswith("W/") and etag == head.headers.get("ETag"),
            f"GET HTTP {got.status_code} ETag {etag or 'absent'}; HEAD HTTP "
            f"{head.status_code} ETag {head.headers.get('ETag') or 'absent'}",
        )
        person = (_json(got).get("persons") or [{}])[0]
        info = (person.get("personInfo") or [{}])[0]
        self.record(
            names[1],
            isinstance(info.get("canUserEdit"), bool),
            f"canUserEdit = {info.get('canUserEdit')!r}",
        )
        facts = person.get("facts") or []
        attributed = [
            f for f in facts if f.get("id") and (f.get("attribution") or {}).get("modified")
        ]
        self.record(
            names[2],
            bool(facts) and len(attributed) == len(facts),
            f"{len(attributed)} of {len(facts)} facts",
        )

    async def fulltext(self) -> None:
        """The full-text service: the same footing as record search, and OR by default.

        Also reads the first hit's shape, which ``shape.fulltext_hits``
        relies on: an image ark, the page text and the bare matched terms.
        """
        names = (
            "full-text: a token without a browser User-Agent gets 403",
            "full-text: a token with a browser User-Agent gets pages with their text",
            "full-text: bare words match any one of them, + words all of them",
        )
        params = {"q.text": f"+{SURNAME}", "m.queryRequireDefault": "on", "count": 1}
        await self.expect_status(
            "full-text: a browser User-Agent without a token gets 401",
            401,
            await self.get(
                self.fulltext_url, accept="application/json", user_agent=BROWSER_UA, params=params
            ),
        )
        if not self.token:
            for name in names:
                self.skip(name, "no token")
            return
        await self.expect_status(
            names[0],
            403,
            await self.get(
                self.fulltext_url,
                accept="application/json",
                token=self.token,
                user_agent=f"python-httpx/{httpx.__version__}",
                params=params,
            ),
        )
        response = await self.fulltext_get(params)
        entry = (_json(response).get("entries") or [{}])[0]
        content = entry.get("content") or {}
        self.record(
            names[1],
            response.status_code == 200
            and str(entry.get("id", "")).startswith("3:1:")
            and bool(content.get("textDocument"))
            and isinstance(content.get("highlightTexts"), list),
            f"HTTP {response.status_code}; first entry {entry.get('id')!r}, "
            f"{len(content.get('textDocument') or '')} characters of text",
        )
        if not self.image_ark and str(entry.get("id", "")).startswith("3:1:"):
            self.image_ark = entry["id"]
        bare = _json(await self.fulltext_get({**params, "q.text": f"{SURNAME} Jones"}))
        both = _json(await self.fulltext_get({**params, "q.text": f"+{SURNAME} +Jones"}))
        self.record(
            names[2],
            (bare.get("results") or 0) > (both.get("results") or 0) > 0,
            f"'{SURNAME} Jones' {bare.get('results') or 0:,}; "
            f"'+{SURNAME} +Jones' {both.get('results') or 0:,}",
        )

    async def fulltext_get(self, params: dict) -> httpx.Response:
        """Search the page text the way the server does."""
        return await self.get(
            self.fulltext_url,
            accept="application/json",
            token=self.token,
            user_agent=BROWSER_UA,
            params=params,
        )

    async def image_name(self) -> None:
        """An image's ``image-name`` relation answers bare text naming its film and image."""
        name = "image-name: bare text dgs:{film}.{film}_{image}"
        if not self.token or not self.image_ark:
            self.skip(name, "no token" if not self.token else "no image found to ask about")
            return
        resource = await self.get(f"/platform/records/images/{self.image_ark}", token=self.token)
        href = links(_json(resource)).get("image-name")
        if not href:
            self.record(name, False, f"{self.image_ark}: no image-name relation")
            return
        response = await self.get(href, accept="application/json", token=self.token)
        text = response.text.strip()
        self.record(
            name,
            response.status_code == 200 and _NODE_NAME.fullmatch(text) is not None,
            f"HTTP {response.status_code}: {text[:60]!r}",
        )

    async def catalog(self) -> None:
        """The catalog entry service, and the storage host's answer for a DGS.

        The service stands where record search does. The entry's shape is
        what ``shape.catalog_items`` reads. The storage host gives a film's
        image count to a token that may view it, with no browser
        User-Agent, 403 to one that may not, and 404 to a DGS number
        without its leading zeros.
        """
        names = (
            "catalog: a token without a browser User-Agent gets 403",
            "catalog: a token with a browser User-Agent gets the entry and its films",
            "catalog: a viewable DGS answers its image count on the storage host",
            "catalog: a DGS this account may not view gets 403 there",
            "catalog: a DGS without its leading zeros gets 404 there",
        )
        url = f"{self.catalog_url}/{CATALOG}"
        await self.expect_status(
            "catalog: a browser User-Agent without a token gets 401",
            401,
            await self.get(url, accept="application/json", user_agent=BROWSER_UA),
        )
        if not self.token:
            for name in names:
                self.skip(name, "no token")
            return
        await self.expect_status(
            names[0],
            403,
            await self.get(
                url,
                accept="application/json",
                token=self.token,
                user_agent=f"python-httpx/{httpx.__version__}",
            ),
        )
        response = await self.get(
            url, accept="application/json", token=self.token, user_agent=BROWSER_UA
        )
        source = _json(response).get("source")
        items = catalog_items(source) if isinstance(source, dict) else []
        self.record(
            names[1],
            response.status_code == 200
            and bool((source or {}).get("display_title"))
            and bool(items)
            and all(i["dgs"] and i["description"] for i in items),
            f"HTTP {response.status_code}; {len(items):,} films",
        )
        rights = {i["dgs"]: i.get("catalog_rights") for i in items if i["dgs"]}
        viewable = next((d for d, r in rights.items() if r == "UNREST"), None)
        group = await self.image_group(viewable or ZERO_PADDED_DGS)
        count = _json(group).get("childCount")
        self.record(
            names[2],
            group.status_code == 200 and isinstance(count, int) and count > 0,
            f"dgs:{viewable or ZERO_PADDED_DGS} HTTP {group.status_code}, childCount {count!r}",
        )
        restricted = next((d for d, r in rights.items() if r == "NO_ACC"), None)
        if restricted:
            await self.expect_status(names[3], 403, await self.image_group(restricted))
        else:
            self.skip(names[3], f"catalog {CATALOG} lists no film marked NO_ACC")
        unpadded = await self.image_group(ZERO_PADDED_DGS.lstrip("0"))
        padded = await self.image_group(ZERO_PADDED_DGS)
        self.record(
            names[4],
            unpadded.status_code == 404 and padded.status_code in (200, 403),
            f"dgs:{ZERO_PADDED_DGS.lstrip('0')} HTTP {unpadded.status_code}; "
            f"dgs:{ZERO_PADDED_DGS} HTTP {padded.status_code}",
        )

    async def image_group(self, dgs: str) -> httpx.Response:
        """Ask the storage host about one image group, as the server does."""
        return await self.get(f"{DAS_HOST}/dgs:{dgs}", accept="application/json", token=self.token)

    async def waypoint_routes(self) -> None:
        """A waypoint opens only with its collection; an unbrowsable collection has no link."""
        path = f"/platform/records/waypoints/{WAYPOINT}"
        await self.expect_status(
            "waypoints: a waypoint without its collection gets 400",
            400,
            await self.get(path, accept=FS_JSON),
        )
        response = await self.get(path, accept=FS_JSON, params={"cc": BROWSABLE})
        node = waypoints(_json(response))
        ids = [c.get("waypoint_id") or "" for c in node["children"]]
        self.record(
            "waypoints: with its collection, it lists children by waypoint id",
            response.status_code == 200 and bool(ids) and all(":" in i for i in ids),
            f"HTTP {response.status_code}: {node['title']!r}, {len(ids)} children, "
            f"first {ids[0] if ids else None!r}",
        )
        described = _json(await self.get(f"/platform/records/collections/{UNBROWSABLE}"))
        listed = await self.get(f"/platform/records/collections/{UNBROWSABLE}/waypoints")
        self.record(
            "waypoints: a collection with nothing to browse has no waypoints link, and 404s",
            "waypoints" not in (described.get("links") or {}) and listed.status_code == 404,
            f"links {sorted(described.get('links') or {})}; waypoints HTTP {listed.status_code}",
        )

    async def catalogue_windows(self) -> None:
        """The catalogue pages in windows of 100 slots, none repeating another."""
        path = "/platform/records/collections"

        async def ids(**params) -> list[str]:
            return [
                c["id"] for c in catalogue_collections(_json(await self.get(path, params=params)))
            ]

        first = await ids(count=100)
        larger = await ids(count=200)
        following = await ids(count=100, start=100)
        self.record(
            "catalogue: count above 100 returns the same window as 100",
            bool(first) and larger == first,
            f"count=100 gave {len(first)}, count=200 gave {len(larger)}",
        )
        self.record(
            "catalogue: the window at start=100 repeats nothing from start=0",
            bool(following) and not set(first) & set(following),
            f"{len(following)} collections, {len(set(first) & set(following))} repeated",
        )

    async def search_criteria(self) -> None:
        """How a year and a place are applied, which search_records reports."""
        names = (
            "search: a year without exact matches 5 years either side",
            "search: exact on a year means that year, on a record giving one",
            "search: an exact place matches its namesakes, and the county filter holds it",
            "search: a page past the first answers from the offset asked",
        )
        if not self.token:
            for name in names:
                self.skip(name, "no token")
            return
        base = {"q.givenName": "John", "q.surname": SURNAME, "m.queryRequireDefault": "on"}

        async def total(**params) -> int:
            return _json(await self.search({**base, **params, "count": 1})).get("results") or 0

        dated = await total(**{"q.birthLikeDate": "1850", "f.birthLikeDate0": "1800"})
        window = await total(
            **{"q.birthLikeDate.from": "1845", "q.birthLikeDate.to": "1855"},
            **{"q.birthLikeDate.exact": "on"},
        )
        self.record(
            names[0],
            dated > 0 and dated == window,
            f"born 1850 and giving a year {dated:,}; born 1845-1855 exactly {window:,}",
        )
        loose = await total(**{"q.birthLikeDate": "1850"})
        exact = await total(**{"q.birthLikeDate": "1850", "q.birthLikeDate.exact": "on"})
        that_year = await total(
            **{"q.birthLikeDate.from": "1850", "q.birthLikeDate.to": "1850"},
            **{"q.birthLikeDate.exact": "on"},
        )
        self.record(
            names[1],
            0 < exact == that_year < loose,
            f"exact {exact:,}; 1850-1850 exactly {that_year:,}; without exact {loose:,}",
        )
        place = {
            "q.surname": SURNAME,
            "q.residencePlace": "White, Arkansas",
            "q.residencePlace.exact": "on",
            "m.queryRequireDefault": "on",
            "c.residencePlace1": "on",
            "c.residencePlace2": "on",
            "count": 1,
        }
        named = _json(await self.search(place))
        county = [
            r
            for r in place_buckets(named, "residencePlace")
            if r["names"][1:] == ["Arkansas", "White"]
        ]
        held = _json(await self.search({**place, **dict([county[0]["filter"]])})) if county else {}
        self.record(
            names[2],
            bool(county)
            and 0 < (held.get("results") or 0) < (named.get("results") or 0)
            and held.get("results") == county[0]["count"],
            f"by its words {named.get('results') or 0:,}; White County bucket "
            f"{county[0]['count'] if county else 'absent'}; filtered {held.get('results')}",
        )
        paged = _json(await self.search({"q.surname": SURNAME, "count": 1, "offset": 20}))
        self.record(names[3], paged.get("index") == 20, f"index {paged.get('index')!r}")

    async def run(self) -> None:
        """Run every check. The record read supplies the image checks' ark."""
        steps: list[Callable[[], Awaitable[None]]] = [
            self.anonymous_routes,
            self.waypoint_routes,
            self.catalogue_windows,
            self.current_user,
            self.search_user_agent,
            self.record_types,
            self.search_criteria,
            self.record_shape,
            self.thin_image_document,
            self.tree_person,
            self.fulltext,
            self.image_name,
            self.catalog,
        ]
        for step in steps:
            await step()


def _json(response: httpx.Response) -> dict:
    """Decode a body, or an empty dict for one that is not a JSON object."""
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _has_image(response: httpx.Response) -> bool:
    """Whether an image resource carried the full-resolution page."""
    return FULL_IMAGE in links(_json(response))


def _saw(response: httpx.Response) -> str:
    """Describe an image resource's answer."""
    return (
        f"HTTP {response.status_code}, image links "
        f"{'present' if _has_image(response) else 'absent'}"
    )


def _said(expected: int, response: httpx.Response) -> str:
    """Describe what came back against what was expected."""
    return f"expected HTTP {expected}, got {response.status_code}"


def report(outcomes: list[Outcome]) -> str:
    """Format the outcomes, one per line, then a count of each status."""
    lines = [f"{o.status}  {o.name}\n      {o.detail}" for o in outcomes]
    counts = {s: sum(o.status == s for o in outcomes) for s in ("PASS", "FAIL", "SKIP")}
    lines.append(", ".join(f"{n} {s.lower()}" for s, n in counts.items()))
    return "\n".join(lines)


async def usable_token(http: httpx.AsyncClient, token: str | None, environment: str) -> str | None:
    """Return ``token`` if FamilySearch still accepts it, otherwise None.

    A token lasts about an hour. An expired one would turn every check that
    needs a token into a FAIL that says nothing about the API, so it is
    caught here and the run falls back to the checks that need none.
    """
    if not token:
        print("No FS_ACCESS_TOKEN found: running only the checks that need none.\n")
        return None
    response = await http.get(
        f"{HOSTS[environment]}{CURRENT_USER_PATH}",
        headers={"Accept": GEDCOMX_JSON, "Authorization": f"Bearer {token}"},
    )
    if response.status_code == 401:
        print(
            "FamilySearch rejected FS_ACCESS_TOKEN; it has probably expired. Refresh "
            "it and run again. Running only the checks that need none.\n"
        )
        return None
    return token


async def check(withheld_image: str | None = None) -> int:
    """Run the checks against the configured environment. Returns an exit status."""
    config = load_config()
    # The file first. Sourcing an env file exports the token it held then, and
    # a refresh written to the file afterwards does not reach that shell: the
    # exported, expired token would win. The server recovers from that on its
    # first 401 by re-reading the file; this reads the file to begin with.
    fresh = token_from_env_file(config.env_file) if config.env_file else None
    async with httpx.AsyncClient(timeout=config.timeout) as http:
        token = await usable_token(http, fresh or config.access_token, config.environment)
        live = LiveCheck(http, token, config.environment, withheld_image)
        await live.run()
    print(report(live.outcomes))
    return 1 if live.failed else 0


def main() -> int:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--withheld-image",
        metavar="ARK",
        help="an image ark withheld from your account, to check that a withheld "
        "image is told apart from a bad token; skipped without one",
    )
    args = parser.parse_args()
    # One line per request would bury the report.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return asyncio.run(check(args.withheld_image))


if __name__ == "__main__":
    raise SystemExit(main())
