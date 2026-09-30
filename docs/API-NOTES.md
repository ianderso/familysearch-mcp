# API notes

FamilySearch's Historical Records API is **no longer publicly documented**.
The old reference pages under `www.familysearch.org/developers/docs/api/records/`
return 404 on every locale and host variant, the replacement site publishes no
Records reference at all, and the Wayback Machine has almost nothing because
those pages were always sign-in gated.

What follows was established from the live API, FamilySearch's own open-source
code, and archived fragments. Probes marked *verified live* were run against
`api.familysearch.org` on 2026-09-23 unless another date is given.

## Checking it again

None of this is promised by FamilySearch, and any of it can change without
notice. The test suite cannot notice, because its mocks were written from
these observations. `tests/live_check.py` asks the live API again:

```bash
uv run python -m tests.live_check
```

It reads the token the way the server does, runs the anonymous checks
without one, and skips the rest when there is none or FamilySearch rejects
it. A FAIL names the claim below that no longer holds.

Last run 2026-09-29, without a usable token: every anonymous claim held —
the routes in the next section, the 406 for the wrong Accept type, the
current-user 401 for no token and for a bad one, the search service's 401
without a token, and the thin image document for no token and for a bad
one. The token checks were last confirmed by hand on 2026-09-28.

## What answers without a token

Verified live, with no `Authorization` header at all:

| Route | Result |
| --- | --- |
| `GET /platform/places/search` | 200 — **but 406** with `application/x-gedcomx-v1+json`. It is a feed and wants `application/x-gedcomx-atom+json`. |
| `GET /platform/places/description/{id}` | 200 |
| `GET /platform/records/collections` | 200 |
| `GET /platform/records/collections/{id}` | 200, with the field dictionary |
| `GET /platform/records/collections/{id}/waypoints` | 200 |
| `GET /platform/records/waypoints/{id}` | 200 |
| `GET /platform/places/description/{id}/children` | 200 |

The anonymous boundary is **data about people**, not the records API as a
whole. Catalogues — places, collections, field labels, and the waypoint tree
that browses a film's structure — are open. Records, personas and images are
not: `GET /platform/records/images/{ark}/records` returns 401 without a
token.

That makes browsing genuinely useful to an unconfigured install. Indexing is
incomplete across most of the archive, so a record no search finds may still
sit on an image reachable by walking collection → volume → film → page.

## The field dictionary

An indexed record labels its values with per-collection codes: `PR_NAME`,
`EVENT_PLACE`, `PR_FTHR_NAME`. The decoder is
`recordDescriptors[].fields[].values[]`, each carrying a `labelId` and a
`labels[]` array. Collection 1417683 (1880 US census) publishes **116** of
them, including `PR_NAME` → "Name" and `PR_FTHR_NAME` → "Father's Name".

Because the collection route is anonymous, record output can be made readable
with no credentials — which is what `get_collection_fields` does.

## Search takes separate `q.*` parameters

Not a single `q=` string. The format is
`category.term[.modifier][.cardinality]=value`, where the category is `q.` for
query terms, `f.` for exact-match filters and `c.` for facets. `count` and
`offset` take no category.

The single-`q`-string form (`q=givenName:John surname:Smith`) is the older
GEDCOM X RS convention. It survives in FamilySearch's own Java and JavaScript
SDKs and still drives `/platform/places/search`, but it is not how the records
search works.

- `count` defaults to 20, maximum 100.
- `offset` is 0-based, maximum 4999. The search returns only the first 5,000
  results; a larger offset is a bad request.

Verified query terms: `q.givenName`, `q.surname`, `q.sex`, `q.birthLikeDate`,
`q.birthLikePlace`, `q.deathLikeDate`, `q.deathLikePlace`,
`q.marriageLikeDate`, `q.marriageLikePlace`, `q.residenceDate`,
`q.residencePlace`, `q.spouseGivenName`, `q.spouseSurname`,
`q.fatherGivenName`, `q.fatherSurname`, `q.motherGivenName`,
`q.motherSurname`, `q.miscKeyword`. Filter: `f.collectionId`.

Modifiers are `.exact`, `.require`, `.from`, `.to`, each taking the value
`on`. Dates are `+YYYY` form and only the year is honoured.

## `f.recordType` codes, verified

A name is rejected with HTTP 400; the parameter takes an integer. Every code
was confirmed on 2026-09-23 by filtering on it and reading the collections
that came back:

| code | kind | a collection it returned |
| --- | --- | --- |
| 0 | birth | England, Births and Christenings, 1538-1975 |
| 1 | marriage | England and Wales, Marriage Registration Index |
| 2 | death | United States, Social Security Death Index |
| 3 | census | United States, Residence Database, 1970-2024 |
| 4 | immigration | New York, County Naturalization Records |
| 5 | military | United States, Enlisted and Officer Muster Rolls |
| 6 | probate | Australia, Victoria, Wills, Probate and Administration |
| 7 | other | Massachusetts, Suffolk, Boston Tax Records |

This table was briefly removed from the server as unreliable, because
filtering by it returned nothing. That was the old endpoint: its index held
only immigration records, so every code but 4 was legitimately empty. The
mapping was right all along, and the endpoint was the problem.

## Accept headers differ by resource

| Resource | Accept |
| --- | --- |
| Record and persona reads | `application/x-gedcomx-v1+json` |
| Matches and change histories, and the API host's own search | `application/x-gedcomx-atom+json` |
| The website's search service (the one the server uses) | `application/json` |
| Places search | `application/x-gedcomx-atom+json` (v1 gets 406) |
| Place descriptions, collections | `application/json` works |

Verified live: `GET /platform/records/personas?q.surname=Smith` returns **406**
with the v1 type and **401** with the Atom type. The 406-before-401 ordering
is what proves the route exists and which type it wants.

## Ark prefixes

| Prefix | Means | Route |
| --- | --- | --- |
| `1:1:` | persona — one person on one record | `/platform/records/personas/{id}` |
| `1:2:` | record — the whole entry | `/platform/records/records/{id}` |
| `3:1:` | image / digital artifact | `/platform/records/images/{ark}` |
| `4:1:` | Family Tree person | `/platform/tree/persons/{id}` |

`/platform/records/{id}` does not exist. Note the doubled segment in
`records/records/`.

## Image resolution

There is no `/records/{id}/image`. An image is reached through the record's
`sourceDescriptions`: the Record description points at a `DigitalArtifact`
description via `sources[].description`, and that carries the `3:1:` ark. On
an image ark, `?cc=` is the collection context and `?wc=` the waypoint
context.

The reverse direction is `GET /platform/records/images/{ark}/records`.

DGS and microfilm numbers have no field of their own in the GEDCOM X
structure. They appear in three places: as free text inside the source
description's `citations[].value`; as the artifact folder id under
`/platform/artifacts/folders/{dgs}`, which requires a token; and, in the
collections that index them, as the labelled index values
`FS_DIGITAL_FILM_NBR` and `FS_IMAGE_NBR` (next section), which is where
`get_record_image` reads them from.

## Verified with a token

Observed on 2026-09-23 against a real account, reading real records:

- **Search** returns a GEDCOM X Atom feed with `results`, `index`, `links`
  and `entries[]`. Each entry carries `id`, `score`, `confidence`, `title`,
  `links`, `matchInfo` and `content.gedcomx`. The entry `id` is the **bare
  persona id** (`KX42-QVQ`), not the full ark that archived examples show.
- **A persona read** returns `attribution`, `description`, `fields`, `id`,
  `lang`, `links`, `persons`, `sourceDescriptions`. Document-level `fields[]`
  carry the record-wide index columns; each person also has its own
  `fields[]`, and `person.links` holds `persona` and `record` rels.
- **Image resolution through `sourceDescriptions` is confirmed.** A persona
  read carried five descriptions: the `Record` (a `1:2:` ark), the
  `Collection`, a `DigitalArtifact` (`3:1:33SQ-G5LD-93NY`, `image/jpeg`), and
  a `Person`. The indexed fields alongside it gave
  `FS_DIGITAL_FILM_NBR` = `004893581` and `FS_IMAGE_NBR` = `213`.
- `f.collectionId` works: scoping a name search to collection 1916078
  narrowed 114,978 matches to 1,526.

## Resolving a record to a readable image

Verified end to end on 2026-09-23, from a search hit to a 3840x4312 page scan.

**A record read carries no image links.** That was the wrong conclusion drawn
from an earlier probe. The links exist on the *image resource*, which is a
separate call:

1. Read the persona or record. Its `sourceDescriptions` include one with
   `resourceType: DigitalArtifact` whose `about` is a `3:1:` ark.
2. `GET /platform/records/images/{3:1: ark}` — **this** returns the image
   relations, with an ordinary account token:

   | Relation | Gives |
   | --- | --- |
   | `image-node` | The DAS storage node, e.g. `.../das/v2/TH-1942-22242-30207-51` |
   | `image-stream-image-dist` | `dist.jpg`, the full-resolution page |
   | `image-stream-image-thumb_16/32/64/128/p200` | Thumbnails |
   | `image-deepzoom` | `image.xml` for tiled viewing |
   | `image-name`, `image-parents`, `image-permission` | Node metadata |
   | `next`, `prev` | Neighbouring pages in the film |
   | `records` | The records indexed from this image |

3. Fetch the image URL. **It 302s to a presigned S3 URL**, and carrying the
   bearer header across that hop fails:

   ```
   400 InvalidArgument
   Only one auth mechanism allowed; only the X-Amz-Algorithm query parameter,
   Signature query string parameter or the Authorization header should be
   specified
   ```

   The signature in the query string is already the credential. Send the
   bearer on the first hop and drop it on the second — which is what
   `client.fetch_binary` does, and what `test_the_bearer_header_is_dropped_on_
   the_storage_redirect` pins.

Thumbnails answer directly with no redirect, so the fetch must not require
one. No browser or user-agent spoofing is needed anywhere in this chain; a
bearer token is sufficient.

### A missing image link has three causes, and the resource never says 401

Verified live on 2026-09-28. `GET /platform/records/images/{ark}` answers
**200 with the image relations left out** (navigation only: `records`,
`self`, sometimes `next`/`prev`) in three different situations:

| Situation | Image resource | `/platform/users/current` |
| --- | --- | --- |
| No token | 200, thin | 401 |
| Expired or invalid token | 200, thin | 401 |
| Valid token, image withheld from the account | 200, thin | 200 |

The first two look identical, and neither produces a 401, so the ordinary
"re-read the env file on a 401" recovery never runs on this route. The
current-user read tells them apart, and asking it through the client brings
that recovery with it. `get_image_links` does this only when the answer came
back thin and a token was sent. Which images are withheld depends on the
account, so the live check asks about one only when given its ark
(`--withheld-image`).

The image URLs themselves (`sg30p0.familysearch.org/.../dist.jpg`) do say
401 to a missing or invalid token, and 302 to the presigned URL for a good
one. `download_image` recovers there the ordinary way.

The token for these checks was obtained outside the server, which has no
login path by design.

## Use the website's search service, not /platform/records/personas

**The record search on the API host answers from a partial index.** Verified
live 2026-09-23: a required-name search for "John Smith" returned 53,043
hits that were, without exception, passenger and crew lists. The
`c.recordType` facet put every one under a single code, and
`f.collectionId` for a collection outside that index was silently dropped
rather than refused, so a census search returned the unfiltered total and
looked like it had worked.

The search the FamilySearch website itself uses reaches the whole
catalogue:

```
https://www.familysearch.org/service/search/hr/v2/personas
```

Same query, same account, same bearer token:

| | /platform/records/personas | website service |
| --- | --- | --- |
| John Smith, required | 53,043 | 5,835,812 |
| scoped to the 1880 census | 53,043 (filter dropped) | 51,272 |
| record-type facet | one code | all eight |

It takes **the same bearer token**, but only with a browser `User-Agent`.
The token alone gets 403; the User-Agent alone gets 401. It speaks
`application/json` rather than GEDCOM X Atom.

The symptom of using the platform endpoint is "search only returns
immigration records", which is easy to mistake for a limit on what the
account may see.

The sandbox has the same service at
`https://integration.familysearch.org/service/search/hr/v2/personas`, and the
server uses it when `FS_ENVIRONMENT=integration`. Checked 2026-09-29 without a
token: it answers 401 to a browser User-Agent, exactly as production does,
where a host without the service would not answer at all. It has not been
checked with a sandbox token.

## A search term is a scoring hint, not a filter

Adding a criterion does not narrow a search unless it is marked required.
Verified live: a name search returned 114,978, and adding `q.deathLikeDate`,
`q.deathLikePlace` or `q.birthLikeDate` left it at exactly 114,978 — the
terms only reordered the results.

Marking them changes everything:

| Query | Results |
| --- | --- |
| given + surname | 114,978 |
| same, required | 4,720 |
| plus death year, required | 66 |

`m.queryRequireDefault=on` is the global switch and this server sends it by
default. `loose=True` turns it off when ranking by similarity is what you
want. A filter that silently does not filter is the surprising behaviour,
which is why the safe reading is the default.

## The catalogue has no search endpoint

`/platform/records/collections` pages at roughly ninety entries with no
query parameter, so a title search means holding the whole list: 3,443
collections across about 38 pages, around ninety seconds. It is cached in
memory and on disk for thirty days; `search_collections(refresh=True)`
rebuilds it.

## Throttling

FamilySearch answers 429 when an application sends too much, with a
`Retry-After` header in seconds. The client waits out a delay of up to 15
seconds and retries once; a longer one is handed back to the caller as
`rate_limited`, because a tool call that blocks for minutes looks hung. No
429 has been captured live in this project's use, so the header's form is
taken from the HTTP standard: a date-form `Retry-After` is ignored rather
than parsed, and a missing one gets a two-second wait.
