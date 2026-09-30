"""Client behaviour: the auth boundary, headers and error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp.client import FamilySearchApiError, FamilySearchClient
from familysearch_mcp.config import AuthRequiredError


@respx.mock
async def test_gazetteer_works_without_a_token(anon_config):
    """The place search is the one anonymous path; it must not demand auth."""
    route = respx.get("https://api.familysearch.org/platform/places/search").mock(
        return_value=httpx.Response(200, json={"entries": []})
    )
    async with FamilySearchClient(anon_config) as client:
        await client.get("/platform/places/search", q='name:"Kaskaskia"')
    assert "Authorization" not in route.calls.last.request.headers


async def test_authenticated_path_without_a_token_is_refused(anon_config):
    """Refuse locally rather than send a request that will fail confusingly."""
    async with FamilySearchClient(anon_config) as client:
        with pytest.raises(AuthRequiredError) as exc:
            await client.get("/platform/tree/persons/K2ZP-VY1")
    assert "FS_ACCESS_TOKEN" in str(exc.value)


@respx.mock
async def test_token_is_sent_as_bearer(auth_config):
    """A configured token travels as a bearer credential."""
    route = respx.get("https://api.familysearch.org/platform/tree/persons/K2ZP-VY1").mock(
        return_value=httpx.Response(200, json={"persons": []})
    )
    async with FamilySearchClient(auth_config) as client:
        await client.get("/platform/tree/persons/K2ZP-VY1")
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
async def test_integration_environment_uses_the_sandbox_host(auth_config):
    """The sandbox must not be mistaken for production."""
    auth_config.environment = "integration"
    route = respx.get("https://api-integ.familysearch.org/platform/tree/persons/X").mock(
        return_value=httpx.Response(200, json={"persons": []})
    )
    async with FamilySearchClient(auth_config) as client:
        await client.get("/platform/tree/persons/X")
    assert route.called


@respx.mock
async def test_error_status_is_preserved(auth_config):
    """A 401 (expired token) must be distinguishable from anything else."""
    respx.get("https://api.familysearch.org/platform/tree/persons/X").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    async with FamilySearchClient(auth_config) as client:
        with pytest.raises(FamilySearchApiError) as exc:
            await client.get("/platform/tree/persons/X")
    assert exc.value.status == 401


@respx.mock
async def test_no_content_is_an_empty_dict(auth_config):
    """A 204 is not an error and must not raise on JSON decoding."""
    respx.get("https://api.familysearch.org/platform/tree/persons/X").mock(
        return_value=httpx.Response(204)
    )
    async with FamilySearchClient(auth_config) as client:
        assert await client.get("/platform/tree/persons/X") == {}
