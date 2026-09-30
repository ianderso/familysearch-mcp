"""Resolving a record to a readable page image, and fetching it.

This is the step that turns a citation into evidence, and it has one trap:
the image routes redirect to a presigned S3 URL, which rejects the request if
the bearer header is carried across. Verified live 2026-09-23.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from familysearch_mcp import server
from familysearch_mcp.client import (
    FamilySearchApiError,
    FamilySearchClient,
    fetch_binary,
)

from .conftest import call_tool

IMAGE_ARK = "3:1:33SQ-G5LD-93NY"
NODE = (
    "https://sg30p0.familysearch.org/service/records/storage/dascloud/das/v2/TH-1942-22242-30207-51"
)
IMAGE_URL = f"{NODE}/dist.jpg"
PRESIGNED = (
    "https://ps-services-us-east-1.s3.amazonaws.com/TH-1942-22242-30207-51"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef"
)
JPEG = b"\xff\xd8\xff\xe0" + b"padding" * 40

#: Trimmed from the live image resource for ark 3:1:33SQ-G5LD-93NY.
LIVE_IMAGE_RESOURCE = {
    "links": {
        "image-node": {"href": NODE},
        "image-deepzoom": {
            "href": "https://sg30p0.familysearch.org/service/records/storage/"
            "deepzoomcloud/dz/v1/TH-1942-22242-30207-51/image.xml"
        },
        "image-stream-image-dist": {"href": IMAGE_URL},
        "image-stream-image-thumb_p200": {"href": f"{NODE}/thumb_p200.jpg"},
        "image-stream-image-thumb_128": {"href": f"{NODE}/thumb_128.jpg"},
        "next": {"href": "https://www.familysearch.org/ark:/61903/3:1:33SQ-G5LD-93X5"},
        "prev": {"href": "https://www.familysearch.org/ark:/61903/3:1:33S7-95LD-93XQ"},
        "records": {
            "href": f"https://www.familysearch.org/platform/records/images/{IMAGE_ARK}/records"
        },
    }
}


# --------------------------------------------------------------------------- #
# get_image_links
# --------------------------------------------------------------------------- #
@respx.mock
async def test_image_links_separate_the_full_page_from_thumbnails(monkeypatch, auth_config):
    """A caller needs the readable page, not whichever stream came first."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE_ARK}").mock(
        return_value=httpx.Response(200, json=LIVE_IMAGE_RESOURCE)
    )
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert out["full_image"] == IMAGE_URL
    assert set(out["thumbnails"]) == {"thumb_p200", "thumb_128"}
    assert "dist" not in out["thumbnails"]


@respx.mock
async def test_image_links_report_the_neighbouring_pages(monkeypatch, auth_config):
    """The entry you want is often not the page the index pointed at."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE_ARK}").mock(
        return_value=httpx.Response(200, json=LIVE_IMAGE_RESOURCE)
    )
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert out["next_image"].endswith("93X5")
    assert out["previous_image"].endswith("93XQ")


@respx.mock
async def test_a_full_ark_url_is_accepted_not_just_the_bare_id(monkeypatch, auth_config):
    """Callers paste what get_record_image gave them, which is a full ark."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    route = respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE_ARK}").mock(
        return_value=httpx.Response(200, json=LIVE_IMAGE_RESOURCE)
    )
    await call_tool(
        "get_image_links",
        image_ark=f"https://www.familysearch.org/ark:/61903/{IMAGE_ARK}",
    )
    assert route.called


# --------------------------------------------------------------------------- #
# The redirect trap
# --------------------------------------------------------------------------- #
@respx.mock
async def test_the_bearer_header_is_dropped_on_the_storage_redirect():
    """Carrying the token onto the presigned URL is rejected by S3.

    The live error is ``InvalidArgument: Only one auth mechanism allowed`` --
    the signature in the query string is already the credential. This is the
    whole reason fetch_binary exists rather than a plain follow-redirects.
    """
    first = respx.get(IMAGE_URL).mock(
        return_value=httpx.Response(302, headers={"location": PRESIGNED})
    )
    second = respx.get(PRESIGNED).mock(return_value=httpx.Response(200, content=JPEG))
    data = await fetch_binary(IMAGE_URL, "test-token")
    assert data == JPEG
    assert first.calls.last.request.headers["Authorization"] == "Bearer test-token"
    assert "Authorization" not in second.calls.last.request.headers


@respx.mock
async def test_an_image_served_without_a_redirect_still_works():
    """Thumbnails answer directly; do not require a redirect to exist."""
    respx.get(f"{NODE}/thumb_128.jpg").mock(return_value=httpx.Response(200, content=JPEG))
    assert await fetch_binary(f"{NODE}/thumb_128.jpg", "t") == JPEG


@respx.mock
async def test_a_redirect_without_a_location_is_an_error_not_a_hang():
    """A malformed redirect must fail loudly."""
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(302))
    with pytest.raises(FamilySearchApiError):
        await fetch_binary(IMAGE_URL, "t")


@respx.mock
async def test_an_access_restricted_image_surfaces_its_status():
    """Some collections are restricted; the caller needs to know which."""
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(403, text="denied"))
    with pytest.raises(FamilySearchApiError) as exc:
        await fetch_binary(IMAGE_URL, "t")
    assert exc.value.status == 403


# --------------------------------------------------------------------------- #
# download_image
# --------------------------------------------------------------------------- #
@respx.mock
async def test_download_writes_the_file_and_reports_its_size(monkeypatch, auth_config, tmp_path):
    """The bytes go to disk; a page scan is not a tool result."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(200, content=JPEG))
    target = tmp_path / "manifest.jpg"
    out = await call_tool("download_image", image_url=IMAGE_URL, destination=str(target))
    assert out["bytes"] == len(JPEG)
    assert out["format"] == "jpeg"
    assert target.read_bytes() == JPEG


async def test_download_refuses_a_directory_that_does_not_exist(monkeypatch, auth_config, tmp_path):
    """Fail before spending the download on a path that cannot be written."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool(
        "download_image",
        image_url=IMAGE_URL,
        destination=str(tmp_path / "nope" / "x.jpg"),
    )
    assert out["error"] == "no_such_directory"


@respx.mock
async def test_download_reports_a_non_jpeg_rather_than_claiming_one(
    monkeypatch, auth_config, tmp_path
):
    """An error page saved as .jpg would look like a successful download."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(200, content=b"<html>nope</html>"))
    out = await call_tool(
        "download_image",
        image_url=IMAGE_URL,
        destination=str(tmp_path / "x.jpg"),
    )
    assert out["format"] == "unknown"


async def test_download_refuses_without_a_token(monkeypatch, anon_config, tmp_path):
    """No token means no request, and a message naming what to set."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    out = await call_tool(
        "download_image",
        image_url=IMAGE_URL,
        destination=str(tmp_path / "x.jpg"),
    )
    assert out["error"] == "auth_required"
    assert "FS_ACCESS_TOKEN" in out["message"]


async def test_download_refuses_an_ark_mistaken_for_a_url(monkeypatch, auth_config, tmp_path):
    """A caller passing the ark instead of the URL gets told, not a stack trace."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool(
        "download_image",
        image_url="3:1:33SQ-G5LD-93NY",
        destination=str(tmp_path / "x.jpg"),
    )
    assert out["error"] == "invalid_image_url"


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/collect.jpg",
        "https://familysearch.org.attacker.example/dist.jpg",
        "https://attacker.example/?u=https://sg30p0.familysearch.org/dist.jpg",
        "http://sg30p0.familysearch.org/service/records/dist.jpg",
    ],
)
@respx.mock
async def test_download_refuses_a_url_that_would_carry_the_token_elsewhere(
    monkeypatch, auth_config, tmp_path, url
):
    """The request carries the bearer token, and the URL is a tool argument.

    A description, memory or change-log reason that talked the model into
    passing its own URL would otherwise receive the token. Plain http would
    send it in the clear.
    """
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    out = await call_tool("download_image", image_url=url, destination=str(tmp_path / "x.jpg"))
    assert out["error"] == "invalid_image_url"
    assert not respx.calls


@respx.mock
async def test_fetch_binary_never_sends_the_token_off_familysearch():
    """Defence in depth, below the tool's own check."""
    route = respx.get("https://elsewhere.example/p.jpg").mock(
        return_value=httpx.Response(200, content=JPEG)
    )
    await fetch_binary("https://elsewhere.example/p.jpg", "test-token")
    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.parametrize(
    "name",
    [
        "Library/LaunchAgents/x.plist",
        ".ssh/authorized_keys",
        ".zshrc",
        "site-packages/evil.pth",
        "page.jpg.sh",
    ],
)
@respx.mock
async def test_download_creates_only_an_image_or_pdf(monkeypatch, auth_config, tmp_path, name):
    """A destination the system would act on is refused before any request.

    The URL may be a memory another user uploaded, and the destination
    whatever injected text persuaded the model to name.
    """
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    out = await call_tool("download_image", image_url=IMAGE_URL, destination=str(target))
    assert out["error"] == "invalid_destination"
    assert not target.exists()
    assert not respx.calls


@respx.mock
async def test_an_uppercase_image_suffix_is_accepted(monkeypatch, auth_config, tmp_path):
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(IMAGE_URL).mock(return_value=httpx.Response(200, content=JPEG))
    out = await call_tool(
        "download_image", image_url=IMAGE_URL, destination=str(tmp_path / "P1.JPG")
    )
    assert out["bytes"] == len(JPEG)


@respx.mock
async def test_download_never_overwrites_an_existing_file(monkeypatch, auth_config, tmp_path):
    """The destination is a tool argument; an existing file is left alone."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    target = tmp_path / "page-1.jpg"
    target.write_text("a page already read")
    out = await call_tool("download_image", image_url=IMAGE_URL, destination=str(target))
    assert out["error"] == "file_exists"
    assert target.read_text() == "a page already read"
    assert not respx.calls


@respx.mock
async def test_a_file_created_during_the_download_is_not_overwritten(
    monkeypatch, auth_config, tmp_path
):
    """The existence check and the write are separate; the write is exclusive."""
    monkeypatch.setattr(server.state, "config", auth_config)
    client = FamilySearchClient(auth_config)
    monkeypatch.setattr(server.state, "client", client)
    target = tmp_path / "page.jpg"

    async def download_then_race(url: str) -> bytes:
        target.write_bytes(b"written meanwhile")
        return JPEG

    monkeypatch.setattr(client, "download", download_then_race)
    out = await call_tool("download_image", image_url=IMAGE_URL, destination=str(target))
    assert out["error"] == "file_exists"
    assert target.read_bytes() == b"written meanwhile"


# --------------------------------------------------------------------------- #
# Film and image number addressing
# --------------------------------------------------------------------------- #
FILM_THUMB = (
    "https://sg30p0.familysearch.org/service/records/storage/dascloud/das/v2/"
    "dgs:004893581_00213/thumb_p200.jpg"
)


def test_a_film_image_node_pads_the_image_number():
    """The storage id wants five digits; 213 is not 00213."""
    from familysearch_mcp.client import film_image_node

    assert film_image_node("004893581", 213) == "dgs:004893581_00213"


def test_leading_zeros_in_the_film_number_are_kept():
    """They are part of the number, not formatting.

    Treating a film number as an integer silently addresses a different
    film, which is why it is a string all the way through.
    """
    from familysearch_mcp.client import film_image_node

    assert film_image_node("004893581", 1).startswith("dgs:004893581_")


@respx.mock
async def test_a_real_film_image_reports_that_it_exists(monkeypatch, anon_config):
    """The thumbnail is the existence check, and needs no token."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    route = respx.get(FILM_THUMB).mock(
        return_value=httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})
    )
    out = await call_tool("get_film_image", film_number="004893581", image_number=213)
    assert out["exists"] is True
    assert out["storage_node"] == "dgs:004893581_00213"
    assert "Authorization" not in route.calls.last.request.headers


@respx.mock
async def test_a_missing_film_image_says_so_rather_than_handing_back_a_url(
    monkeypatch, anon_config
):
    """A wrong film or image number should be a clear answer, not a 404 later."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    respx.get(FILM_THUMB).mock(return_value=httpx.Response(404))
    out = await call_tool("get_film_image", film_number="004893581", image_number=213)
    assert out["exists"] is False
    assert "Check both" in out["message"]


@respx.mock
async def test_an_html_error_page_is_not_mistaken_for_an_image(monkeypatch, anon_config):
    """A 200 carrying HTML is a failure dressed as success."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    respx.get(FILM_THUMB).mock(
        return_value=httpx.Response(
            200, content=b"<html>no</html>", headers={"content-type": "text/html"}
        )
    )
    out = await call_tool("get_film_image", film_number="004893581", image_number=213)
    assert out["exists"] is False


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"film_number": "not-digits", "image_number": 1}, "invalid_film_number"),
        ({"film_number": "004893581", "image_number": 0}, "invalid_image_number"),
        ({"film_number": "004893581", "image_number": -5}, "invalid_image_number"),
    ],
)
async def test_bad_arguments_are_refused_locally(monkeypatch, anon_config, args, expected):
    """Catch it here rather than construct a nonsense storage id."""
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    assert (await call_tool("get_film_image", **args))["error"] == expected


# --------------------------------------------------------------------------- #
# The thin anonymous image resource
# --------------------------------------------------------------------------- #
@respx.mock
async def test_missing_image_links_are_explained_not_reported_as_absent(monkeypatch, anon_config):
    """Without a token the resource answers 200 with the streams omitted.

    Verified live 2026-09-23: an unauthenticated read returns next, prev,
    records and self only. Passing that through unmarked would read as an
    image with no files rather than as a missing credential.
    """
    monkeypatch.setattr(server.state, "config", anon_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(anon_config))
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE_ARK}").mock(
        return_value=httpx.Response(
            200,
            json={
                "links": {
                    "next": {"href": "https://x/next"},
                    "prev": {"href": "https://x/prev"},
                    "records": {"href": "https://x/records"},
                    "self": {"href": "https://x/self"},
                }
            },
        )
    )
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert out["images_require_token"] is True
    assert "No token is configured" in out["message"]
    assert out["next_image"] == "https://x/next"


@respx.mock
async def test_a_full_response_carries_no_token_warning(monkeypatch, auth_config):
    """With a token the streams are present and there is nothing to explain."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(f"https://api.familysearch.org/platform/records/images/{IMAGE_ARK}").mock(
        return_value=httpx.Response(200, json=LIVE_IMAGE_RESOURCE)
    )
    current_user = respx.get(CURRENT_USER).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert "images_require_token" not in out
    assert "image_restricted" not in out
    assert out["full_image"] == IMAGE_URL
    # A full answer needs no second opinion on the token.
    assert not current_user.called


# --------------------------------------------------------------------------- #
# The thin document with a token: expired, or withheld?
# --------------------------------------------------------------------------- #
IMAGE_RESOURCE = f"https://api.familysearch.org/platform/records/images/{IMAGE_ARK}"
CURRENT_USER = "https://api.familysearch.org/platform/users/current"
THIN = {
    "links": {
        "records": {"href": "https://x/records"},
        "self": {"href": "https://x/self"},
    }
}


@respx.mock
async def test_a_valid_token_with_no_image_links_reports_a_restricted_image(
    monkeypatch, auth_config
):
    """The reported case: a withheld image was blamed on a missing token.

    Reported from real use: get_image_links on a withheld image said "no
    token is configured" while auth_status said authenticated. Re-checked
    live 2026-09-28 with a token the current-user read accepted: the image
    resource still came back with no image links. The token was fine; the
    image is withheld from the account.
    """
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(IMAGE_RESOURCE).mock(return_value=httpx.Response(200, json=THIN))
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(200, json={}))
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert out["image_restricted"] is True
    assert "images_require_token" not in out
    assert "no token" not in out["message"].lower()
    assert out["records_on_this_image"] == "https://x/records"


@respx.mock
async def test_an_expired_token_is_refreshed_and_the_image_asked_for_again(
    monkeypatch, auth_config, tmp_path
):
    """The image resource never says 401, so recovery must be provoked.

    Verified live 2026-09-28: an invalid token gets the same 200 and the same
    thin document as no token at all.
    """
    env = tmp_path / "fs.env"
    env.write_text("FS_ACCESS_TOKEN=fresh\n")
    auth_config.env_file = str(env)
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))

    def image(request):
        fresh = request.headers["authorization"] == "Bearer fresh"
        return httpx.Response(200, json=LIVE_IMAGE_RESOURCE if fresh else THIN)

    def current_user(request):
        fresh = request.headers["authorization"] == "Bearer fresh"
        return httpx.Response(200 if fresh else 401, json={})

    respx.get(IMAGE_RESOURCE).mock(side_effect=image)
    respx.get(CURRENT_USER).mock(side_effect=current_user)
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert out["full_image"] == IMAGE_URL
    assert "message" not in out


@respx.mock
async def test_a_dead_token_with_no_image_links_reports_token_rejected(monkeypatch, auth_config):
    """Not a restricted image, and not "no token": the token is refused."""
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    respx.get(IMAGE_RESOURCE).mock(return_value=httpx.Response(200, json=THIN))
    respx.get(CURRENT_USER).mock(return_value=httpx.Response(401, json={}))
    out = await call_tool("get_image_links", image_ark=IMAGE_ARK)
    assert out["error"] == "token_rejected"


@respx.mock
async def test_download_recovers_from_an_expired_token(monkeypatch, auth_config, tmp_path):
    """The image host does say 401, but download used to bypass recovery.

    It fetched through its own path rather than the client's, so a
    refreshed token on disk was never adopted there.
    """
    env = tmp_path / "fs.env"
    env.write_text("FS_ACCESS_TOKEN=fresh\n")
    auth_config.env_file = str(env)
    monkeypatch.setattr(server.state, "config", auth_config)
    monkeypatch.setattr(server.state, "client", FamilySearchClient(auth_config))
    seen: list[str] = []

    def host(request):
        seen.append(request.headers.get("authorization"))
        ok = request.headers.get("authorization") == "Bearer fresh"
        return httpx.Response(200, content=JPEG) if ok else httpx.Response(401)

    respx.get(IMAGE_URL).mock(side_effect=host)
    target = tmp_path / "page.jpg"
    out = await call_tool("download_image", image_url=IMAGE_URL, destination=str(target))
    assert out["bytes"] == len(JPEG)
    assert seen == ["Bearer test-token", "Bearer fresh"]
