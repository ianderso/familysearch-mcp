"""Configuration: the sandbox and production must never be confused.

An individual developer key reaches only the Integration sandbox, which holds
synthetic data. Sending a sandbox token at production -- or worse, reporting
synthetic people as if they were real -- is the mistake this guards.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx
import pytest
import respx

from familysearch_mcp.client import FamilySearchClient
from familysearch_mcp.config import (
    HOSTS,
    Config,
    ConfigError,
    load_config,
    token_from_env_file,
)

FS_VARIABLES = (
    "FS_ENVIRONMENT",
    "FS_ACCESS_TOKEN",
    "FS_CLIENT_ID",
    "FS_TIMEOUT",
    "FS_ENV_FILE",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Strip FS_* variables so a developer's own .env cannot alter a result.

    The conftest already runs each test from an empty directory, so no real
    env file is found. What a test's own env file loads is written straight
    into ``os.environ`` by dotenv, bypassing monkeypatch, so it is removed
    afterwards -- before monkeypatch restores anything the developer had set.
    """
    for name in FS_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    yield
    for name in FS_VARIABLES:
        os.environ.pop(name, None)


def test_production_is_the_default_host():
    """An install that sets nothing talks to production, not the sandbox."""
    assert load_config().base_url == "https://api.familysearch.org"


def test_integration_selects_the_sandbox_host(monkeypatch):
    """The sandbox has a different host and holds synthetic data."""
    monkeypatch.setenv("FS_ENVIRONMENT", "integration")
    assert load_config().base_url == "https://api-integ.familysearch.org"


def test_the_two_hosts_are_not_the_same():
    """A typo collapsing the two would silently send sandbox work at production."""
    assert HOSTS["production"] != HOSTS["integration"]
    assert len(set(HOSTS.values())) == len(HOSTS)


def test_an_unknown_environment_is_refused_at_config_load(monkeypatch):
    """Refuse at load rather than build a base URL that cannot resolve."""
    monkeypatch.setenv("FS_ENVIRONMENT", "staging")
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "staging" in str(exc.value)
    assert "production" in str(exc.value) and "integration" in str(exc.value)


def test_environment_name_is_case_and_space_insensitive(monkeypatch):
    """' Integration ' is a configuration typo, not a different environment."""
    monkeypatch.setenv("FS_ENVIRONMENT", "  Integration  ")
    assert load_config().environment == "integration"


def test_an_empty_token_is_not_a_token(monkeypatch):
    """FS_ACCESS_TOKEN= in a .env must read as unconfigured, not as ''."""
    monkeypatch.setenv("FS_ACCESS_TOKEN", "")
    config = load_config()
    assert config.access_token is None
    assert config.authenticated is False


def test_no_client_id_is_bundled(monkeypatch):
    """The package ships no credential; an unset id stays unset."""
    assert load_config().client_id is None
    assert Config().client_id is None


@respx.mock
async def test_a_sandbox_client_never_reaches_the_production_host():
    """Pinned by mocking production and asserting it was not called."""
    production = respx.route(host="api.familysearch.org").mock(
        return_value=httpx.Response(200, json={})
    )
    sandbox = respx.get("https://api-integ.familysearch.org/platform/tree/persons/X").mock(
        return_value=httpx.Response(200, json={"persons": []})
    )

    config = Config(access_token="t", environment="integration", timeout=5.0)
    async with FamilySearchClient(config) as client:
        await client.get("/platform/tree/persons/X")

    assert sandbox.called
    assert not production.called


# --------------------------------------------------------------------------- #
# Finding the env file: startup and token recovery must agree
# --------------------------------------------------------------------------- #
def _write(path: Path, token: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"FS_ACCESS_TOKEN={token}\n")
    return path


def test_fs_env_file_alone_supplies_the_token(tmp_path, monkeypatch):
    """Naming the file is enough; the launcher need not export the token.

    FS_ENV_FILE used to be consulted only after a 401, so a server given
    just the path started with no token at all.
    """
    env = _write(tmp_path / "elsewhere" / "fs.env", "from-file")
    monkeypatch.setenv("FS_ENV_FILE", str(env))
    config = load_config()
    assert config.access_token == "from-file"
    assert config.env_file == str(env)


def test_startup_and_recovery_read_the_same_file(tmp_path, monkeypatch):
    """With two candidate files, both steps take the one FS_ENV_FILE names.

    Startup used to let dotenv search upward from the package's own source
    file, while recovery searched from the working directory. A server could
    load its token from one file and look for the refreshed one in another.
    """
    _write(tmp_path / ".env", "nearby")
    named = _write(tmp_path / "named.env", "named")
    monkeypatch.setenv("FS_ENV_FILE", str(named))
    config = load_config()
    assert config.access_token == "named"
    assert token_from_env_file(config.env_file) == "named"


def test_without_fs_env_file_the_nearest_env_upward_is_used(tmp_path, monkeypatch):
    """Running from inside a project finds the project's .env."""
    env = _write(tmp_path / ".env", "nearby")
    deeper = tmp_path / "a" / "b"
    deeper.mkdir(parents=True)
    monkeypatch.chdir(deeper)
    config = load_config()
    assert config.access_token == "nearby"
    assert Path(config.env_file).resolve() == env.resolve()


def test_a_tilde_in_fs_env_file_is_expanded(tmp_path, monkeypatch):
    """Client configs are JSON, and JSON does not expand ~."""
    # ~ comes from HOME on POSIX and from USERPROFILE on Windows.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _write(tmp_path / "fs.env", "from-home")
    monkeypatch.setenv("FS_ENV_FILE", "~/fs.env")
    assert load_config().access_token == "from-home"


def test_an_exported_token_wins_over_the_file(tmp_path, monkeypatch):
    """A real environment variable beats the file, and recovery still knows it."""
    env = _write(tmp_path / "fs.env", "from-file")
    monkeypatch.setenv("FS_ENV_FILE", str(env))
    monkeypatch.setenv("FS_ACCESS_TOKEN", "exported")
    config = load_config()
    assert config.access_token == "exported"
    assert config.env_file == str(env)


def test_an_exported_token_with_no_file_is_warned_about(monkeypatch, caplog):
    """The launcher case: the token is known, where it came from is not."""
    monkeypatch.setenv("FS_ACCESS_TOKEN", "exported")
    with caplog.at_level(logging.WARNING, logger="familysearch_mcp.config"):
        config = load_config()
    assert config.env_file is None
    assert "FS_ENV_FILE" in caplog.text


def test_a_missing_fs_env_file_is_reported_not_skipped(tmp_path, monkeypatch, caplog):
    """A mistyped path must surface, not quietly fall back to another file."""
    _write(tmp_path / ".env", "nearby")
    missing = tmp_path / "typo.env"
    monkeypatch.setenv("FS_ENV_FILE", str(missing))
    with caplog.at_level(logging.WARNING, logger="familysearch_mcp.config"):
        config = load_config()
    assert config.access_token is None
    assert config.env_file == str(missing)
    assert "does not exist" in caplog.text


@respx.mock
async def test_the_sandbox_searches_the_sandbox_website():
    """A sandbox token means nothing to production; search where it was issued."""
    from familysearch_mcp.client import SEARCH_URL, SEARCH_URLS, FamilySearchClient

    route = respx.get(SEARCH_URLS["integration"]).mock(
        return_value=httpx.Response(200, json={"results": 0})
    )
    config = Config(access_token="t", environment="integration", timeout=5.0)
    async with FamilySearchClient(config) as client:
        await client.search({"q.surname": "Smith"})
    assert route.called
    assert SEARCH_URLS["integration"] != SEARCH_URL
    assert set(SEARCH_URLS) == set(HOSTS)
