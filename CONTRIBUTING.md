# Contributing

Issues and pull requests are welcome. This file says how the project is put
together and what a change is expected to carry.

## Setting up

```bash
git clone https://github.com/ianderso/familysearch-mcp
cd familysearch-mcp
uv sync --extra dev
```

Before sending a change, run what CI runs:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The suite is mocked with [respx](https://lundberg.github.io/respx/) and needs
no token. It must never touch the live API: a guard in `tests/conftest.py`
fails any test that opens a real connection, and CI has no token at all.

## Where things live

| Path | What it holds |
| --- | --- |
| `src/familysearch_mcp/server.py` | The tools. Their docstrings and `Field` descriptions *are* the published tool descriptions and schema. |
| `src/familysearch_mcp/client.py` | The HTTP client: the anonymous-path boundary, token recovery, the throttling retry, and the image download. |
| `src/familysearch_mcp/shape.py` | Turning uneven GEDCOM X into compact results. |
| `src/familysearch_mcp/compare.py` | `compare_person`'s comparison and packets: pure functions, no requests. |
| `src/familysearch_mcp/config.py` | Settings from the environment and the env file. |
| `docs/API-NOTES.md` | What the live API actually does, where FamilySearch no longer documents it. |
| `docs/AUTH.md` | Why the package takes a token and never a password, and how to get one. |
| `tests/test_tool_contract.py` | Tests over the tool surface as a client sees it. |
| `tests/live_check.py` | The one script that talks to the live API, run by hand with a token. Not collected. |
| `tests/record_tree_fixture.py` | Records a tree profile's responses into `tests/fixtures/tree/`, with every contributor replaced. Run by hand with a token. Not collected. |
| `tests/record_catalog_fixture.py` | Records a FamilySearch Catalog entry into `tests/fixtures/catalog/`, cut short, with the people its film descriptions name replaced. Run by hand with a token. Not collected. |

## What a change carries

**A test that fails without it.** Bug fixes especially: reproduce the bug as a
test first.

**Descriptions written for the model.** A tool's docstring is what a model
reads when choosing and calling it, so write it for that reader, not for a
developer. The combined descriptions have a ceiling (`DESCRIPTION_BUDGET` in
`tests/test_tool_contract.py`), because they are sent on every session before
any work happens. Raise it deliberately, in a pull request of its own, saying
why. Pull requests are squash-merged, so a commit of its own inside a larger
one would not survive the merge.

**The tree kept at arm's length.** Every tool that reads the shared tree is
registered through `_tree_tool`, which appends the warning that a profile is
a lead and not evidence. A contract test enforces it.

**The credential boundary kept.** A tool that needs a token refuses locally
without one, naming what to set. The auth-boundary tests check every tool.
Nothing in this repository may ask for, store or send a password; a test
fails if code that signs in to the FamilySearch website appears.

**A structured result, never an exception.** Every tool catches its failures
and returns an `error` envelope. A sweep test calls every tool with the API
failing and fails if one raises.

**A snapshot update, if the surface changed.** Renaming or adding a tool or
parameter changes what callers depend on, so it has to show up as a diff:

```bash
uv run python -m tests.regen_tool_snapshot
```

Commit the regenerated `tests/fixtures/tool_schema.json` with the change, and
add the tool to the README's tables — a test checks that too.

**Dated evidence for claims about the live API.** Much of it is undocumented,
so behaviour is only trusted once seen. When a change depends on how the live
API answers, record what was observed and when, in `docs/API-NOTES.md` and
beside the code that relies on it, and add a check to `tests/live_check.py`.
Remove personal names and anything else identifying from captured payloads
before committing them: fixtures use invented people. The one exception is a
recorded tree profile, which may keep a long-dead public figure and their
family by name; everyone who *edited* the profile is replaced, which
`tests/record_tree_fixture.py` does.

## What will not be merged

Tools that write to FamilySearch — tree edits, merges, memory uploads,
attaching sources. A write to the shared tree is immediately visible to
everyone and cannot be withdrawn by this server. A bundled client id, or a
password flow anywhere in this repository, will not be merged either; see
[docs/AUTH.md](docs/AUTH.md).

## Releasing

1. Update `__version__` in `src/familysearch_mcp/__init__.py`; the package
   version is read from there. Set the same version twice in `server.json`,
   once at the top and once on the package; a test holds the three together.
2. Move the changelog's entries under a heading for the new version.
3. Once that pull request is merged, tag the merge commit `vX.Y.Z` and
   publish a GitHub release from the tag.
4. Publishing the release runs `.github/workflows/release.yml`, which builds
   the tag, uploads it to PyPI by Trusted Publishing, and then publishes
   `server.json` to the MCP Registry; there is no token to manage. It refuses
   a tag that does not match `__version__` or `server.json`.

Before the first release, once: add this repository as a Trusted Publisher
of `familysearch-mcp` on PyPI (workflow `release.yml`, environment `pypi`);
create the `pypi` and `mcp-registry` environments in the repository's
settings, each limited to `v*` tags and `main`; and turn on private
vulnerability reporting, which `SECURITY.md` and the issue templates link
to.
