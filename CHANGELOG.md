# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/). The tool surface is the public
interface: renaming or removing a tool or a parameter is a major release, and
adding one is a minor release.

## [Unreleased]

### Added

- `get_catalog_entry`: read a FamilySearch Catalog entry, the library's
  description of a set of films: title, authors, places, notes, and each
  film or DGS with its description (volume, case numbers, years), its image
  count and whether your account may view it. `contains` keeps the items
  holding every word given, a number matching only whole or inside a span,
  and `count` and `offset` page through an entry of thousands. It reads the
  service the website's catalog page reads, with your token and a browser
  User-Agent, like record search, and asks the image store for each
  returned film. Every result carries cautions: an entry describes
  holdings, not the record; a film may be restricted or never digitised;
  and a DGS is not the microfilm number.

### Changed

- The tool descriptions are shorter, to make room for the new tool within
  the same budget: the shared-tree warning every tree tool carries is said
  in fewer words, and repetition in `get_film_image`, `search_collections`,
  `get_person_relatives` and `get_person_changes` is gone. The existing
  descriptions fell from 15,667 characters to 14,787; with the new tool the
  block is 15,409 of 16,000.
- The README counts 28 tools; it had said 26 since 1.1.0 added two.

## [1.1.0] — 2026-10-05

### Added

- `compare_person`: compare your own record of one deceased person (names,
  events, relatives, each with its sources) with their tree profile. It
  reports what agrees, what the profile lacks and what differs, the profile's
  ETag, who has changed it in the last 90 days, possible duplicates and signs
  of a conflation, and drafts packets: one proposed change each, with the
  source, its tags and a draft reason, for you to make by hand. It reads
  only, refuses anyone who may be living, and never proposes combining
  profiles, removing anything, replacing a relationship or changing living
  status. See [docs/COMPARE.md](docs/COMPARE.md).
- `fulltext_search`: search the handwriting-recognised text of page images,
  mostly deeds, wills, probate and court files, for a name or phrase
  anywhere on a page. It uses the website's full-text service, with your
  token and a browser User-Agent, like record search. Each hit is a page
  image with the passages that matched, the names recognised on it, and its
  collection and record title. Every word must match unless the query says
  otherwise. Facets narrow by collection, century, place and record type,
  and `image_group` searches one volume. Every result carries cautions: the
  text is a machine reading, so open the image and cite that; coverage is
  partial; and the citation path to the image.
- `get_image_links` reports the page's `film_number` (image group) and
  `image_number` when a token is set. A citation to the page needs both.

### Changed

- An error from a website search service now includes the service's own list
  of validation errors, not just "Validation failed."
- Tool descriptions are published without their source indentation on
  Python 3.11 and 3.12, as they already were on 3.13. Every client now gets
  the same text, about 870 characters shorter in all on those versions.

## [1.0.0] — 2026-09-29

The first public release.

### Tools

- Places, with no token: `search_places`, `search_places_at_date` (a place as
  it was in a given year), `get_place`, `get_place_jurisdictions`,
  `get_place_children`.
- Records and collections: `search_records` (name, birth, death, marriage and
  residence, spouse and parents, record type, collection; every criterion
  filters unless `loose` is set), `get_record`, `get_record_image`,
  `get_records_on_image`, and, with no token, `search_collections`,
  `get_collection`, `get_collection_fields` and `browse_waypoints`.
- Page images: `get_image_links`, `get_film_image`, `download_image`.
- The shared tree, each tool carrying the warning that a profile is a lead and
  not evidence: `get_person`, `get_person_relatives`, `get_person_sources`,
  `get_ancestry`, `get_descendancy`, `get_person_memories`,
  `get_person_changes`, `get_matches`.
- `auth_status`, which asks FamilySearch whether the token is still accepted.

### Behaviour worth knowing

- The package ships no client id and never handles a password. A token
  that expires mid-session is replaced by re-reading the env file.
- A tool refuses a parameter it does not define, and names the ones it
  takes.
- A throttled request is retried once after a `Retry-After` of up to 15
  seconds.
- `download_image` fetches only HTTPS FamilySearch URLs, since the request
  carries the token, and creates only image and PDF files, never
  overwriting one.
- An id is checked before it is placed in a request path.
- With `FS_ENVIRONMENT=integration`, record search goes to the sandbox's
  search service rather than production's.
- Every tool declares MCP annotations: all read-only except `download_image`,
  which creates a local file.

[Unreleased]: https://github.com/ianderso/familysearch-mcp/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/ianderso/familysearch-mcp/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ianderso/familysearch-mcp/releases/tag/v1.0.0
