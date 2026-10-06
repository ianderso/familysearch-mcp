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

Last run 2026-10-06, later that day, with a fresh token: 50 checks passed,
none failed and one was skipped, including the ten added for waypoints, the
catalogue's windows, how search applies a year and a place, and a record's
fact values. Earlier on 2026-10-06, 40 passed, including the six added for
the FamilySearch Catalog. On 2026-10-05, after
`compare_person` and full-text search were combined, 34 passed and none
failed; on 2026-09-29, 26.
Every claim below held — the anonymous routes, the 406 for the wrong Accept
type, the current-user 401 and 200, the search service's 401 without a token
and 403 without a browser User-Agent, all eight record-type codes narrowing
to different sets, the record read's shape, and the image resource's thin
document for no token and for a bad one. The withheld-image check was
skipped: it needs an ark withheld from the account running it.

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
- `offset` is 0-based. The API host's search documented a maximum of 4,999;
  the website's is not dependable that far (see "Paging the website search"
  below).

Verified query terms: `q.givenName`, `q.surname`, `q.sex`, `q.birthLikeDate`,
`q.birthLikePlace`, `q.deathLikeDate`, `q.deathLikePlace`,
`q.marriageLikeDate`, `q.marriageLikePlace`, `q.residenceDate`,
`q.residencePlace`, `q.spouseGivenName`, `q.spouseSurname`,
`q.fatherGivenName`, `q.fatherSurname`, `q.motherGivenName`,
`q.motherSurname`, `q.miscKeyword`. Filter: `f.collectionId`.

Modifiers are `.exact`, `.require`, `.from`, `.to`. `.exact` and `.require`
take the value `on`; `.from` and `.to` take a year. Only the year of a date
is honoured. What each modifier actually does is measured in "How a search
criterion is applied" below.

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

## Full-text search: the website's service over machine-read page text

FamilySearch has run handwriting recognition over a large part of its page
images, heaviest on US deeds, wills, probate and court records, and the
website searches the result. Its route is undocumented. It was first
described in the open-source
[PioneerAIAcademy/cowork-genealogy](https://github.com/PioneerAIAcademy/cowork-genealogy)
(`docs/specs/fulltext-search-tool-spec.md`). Everything below was verified
live on 2026-10-05 unless it says otherwise.

```
https://www.familysearch.org/service/search/fulltext/search
```

- **The same footing as record search.** It takes the API's bearer token,
  but only with a browser `User-Agent`: the token alone gets 403 (a firewall
  page) and the User-Agent alone gets 401. Same token, same header, no
  cookie. The sandbox host answers 401 to a browser User-Agent with no
  token; it has not been tried with a sandbox token.
- **Bare words are OR'd.** `q.text=Hannah Ball` matched 19,707,871 pages,
  with or without `m.queryRequireDefault=on`. `+Hannah +Ball` matched
  270,195. So `fulltext_search` adds `+` to every bare word and phrase,
  unless the query uses AND, OR or NOT. A quoted phrase works
  (`"Hannah Ball"`), as do `-word` and a trailing `*`.
- **The response** is `results` (the total), `index`, `links.next` while
  there are more, `facets`, and `entries[]`. Each entry is one page image:
  - `id`, a `3:1:` image ark, which `get_image_links` resolves like any other;
  - `sourceUrl`;
  - `collectionId` and `collectionTitle`;
  - `content`, holding:
    - `title` ("Fauquier, Virginia, United States Deed Book 1821"),
      `recordType`, `recordPlace` and `recordDate`;
    - `textDocument`, the whole page's text, 9,000 to 21,000 characters in
      the pages seen;
    - `entities`, typed NAME, PLACE and DATE;
    - `highlightTexts`, the matched terms, bare.

  There is no relevance score and no snippet; the server cuts its own
  passages out of `textDocument` around the matched terms.
- **Narrowing.**
  - `q.fullName` matches the recognised names only.
  - `q.groupName` takes an image group (DGS film) number and searches that
    volume: `+Ball` in film 008190429 gave 70 pages.
  - `f.collectionId` takes both kinds of collection id seen in results:
    numeric (`3158846`) and the newer alphanumeric (`M9J1-S4M`).
  - With `m.defaultFacets=on` the response carries facets by Collection,
    Year, Place and Record Type. Each bucket's `params` is the filter that
    selects it, e.g. `c.recordPlace1=on&f.recordPlace0=10` for the United
    States, or `f.recordTypeId0=122797` for Legal Records. Places and record
    types are named only by these ids.
- **The year filter is a century.** `f.recordYear0=1800` selects the 1800s.
  `f.recordYear1=1820` was ignored (the total did not change), and asking
  for a facet level below (`c.recordYear2=on`) is a 400: "Unable to map
  supplied value=record_year2 to count term". So `fulltext_search` takes no
  year range. Its `filters` parameter accepts the facet strings above and
  nothing else.
- **Place filters match the collection, not the page.** Reported by
  cowork-genealogy from measurement on 2026-09-10; not re-checked here.
- **The page's film and image number.** The image resource's `image-name`
  relation answers bare text with an `application/json` content type, e.g.
  `dgs:008190429.008190429_00580`: film 008190429, image 580. A citation to
  the page needs both, so `get_image_links` now reports them.

`tests/live_check.py` re-asks the 401, the 403, the shape, the OR, and the
image name.

## The FamilySearch Catalog: the website's entry service

The Catalog is the library's catalogue of films and books, not the list of
record collections that `search_collections` reads. Its route is
undocumented; it was found on 2026-10-05 by reading the scripts the
website's catalog page (`/search/catalog/{id}`) loads, and everything below
was verified live that day.

```
https://www.familysearch.org/service/search/catalog/item/{catalog_id}
```

- **The same footing as record search.** The token with a browser
  `User-Agent` gets 200; the token alone 403 (the firewall page); the
  User-Agent alone 401. An unknown id gets 404 with no body. The sandbox
  host answers 401 to a browser User-Agent with no token; it has not been
  tried with a sandbox token.
- **A second route exists.** Behind a feature flag the page reads
  `/search/orchestration/catalog/{id}` instead. It answered 200 with the
  same entry and a few more fields (each film's `volume` and
  `inclusive_dates` split out of its text) at twice the size. The server
  uses the `/service/search/` route, beside the other two.
- **The response** is `{"source": {...}}`:
  - `display_title`, `title`, `inclusive_dates`, `format` and
    `format_addendum`, `available_online` (`Y`);
  - `author[]`, each with `display_text` and a `type` such as `Main Author`
    or `Repository`;
  - `subject`, one object or a list; one tied to the place authority has a
    `geo_name` and reads "Place - Topic";
  - `note[]`, whose text can be HTML: the note that a description is
    preliminary arrives in a red font tag;
  - `publisher`, `language`, `physical`;
  - `film_note[]`, one per film or DGS: `digital_film_no` (a number, or a
    string without its leading zeros), `filmno` (the microfilm number,
    empty for a born-digital capture), `text`, `items` ("Item 4"),
    `item_image_start_no`, `digital_film_rights` (`UNREST`, `NO_ACC` or
    empty), `location` and `shelf`.

  A field holding one value can arrive bare rather than as a list.
- **Catalog 3154151** (Nebraska, Furnas County, probate records,
  1806-1952) holds 3,045 films in 815 KB, each one case file with its own
  DGS: 3,019 marked `UNREST` and 26 `NO_ACC`. The service takes no query
  for its films, so `get_catalog_entry` filters the decoded entry, and
  keeps an entry for ten minutes because narrowing one means asking again.
- **Image counts come from the storage host.** The entry carries none.
  `GET {DAS_HOST}/dgs:{dgs}` with the token, and no browser User-Agent,
  answers 200 with `childCount`, the number of images, when this account
  may view the film; 403 "Access to artifact denied" for a `NO_ACC` film;
  401 with no token; 404 for an unknown number. The website asks the same
  question with a POST to `/platform/artifacts/groups/permissions`, which
  this server does not send.
- **A DGS keeps its zeros.** `dgs:008126335` answered 200 with 423 images
  and `dgs:8126335` answered 404. The catalog sends `8126335`, so
  `get_catalog_entry` pads every DGS to nine digits, as the website does.

`tests/live_check.py` re-asks the 401, the 403, the shape, the image count,
the 403 for a restricted film and the 404 for an unpadded DGS.

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

## How a search criterion is applied

Measured live on 2026-10-06 against the website search, with John Smith and
with Smith in Arkansas, all criteria required (`m.queryRequireDefault=on`).
`search_records` reports these rules back, per criterion, in its `filters`.

**A required criterion leaves out only a record that contradicts it.** A
record that does not give the field at all stays in. "John Smith born 1850"
matched 1,676,326; the Birth Year facet put only 171,054 of them in any
century, so 1.5 million gave no birth year. Of 5,887,737 John Smiths, a
spouse surname of "Jones" matched 4,266,296 and one of "Xyzzyqq" 4,259,584:
what either left out was the records naming some other spouse, and the
records naming none stayed in.

**Without `.exact`:**

| Criterion | Matches | Evidence |
| --- | --- | --- |
| A year | Five years either side. A christening counts as a birth and a burial as a death. | John Smith born 1850 and giving a year: 171,054 = born 1845-1855 exactly. Smith died 1870 and giving a year in the 1800s: 279,673 = died 1865-1875 exactly. Smith married 1880, in the 1800s: 407,012 = 1875-1885 exactly. A burial alone in 1900 matched a death year of 1900. |
| A given name | Spelling variants, and the name as a middle name. | Smiths born in 1850: "Jon" matched as many as "John", 17,104; "David John Smith" was a hit for John. |
| A surname | Spelling variants. | "Smyth", born in 1850: 176,495 without exact, 1,752 with. |
| A place | Far beyond the place. A word that is not a place FamilySearch knows is dropped. | Smith with a residence of "White, Arkansas": 3,968,744, of which 28,460 lived in Arkansas and 9,570 in White County. "Xyzzyqq, Arkansas" matched as many as "Arkansas". |

**With `.exact`, the record must give the field, and it must match:**

| Criterion | Matches | Evidence |
| --- | --- | --- |
| A year | That year only. | 17,104, every one born 1850; `.exact` on `q.birthLikeDate=1850` and on `.from=1850&.to=1850` gave the same 17,104. Without `.exact`, `.from`/`.to` still let in the records giving no year: 1,434,967. |
| A given name | The whole given name as spelled. | "John" 6,017, against 17,104 without; "John William" 98. |
| A place | Every place FamilySearch knows by those words, at any level. | Smith, "White, Arkansas": 10,566. The Residence Place facet put 9,570 in White County and the rest in Phillips, Newton, Searcy, Polk and other counties, each of which has a White Township. "Xyzzyqq, Arkansas" still matched as many as "Arkansas" (369,151). "Saline District, Cherokee Nation, Indian Territory" matched nothing, where "Cherokee Nation, Indian Territory" matched 1,506: the index gives the nation, never the district. |

Under `loose` (no `m.queryRequireDefault`) the criteria rank rather than
filter: John Smith matched 62,242,889, as many as Smith alone, and adding a
birth year changed nothing.

**A place can be held to its county or state by the place facet.** Asked
for with `c.residencePlace1=on&c.residencePlace2=on`, the facet nests a
region (`United States of America`), a state or country (`Arkansas`) and a
county (`White`), each bucket counting the hits there and carrying the
filter that selects it, e.g. `f.residencePlace2=10,Arkansas,White`. Sent
back, that filter returned 9,570, exactly the bucket's count. A fourth
level (`c.residencePlace3`) is a 400; the year facets stop at the decade
(`c.birthLikeDate2` is a 400). The same facets exist for `birthLikePlace`,
`deathLikePlace` and `marriageLikePlace`. With `exact`, `search_records`
finds the bucket naming the caller's county or state and asks again with its
filter; without it, it reports how many hits are in that place.

Asking for the facets made no difference beyond the noise in a search that
took five to nine seconds.

## Paging the website search

The response's `index` says where its page starts, and that is the only
dependable sign of which page came back. On 2026-10-06 an offset of 1,001
was answered from index 1,001 in one minute and from index **0** a few
minutes later: the first page again, with no error. Offsets of 1,500 and
above did the same, or answered 400. So `search_records` checks `index`
against the offset it asked for, and refuses a page it was not asked for
rather than passing the first page off as the next. It refuses an offset
over 4,999 without asking.

## The catalogue has no search endpoint

`/platform/records/collections` takes no query, so a title search means
holding the whole list. Verified live on 2026-10-06:

- **A page is a window of 100 slots**, holding the collections visible in
  it: between 78 and 100 of them, never more. `count=200` at `start=0`
  returned the same 91 as `count=100`. Stepping `start` by 100 from 0 found
  3,828 collections in 42 windows, no window repeating another, then empty
  windows from `start=4200`. Every page also repeats the container the
  collections sit in (`sd_c`), which is not a collection.
- **There is no total.** The listing carries no `results`, no `links` and
  no count in any header, under any of the three Accept types it serves
  (the Atom type is a 406). The
  records root (`/platform/collections/records`) carries none either. The
  website's collection list (`/service/search/hr/v2/collections`, a browser
  User-Agent and the token) reports `results: 3507`, but that is a
  different set from the API's 3,828 with every combination of its flags
  tried, so it cannot check a walk.
- **The walk used to step by what came back.** It asked for 200, stepped
  `start` by the number of entries returned (the container included), and
  stopped at the first page with nothing new. A full page made it step
  101 and skip a collection: on 2026-10-06 that walk found 3,826, missing
  2467808 and 5000242. A cache written by it once held 3,443 of 3,827 and
  was trusted for a month, because nothing recorded how its walk had ended.
- **Each collection's id is in its `about`.** The listing names a
  collection `sd_c_2110820`, an id local to the document. The collection
  route and the search filter both answer that form with a 400; `2110820`
  works.

`search_collections` now steps by 100 and stops after two empty windows in
a row, or, incomplete, at its 80-page limit or at a window repeating one
already read. Only a complete walk is cached, on disk for thirty days, with
its format version, time and page count; any other cache is walked again.
Every result reports the catalogue's size, age and completeness. A walk
takes about a hundred seconds. `search_collections(refresh=True)` rebuilds
it.

## Browsing waypoints

Verified live on 2026-10-06 on "Tennessee, Probate Court Books, 1795-1927"
(1909088), whose images are not indexed, and with and without a token: the
waypoint routes answer the same either way.

- **A waypoint needs its collection.** `GET /platform/records/waypoints/{id}`
  answers 400 "Required request parameter 'cc'" without `cc={collection}`.
  The records root's own link template says as much:
  `/platform/records/waypoints/{wid}{?cc,count,start}`.
- **Under the wrong collection** the same waypoint answered 404 one time and
  200 with nothing in it (`results: 0`, `start=-1`) the next.
- **The response describes a node, its parents and its children.** The
  document's `description` names the node (`#src_1`); each child's
  `componentOf` points at it; the node's points up through the county to
  the collection. The `sd_`/`src_` ids are local to the document. The id to
  descend by is inside each child's `about`, and a volume's has a comma:
  `M6QS-124:179638101,179638102`.
- **A volume lists its images** as `DigitalArtifact` descriptions whose
  `about` holds a `3:1:` (or `3:2:`) ark. `links.self.results` counts the
  children. With no `count`, a volume of 1,007 images answered 1,000; `start`
  and `count` page it.
- **A collection with nothing to browse** answers its waypoints with 404,
  the same as a collection that does not exist. Its description tells them
  apart: 1909088 has `links.waypoints` and a `DigitalArtifact` content count
  of 628,641; "Iowa, County Death Records, 1880-1992" (2110820) has neither.

## A record's facts carry a value

Verified live on 2026-10-06 on Tennessee death index personas of 1911 and an
1880 census persona. A fact such as a marital status, a race or an
occupation holds its content in `value` ("Single", "Stock Broker"), not in a
date or place. On a record, a fact also carries indexed `fields` of its own,
and so do its `date` and `place`: each value is typed `Original` (labelled
`..._ORIG`, as the indexer transcribed it: "S") or `Interpreted`. The
`date.original` and `place.original` a fact shows are FamilySearch's
reading, which can differ from the transcription: a death place written
"Paducah, Kentucky" is shown as "Paducah, McCracken, Kentucky, United
States", and a date written with the month as a number is shown with its
name. A birth year with no `_ORIG` date was worked out, for example from an
age (`PR_BIR_YEAR_EST`).
`get_record` reports `value`, and `original` by label, for every fact; a
fact with nothing in it is marked `sent_empty`.

## Tree profiles, as `compare_person` reads them

Verified live on 2026-10-05 against two long-dead public profiles: George
Washington (`KNDX-MKG`) and his great-grandmother Hannah Atherold
(`L1M1-8GY`).

- **The GET carries the version.** `GET /platform/tree/persons/{id}`
  answers with a weak `ETag` (`W/"139769026020400000"`) and a
  `Last-Modified`, and `HEAD` on the same path answers the same ETag. So
  the comparison reads both from the GET and no HEAD is sent. The change
  log carries an ETag of its own, which is not the profile's.
- **Whether you may change it.** `persons[0].personInfo[0].canUserEdit` is
  false for Washington, whom FamilySearch keeps read-only, and true for
  Hannah Atherold. `compare_person` drafts no packets when it is false.
- **Who last changed each conclusion.** Every fact, name and gender carries
  its conclusion `id` and an `attribution`: the contributor's agent id
  (`contributor.resourceId`), `modified` in epoch milliseconds, and the
  `changeMessage` they typed, if any. The person read has no contributor
  *names*; the change log does, as `contributors[].name` with the agent id
  at the end of `contributors[].uri`. `compare_person` maps one to the other
  and falls back to the agent id for anyone not on the log's first page.
- **Tags name a conclusion two ways.** A source reference's `tags[]` hold
  either `{"resource": "http://gedcomx.org/Birth"}` or, for one of several
  facts of a kind, `{"conclusionId": "..."}`.
- **User-defined facts** carry their type as a `data:` URI, e.g.
  `data:,Will+Proved`.
- **The change log ignores `count`.** For Hannah Atherold's profile, being
  edited that week, one page held 116 entries and about 960 KB, with or
  without `count=10`; a `next` link pages further back. The comparison reads
  the first page only, which is enough to see the last 90 days on any
  profile seen so far.
- **No duplicates is a 204.** `GET .../matches?collection=tree` answered 204
  with no body for both profiles.
- **Families** carry the subject's `Couple` relationships with their
  `Marriage` facts, `ParentChild` relationships, and
  `childAndParentsRelationships`, for the subject and their parents' other
  children.

`tests/live_check.py` re-asks the first three, against Washington's profile.

## Throttling

FamilySearch answers 429 when an application sends too much, with a
`Retry-After` header in seconds. The client waits out a delay of up to 15
seconds and retries once; a longer one is handed back to the caller as
`rate_limited`, because a tool call that blocks for minutes looks hung. No
429 has been captured live in this project's use, so the header's form is
taken from the HTTP standard: a date-form `Retry-After` is ignored rather
than parsed, and a missing one gets a two-second wait.
