# familysearch-mcp

[![CI](https://github.com/ianderso/familysearch-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ianderso/familysearch-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/familysearch-mcp?label=pypi)](https://pypi.org/project/familysearch-mcp/)

<!-- mcp-name: io.github.ianderso/familysearch-mcp -->

An [MCP](https://modelcontextprotocol.io) server for genealogical research on
**FamilySearch**: a historical place gazetteer, indexed record search, the
page images behind the records, and reads of the shared family tree.

Nothing here writes to FamilySearch. The shared tree is community-edited and
conflations of same-named people are common, so a tree result is a hint:
follow it to the underlying record and cite that.

This is an independent project. It is not made, endorsed or supported by
FamilySearch.

## Credentials

**This package ships no client id and never handles a FamilySearch
password.** Records, images and the tree need an access token from your own
registered FamilySearch application; [docs/AUTH.md](docs/AUTH.md) explains why,
and how to get one.

The gazetteer, the collection catalogue and the film browser answer without
a token, so they work on a fresh install with no setup at all.

## Install

```bash
uvx familysearch-mcp
```

That runs the server over stdio, which is how an MCP client starts it. You
normally put it in the client's configuration rather than running it
yourself.

### Claude Desktop

```json
{
  "mcpServers": {
    "familysearch": {
      "command": "uvx",
      "args": ["familysearch-mcp"],
      "env": { "FS_ENV_FILE": "/path/to/familysearch.env" }
    }
  }
}
```

Point at an env file rather than pasting the token into `env`. A token that
lives in the client's config can only be replaced by editing it and
restarting; a token in the file is picked up mid-session. With no token at
all, leave `env` out and the anonymous tools still work.

### Claude Code

```bash
claude mcp add familysearch -e FS_ENV_FILE=/path/to/familysearch.env -- uvx familysearch-mcp
```

## Configuration

| Variable | Meaning |
| --- | --- |
| `FS_ACCESS_TOKEN` | Bearer token from your application's OAuth flow. |
| `FS_ENV_FILE` | The env file to read these settings from, and to re-read a refreshed token from. Default: the nearest `.env` from the working directory upward. |
| `FS_CLIENT_ID` | Your registered application's client id, reported by `auth_status`. |
| `FS_ENVIRONMENT` | `production` (default) or `integration` for the FamilySearch sandbox. |
| `FS_TIMEOUT` | HTTP timeout in seconds. Default 60. |

[`.env.example`](.env.example) lists them with comments.

## Tools

Twenty-six tools. All of them read; `download_image` also writes the page
it fetches to a local file.

### Places

FamilySearch's Places API answers anonymously.

| Tool | Needs a token | Purpose |
| --- | --- | --- |
| `search_places` | no | Resolve a place name to its full jurisdictional form and coordinates. |
| `search_places_at_date` | no | Resolve a place *as it was* in a given year. A record naming a county that no longer exists is normal; filing it under the modern one is an invisible error. |
| `get_place` | no | Read one place: jurisdictional chain, type, coordinates, and the dates that jurisdiction existed. |
| `get_place_jurisdictions` | no | Walk the containment chain upward — what turns "Kaskaskia" into "Kaskaskia, Randolph, Illinois, United States". |
| `get_place_children` | no | The places directly inside a jurisdiction — the downward walk. |

### Records and collections

| Tool | Needs a token | Purpose |
| --- | --- | --- |
| `search_records` | yes | Search historical records by name, life events, parents, spouse, record type or collection. Every criterion filters. Returns one hit per record, with the others named on it. |
| `get_record` | yes | Read one indexed record in full: every person on it and the labelled fields behind each. |
| `get_record_image` | yes | Find the document image a record came from, or the film number when no image was published. |
| `get_records_on_image` | yes | Every record indexed from one image. A census page carries forty people. |
| `fulltext_search` | yes | Search the handwriting-recognised text of page images, mostly deeds, wills, probate and court files, for a name or phrase anywhere on the page. A machine reading: open the image and cite that. |
| `search_collections` | no | Find a record collection by title, with its coverage. |
| `get_collection` | no | Read one collection: what it covers and how much of it there is. |
| `get_collection_fields` | no | Decode a collection's indexed field codes (`PR_FTHR_NAME` → "Father's Name"). |
| `browse_waypoints` | no | Browse a collection's volumes and films, to reach pages the index never covered. |

### Page images

| Tool | Needs a token | Purpose |
| --- | --- | --- |
| `get_image_links` | for the page | Resolve an image ark to fetchable URLs: full page, deep zoom, thumbnails, neighbouring pages, and with a token the film and image number a citation needs. Without a token only the navigation comes back. |
| `get_film_image` | for the page | Reach a page by film and image number when a citation gives those instead of an ark. Checking the page exists needs no token. |
| `download_image` | yes | Download a page image to a new local file so it can be read. |

### Shared tree — a lead, never a source

Every tool here reads a community-edited profile, and says so in its own
description.

| Tool | Needs a token | Purpose |
| --- | --- | --- |
| `get_person` | yes | Read a shared-tree person: names, sex, facts. |
| `get_person_relatives` | yes | Parents, spouses, children and siblings in one call. |
| `get_person_sources` | yes | What the tree attaches as sources, and which facts each supports. The fastest route out of the tree. |
| `get_ancestry` | yes | Pedigree walk back, up to 8 generations, numbered by Ahnentafel. |
| `get_descendancy` | yes | Pedigree walk forward, up to 4 generations. |
| `get_person_memories` | yes | Attached photographs, documents and stories. |
| `get_person_changes` | yes | The change log: who edited this profile, when, and why. |
| `get_matches` | yes | FamilySearch's own duplicate and record-match candidates. |
| `compare_person` | yes | Compare your own record of a deceased person with their profile: what agrees, what the profile lacks, what differs, and one proposed change per packet for you to make by hand. |

### Setup

| Tool | Needs a token | Purpose |
| --- | --- | --- |
| `auth_status` | no | Report what is configured, what is missing, and whether FamilySearch still accepts the token. |

## How it behaves

- **The tree is not evidence.** The tree tools read profiles anyone can
  edit. Use them to find records. `get_person_sources` is the most useful of
  them because it leads out of the tree towards a document.
- **A comparison proposes; it never changes.** `compare_person` takes your
  own names, events, relatives and sources for one person, reads the
  profile, and reports what agrees, what the profile lacks and what
  differs. Each proposed change comes as a packet: the source, the facts to
  tag it to, a draft reason with gaps for you to fill, and where on the
  website to make it. You make the change yourself, one at a time, after
  reading the record. It refuses anyone who may be living, and it never
  proposes combining profiles, removing anything, replacing a
  relationship or changing living status. See
  [docs/COMPARE.md](docs/COMPARE.md).
- **A persona is not the record.** A search returns one person's summary of
  what a record said; `get_record` returns the indexed fields behind it, and
  `get_record_image` the document itself. Read down that chain before citing.
- **Jurisdictions move.** `search_places_at_date` resolves a place as it was
  in a given year. Filing an 1820 record under the county that covers the
  ground today is a common and hard-to-spot error.
- **Record search uses the website's search service.** The API's own record
  search answers from a partial index that is almost all immigration
  records. `search_records` asks the service the FamilySearch website uses
  instead, with your token and a browser User-Agent, which that service
  requires. It is undocumented and FamilySearch can change or close it;
  [docs/API-NOTES.md](docs/API-NOTES.md) has the comparison.
- **Full-text search is a machine reading.** `fulltext_search` asks the
  website's full-text service, on the same footing as record search: your
  token, a browser User-Agent, and an undocumented route. Its text is
  handwriting recognition, so names and numbers are often misread; each
  hit gives the passages that matched and the page's image ark, and the
  page is what to read and cite. Only some collections and volumes have
  been machine-read, so no result proves nothing. Every word must match
  unless you write OR, because the service otherwise matches any one of
  them.
- **Search criteria filter.** FamilySearch treats a search term as a ranking
  hint unless told otherwise, so adding a death year to a name search only
  reorders it. This server asks for every criterion to match; `loose=True`
  goes back to ranking.
- **Tokens expire, and a refreshed one is picked up.** A token lasts about an
  hour. On a 401 the server re-reads `FS_ACCESS_TOKEN` from the env file and
  retries once, so refreshing the file is enough. `auth_status` reports
  `token_accepted: false` when it is not.
- **Throttling is retried once.** A 429 asking for a wait of up to 15 seconds
  is waited out and retried. A longer wait, or a second 429, comes back as
  `rate_limited` with the server's `Retry-After`.
- **Unknown parameters are refused.** A misspelt or invented argument is an
  error that lists the parameters the tool does take. It is not silently
  dropped, which would make a filtered search quietly return unfiltered
  results.
- **`download_image` is careful with what it is given.** It fetches only
  HTTPS URLs on FamilySearch hosts, because the request carries your token.
  It creates only image and PDF files, and never overwrites one.
- **Some routes are not publicly documented.** FamilySearch's Historical
  Records API is behind a login wall, so those routes and response shapes
  were confirmed by live probing instead. A comment beside the code says
  when, and [docs/API-NOTES.md](docs/API-NOTES.md) records what was found.
  `tests/live_check.py` asks again.

## Development

```bash
git clone https://github.com/ianderso/familysearch-mcp
cd familysearch-mcp
uv sync --extra dev
uv run pytest                  # mocked with respx; no token, no network
uv run ruff check .
uv run ruff format --check .
```

`uv run python -m tests.live_check` re-asks FamilySearch the questions only
the live API can answer, with the token from your env file. See
[CONTRIBUTING.md](CONTRIBUTING.md) for what a change is expected to carry.

## License

[MIT](LICENSE).
