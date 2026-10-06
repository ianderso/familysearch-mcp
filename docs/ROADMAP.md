# Roadmap

Everything this project set out to build is built: the anonymous gazetteer,
record search and record reads, image resolution and download, the
collection catalogue and film browser, the FamilySearch Catalog's entries
and their films, full-text search of machine-read page images, the
shared-tree tools, and a read-only comparison of your own research with a
tree profile. That is 28 tools; the [README](../README.md) is the reference
for what exists, and the
[changelog](../CHANGELOG.md) for what changed.

Nothing is queued. New work starts from a research question the tools cannot
answer — open an issue saying what you were trying to find and where the
tools stopped you.

## How a new tool is judged

- **It reads.** See below.
- **A token-only tool refuses locally without one**, naming what to set. It
  never sends a bare request and relays FamilySearch's confusing 401. The
  auth-boundary tests enforce this for every tool.
- **A tree tool carries the shared-tree caveat in its own description.** A
  model choosing a tool sees the description and nothing else, and the
  failure mode is a caller treating a community-edited profile as a source
  because a tool returned it confidently.
- **An id goes into a path only after it is checked.** A tool argument must
  not be able to steer a request to a different route.
- **Undocumented behaviour gets a dated live verification**, in a comment
  beside the code, in [API-NOTES.md](API-NOTES.md), and as a check in
  `tests/live_check.py`. Much of the Historical Records API is behind a
  login wall, so the live API is the only documentation there is.

## Not planned

- **Any write.** Tree edits, memory uploads, merges. The tree is
  community-edited, a write is immediately visible to everyone, and this
  server treats the tree as a lead rather than a source. `compare_person`
  proposes changes as packets for a person to make by hand; it never makes
  one.
- **A bundled client id or a password flow.** See
  [AUTH.md](AUTH.md).
- **Managing the OAuth lifecycle.** FamilySearch issues no refresh token, so
  keeping a token live means signing in again. The server stays out of that.
  It takes a token and, when one expires, re-reads the env file, so anything
  that writes a fresh token there is enough, and the server never handles a
  password.
- **`/platform/places/parents` and `/platform/places/{id}/ischild`.** A place
  description already carries every jurisdiction above it, which is what
  `get_place_jurisdictions` returns, so both questions are answered without
  them. Unlike the rest of the Places API, their specification also carries
  no "no auth" declaration.
- **Longer backoff on throttling.** One retry after a wait of up to 15
  seconds is the limit. A tool call that blocks for longer looks hung to the
  client, and the caller is better placed to decide whether to wait.
