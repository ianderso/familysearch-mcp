"""Recovering from a token that expires mid-session.

A token lasts about an hour and a server process reads its environment once
at startup, so any long session outlives its credential. Reported from real
use: the harness saw the process as healthy and refused to reconnect it, the
refreshed token sat unread in the env file, and every call returned 401 until
the session was restarted.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp.client import (
    SEARCH_URL,
    FamilySearchApiError,
    FamilySearchClient,
)
from familysearch_mcp.config import Config, token_from_env_file

PERSON = "https://api.familysearch.org/platform/tree/persons/K2ZP-VY1"


def _env(tmp_path, token: str | None = "fresh", extra: str = "") -> str:
    target = tmp_path / ".env"
    body = f"FS_ACCESS_TOKEN={token}\n" if token else ""
    target.write_text(extra + body)
    return str(target)


# --------------------------------------------------------------------------- #
# Reading the file rather than the environment
# --------------------------------------------------------------------------- #
def test_the_token_is_read_from_the_file_not_the_environment(tmp_path, monkeypatch):
    """load_dotenv will not override a variable already set in the process.

    That is exactly this situation: the launcher exported the token before
    starting the server, so anything that goes through the environment sees
    the stale value forever.
    """
    monkeypatch.setenv("FS_ACCESS_TOKEN", "stale-from-launcher")
    assert token_from_env_file(_env(tmp_path, "fresh-on-disk")) == "fresh-on-disk"


def test_a_missing_env_file_is_not_an_error(tmp_path):
    """A server configured purely from the environment still works."""
    assert token_from_env_file(str(tmp_path / "nope.env")) is None


def test_an_env_file_without_a_token_returns_nothing(tmp_path):
    """Other settings in the file must not be mistaken for a token."""
    assert token_from_env_file(_env(tmp_path, None, "FS_CLIENT_ID=abc\n")) is None


def test_other_settings_in_the_file_are_left_alone(tmp_path):
    """Reading the token must not disturb the rest of the file."""
    path = _env(tmp_path, "tok", "OTHER_API_KEY=secret\nOTHER_TOOL_URL=http://x\n")
    assert token_from_env_file(path) == "tok"
    assert "OTHER_API_KEY=secret" in open(path).read()


# --------------------------------------------------------------------------- #
# Recovering on a 401
# --------------------------------------------------------------------------- #
@respx.mock
async def test_a_401_retries_once_with_a_refreshed_token(tmp_path):
    """The whole point: no reconnect, no restart."""
    client = FamilySearchClient(
        Config(access_token="stale", env_file=_env(tmp_path, "fresh"), timeout=5)
    )
    seen: list[str] = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(401 if len(seen) == 1 else 200, json={"ok": True})

    respx.get(PERSON).mock(side_effect=handler)
    assert (await client.get("/platform/tree/persons/K2ZP-VY1"))["ok"] is True
    assert seen == ["Bearer stale", "Bearer fresh"]
    await client.aclose()


@respx.mock
async def test_the_search_path_recovers_too(tmp_path):
    """Search goes through a different host and headers; it needs its own."""
    client = FamilySearchClient(
        Config(access_token="stale", env_file=_env(tmp_path, "fresh"), timeout=5)
    )
    seen: list[str] = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        return httpx.Response(401 if len(seen) == 1 else 200, json={"results": 1})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    assert (await client.search({"q.surname": "Pettibone"}))["results"] == 1
    assert seen[-1] == "Bearer fresh"
    await client.aclose()


@respx.mock
async def test_an_unchanged_token_is_not_retried(tmp_path):
    """Retrying the same credential would just spend another call."""
    client = FamilySearchClient(
        Config(access_token="same", env_file=_env(tmp_path, "same"), timeout=5)
    )
    route = respx.get(PERSON).mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(FamilySearchApiError):
        await client.get("/platform/tree/persons/K2ZP-VY1")
    assert route.call_count == 1
    await client.aclose()


@respx.mock
async def test_a_second_401_is_not_retried_again(tmp_path):
    """One retry, not a loop. A genuinely dead token must surface."""
    client = FamilySearchClient(
        Config(access_token="stale", env_file=_env(tmp_path, "fresh"), timeout=5)
    )
    route = respx.get(PERSON).mock(return_value=httpx.Response(401, json={}))
    with pytest.raises(FamilySearchApiError):
        await client.get("/platform/tree/persons/K2ZP-VY1")
    assert route.call_count == 2
    await client.aclose()


@respx.mock
async def test_a_403_is_not_treated_as_an_expired_token(tmp_path):
    """403 is insufficient scope, and a fresh token will not help."""
    client = FamilySearchClient(
        Config(access_token="stale", env_file=_env(tmp_path, "fresh"), timeout=5)
    )
    route = respx.get(PERSON).mock(return_value=httpx.Response(403, json={}))
    with pytest.raises(FamilySearchApiError):
        await client.get("/platform/tree/persons/K2ZP-VY1")
    assert route.call_count == 1
    await client.aclose()


def test_reloading_never_reads_a_password(tmp_path, monkeypatch):
    """Recovery adopts a token someone else obtained. It does not sign in.

    The server's standing guarantee is that it never handles a password,
    and this path must not quietly become an exception to it.
    """
    path = _env(tmp_path, "fresh", "FS_USERNAME=someone\nFS_PASSWORD=secret\n")
    client = FamilySearchClient(Config(access_token="stale", env_file=path, timeout=5))
    assert client._reload_token() is True
    assert client._config.access_token == "fresh"
    assert getattr(client._config, "password", None) is None


def test_a_server_started_without_a_file_finds_one_that_appears(tmp_path):
    """The one way to rescue a running server whose launcher named no file.

    Its environment cannot be changed from outside, but a .env placed in
    its working directory is found on the next 401 -- and remembered, so
    auth_status reports where the token now comes from.
    """
    client = FamilySearchClient(Config(access_token="stale", timeout=5))
    assert client._reload_token() is False
    env = _env(tmp_path, "fresh")  # the conftest runs each test from tmp_path
    assert client._reload_token() is True
    assert client._config.access_token == "fresh"
    assert client._config.env_file == env
