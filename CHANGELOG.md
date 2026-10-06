# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/). The tool surface is the public
interface: renaming or removing a tool or a parameter is a major release, and
adding one is a minor release.

## [Unreleased]

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

[Unreleased]: https://github.com/ianderso/familysearch-mcp/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ianderso/familysearch-mcp/releases/tag/v1.0.0
