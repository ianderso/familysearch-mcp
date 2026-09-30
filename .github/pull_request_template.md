<!-- What this changes and why. Link the issue it closes, if there is one. -->

## Checklist

What each item means is in [CONTRIBUTING.md](https://github.com/ianderso/familysearch-mcp/blob/main/CONTRIBUTING.md#what-a-change-carries).

- [ ] A test that fails without this change.
- [ ] `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest` pass.
- [ ] Tool descriptions are written for the model and fit under `DESCRIPTION_BUDGET`. Raising it takes a pull request of its own, saying why.
- [ ] Any tool reading the shared tree is registered through `_tree_tool`.
- [ ] A tool needing a token refuses locally without one.
- [ ] Failures come back as an `error` result, not an exception.
- [ ] A new tool declares annotations: read-only, or what it writes.
- [ ] If a tool or parameter changed: `tests/fixtures/tool_schema.json` is regenerated and the README tables are updated.
- [ ] If this relies on how the live API answers: what was observed, and when, is in `docs/API-NOTES.md` and `tests/live_check.py`, and captured payloads carry no real people's names.
- [ ] A `CHANGELOG.md` entry, if users will notice the change.
- [ ] Nothing here writes to FamilySearch, and nothing in this repository handles a password.
