"""Throttling. FamilySearch rate-limits, and a 429 must not read as a 404.

The client retries a throttled request once, after the server's
``Retry-After`` when that is short and a brief default when it is missing.
A longer wait is handed back rather than slept through, so a tool call never
hangs. Whatever is still refused comes back as an envelope that says what
happened and how long to wait.

No test here sleeps: the autouse ``slept`` fixture records each wait instead.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import (
    DEFAULT_RETRY_WAIT,
    MAX_RETRY_WAIT,
    SEARCH_URL,
    FamilySearchApiError,
    FamilySearchClient,
)

from .conftest import call_tool


@pytest.fixture
def authenticated(monkeypatch, auth_config):
    """Install a token-carrying client on the server."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    return auth_config


@respx.mock
async def test_a_429_surfaces_as_rate_limited_not_a_generic_api_error(authenticated):
    """Throttling is temporary; a caller told 'api_error' will not retry."""
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(429, json={"error": "Too Many Requests"})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "rate_limited"
    assert out["status"] == 429


@respx.mock
async def test_a_429_carries_retry_after_when_the_server_sends_one(authenticated):
    """The wait is the server's to state; passing it on saves a guess."""
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"}, json={})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["retry_after"] == 30


@respx.mock
async def test_a_429_without_retry_after_is_still_rate_limited(authenticated):
    """A missing header is a missing hint, not a different failure."""
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(429, json={})
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "rate_limited"
    assert out["retry_after"] is None


@respx.mock
async def test_a_date_form_retry_after_does_not_crash(authenticated):
    """Retry-After may be an HTTP-date; ignore it rather than raise on int()."""
    respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
            json={},
        )
    )
    out = await call_tool("get_person", person_id="K2ZP-VY1")
    assert out["error"] == "rate_limited"
    assert out["retry_after"] is None


@respx.mock
async def test_a_short_retry_after_is_waited_out_and_retried_once(auth_config, slept):
    """A throttle the server says will lift in seconds is not the caller's problem."""
    route = respx.get("https://api.familysearch.org/platform/tree/persons/X").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}, json={}),
            httpx.Response(200, json={"persons": []}),
        ]
    )
    async with FamilySearchClient(auth_config) as client:
        assert await client.get("/platform/tree/persons/X") == {"persons": []}
    assert route.call_count == 2
    assert slept == [3]


@respx.mock
async def test_a_429_with_no_retry_after_waits_the_default(auth_config, slept):
    """A missing header is a missing hint: wait briefly rather than not at all."""
    route = respx.get("https://api.familysearch.org/platform/tree/persons/X").mock(
        side_effect=[httpx.Response(429, json={}), httpx.Response(200, json={})]
    )
    async with FamilySearchClient(auth_config) as client:
        await client.get("/platform/tree/persons/X")
    assert route.call_count == 2
    assert slept == [DEFAULT_RETRY_WAIT]


@respx.mock
async def test_the_retry_happens_once_not_in_a_loop(auth_config, slept):
    """A throttle that persists is reported, not hammered."""
    route = respx.get("https://api.familysearch.org/platform/tree/persons/X").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}, json={})
    )
    async with FamilySearchClient(auth_config) as client:
        with pytest.raises(FamilySearchApiError) as exc:
            await client.get("/platform/tree/persons/X")
    assert exc.value.status == 429
    assert exc.value.retry_after == 1
    assert route.call_count == 2
    assert slept == [1]


@respx.mock
async def test_a_long_retry_after_is_handed_back_not_slept(auth_config, slept):
    """A tool call that blocks for minutes looks hung; the caller decides."""
    route = respx.get("https://api.familysearch.org/platform/tree/persons/X").mock(
        return_value=httpx.Response(429, headers={"Retry-After": str(MAX_RETRY_WAIT + 1)}, json={})
    )
    async with FamilySearchClient(auth_config) as client:
        with pytest.raises(FamilySearchApiError) as exc:
            await client.get("/platform/tree/persons/X")
    assert exc.value.retry_after == MAX_RETRY_WAIT + 1
    assert route.call_count == 1
    assert slept == []


@respx.mock
async def test_the_record_search_retries_a_short_throttle(auth_config, slept):
    """The search goes to a different host by a different method; same rule."""
    route = respx.get(SEARCH_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}, json={}),
            httpx.Response(200, json={"results": 1}),
        ]
    )
    async with FamilySearchClient(auth_config) as client:
        assert (await client.search({"q.surname": "Smith"}))["results"] == 1
    assert route.call_count == 2
    assert slept == [2]


@respx.mock
async def test_an_image_download_retries_a_short_throttle(auth_config, slept):
    """The download does not go through get(), so it carries its own retry."""
    url = "https://sg30p0.familysearch.org/service/records/storage/das/v2/n/dist.jpg"
    route = respx.get(url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, content=b"\xff\xd8page"),
        ]
    )
    async with FamilySearchClient(auth_config) as client:
        assert await client.download(url) == b"\xff\xd8page"
    assert route.call_count == 2
    assert slept == [1]


@respx.mock
async def test_rate_limiting_is_distinguishable_from_the_credential_failures(
    authenticated,
):
    """429, 401 and 403 each need a different response from the caller."""
    route = respx.get("https://api.familysearch.org/platform/tree/persons/X")
    seen = set()
    for status in (401, 403, 429):
        route.mock(return_value=httpx.Response(status, json={}))
        seen.add((await call_tool("get_person", person_id="X"))["error"])
    assert len(seen) == 3
