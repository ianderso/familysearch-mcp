"""Tests over the MCP Registry listing: ``server.json`` and the README marker.

The registry lists what ``server.json`` says, and confirms that the PyPI
package is this project's by finding ``mcp-name: <name>`` in the README that
PyPI holds for that exact version. Nothing else fails if the three drift
apart; the release would, after PyPI had already accepted it.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from familysearch_mcp import __version__

ROOT = Path(__file__).parent.parent
SERVER_JSON = json.loads((ROOT / "server.json").read_text())
PACKAGE = SERVER_JSON["packages"][0]


def test_server_json_carries_the_package_version_twice():
    """The listing names a version, and so does the package it points at."""
    assert SERVER_JSON["version"] == __version__
    assert PACKAGE["version"] == __version__


def test_server_json_points_at_this_package_on_pypi():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert PACKAGE["registryType"] == "pypi"
    assert PACKAGE["identifier"] == project["name"]


def test_the_readme_carries_the_registry_marker_for_this_name():
    """Without it the registry refuses the listing as someone else's package.

    The token must end at a boundary: ``mcp-name: x/y.`` does not match.
    """
    marker = re.escape(f"mcp-name: {SERVER_JSON['name']}")
    assert re.search(marker + r"(\s|-->|<)", (ROOT / "README.md").read_text())


def test_server_json_declares_every_setting_the_server_reads():
    """A client configures the server from this list, so a gap is a setting nobody sets."""
    read = set(re.findall(r'"(FS_[A-Z_]+)"', (ROOT / "src/familysearch_mcp/config.py").read_text()))
    declared = {v["name"] for v in PACKAGE["environmentVariables"]}
    assert declared == read


def test_the_token_is_declared_secret_but_not_required():
    """A client masks a secret. Not required: the gazetteer works without one."""
    token = next(v for v in PACKAGE["environmentVariables"] if v["name"] == "FS_ACCESS_TOKEN")
    assert token["isSecret"] is True
    assert not token.get("isRequired")


def test_the_description_fits_the_registry_limit():
    """The MCP Registry refuses a description over 100 characters, after PyPI has the release."""
    assert len(SERVER_JSON["description"]) <= 100
