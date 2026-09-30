"""Tests for the sweep's own argument builder and drift guard.

The auth boundary is this project's load-bearing property, and the sweep that
checks it is only as good as the arguments it invokes tools with. When those
stop being valid, the tool returns a tidy error envelope, the sweep's
assertion passes, and the boundary stops being tested. That happened here
once already.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import (
    LOCAL_VALIDATION_ERRORS,
    assert_reached_body,
    valid_args,
)


class _Tool:
    """A stand-in for a registered tool, carrying only what the builder reads."""

    def __init__(self, name: str, schema: dict):
        self.name = name
        self.input_schema = schema


def _schema(required: list[str] | None, **props) -> dict:
    return {"type": "object", "properties": props, "required": required}


# --------------------------------------------------------------------------- #
# The drift guard
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("code", sorted(LOCAL_VALIDATION_ERRORS))
async def test_the_guard_fires_on_every_local_validation_error(code):
    """Each of these means the sweep never reached the tool's body."""
    with pytest.raises(AssertionError) as exc:
        assert_reached_body("some_tool", {"error": code, "message": "nope"})
    assert "did not test it" in str(exc.value)
    assert "some_tool" in str(exc.value)


async def test_the_guard_names_the_fix():
    """An assertion nobody can act on is a worse failure than none."""
    with pytest.raises(AssertionError) as exc:
        assert_reached_body("search_records", {"error": "no_criteria"})
    assert "ARGUMENT_HINTS" in str(exc.value)


async def test_the_guard_lets_an_auth_refusal_through():
    """auth_required is exactly what the boundary sweep is looking for."""
    assert_reached_body("get_person", {"error": "auth_required", "message": "x"})


async def test_the_guard_lets_an_api_failure_through():
    """A 429 or a 500 is the tool working, not the sweep misfiring."""
    assert_reached_body("get_record", {"error": "rate_limited", "status": 429})


# --------------------------------------------------------------------------- #
# The builder
# --------------------------------------------------------------------------- #
async def test_an_empty_string_default_is_not_used_as_a_value():
    """A search term of "" is exactly what makes a tool answer no_criteria.

    Every optional parameter here defaults to "", so a builder that trusted
    defaults would supply nothing and never reach the auth check. This is
    the bug the guard caught.
    """
    tool = _Tool("search_records", _schema(None, surname={"type": "string", "default": ""}))
    assert valid_args(tool)["surname"] == "Pettibone"


async def test_a_meaningful_default_is_still_honoured():
    """A real default is the tool's own idea of a sensible value."""
    tool = _Tool("t", _schema(["count"], count={"type": "integer", "default": 20}))
    assert valid_args(tool)["count"] == 20


@pytest.mark.parametrize(
    ("name", "check"),
    [
        ("image_ark", lambda v: v.startswith("3:1:")),
        ("ark", lambda v: bool(v) and " " not in v),
        ("person_id", lambda v: bool(v)),
        ("record_type_code", lambda v: str(v).isdigit()),
        ("collection_id", lambda v: str(v).isdigit()),
        ("place_id", lambda v: str(v).isdigit()),
        ("image_url", lambda v: v.startswith("https://")),
        ("birth_year", lambda v: v == 1850),
    ],
)
async def test_parameter_names_drive_plausible_values(name, check):
    """Names carry meaning the schema does not.

    record_type_code must be numeric or the tool refuses it locally, and an
    image_ark has a shape. A generic string satisfies neither.
    """
    tool = _Tool("t", _schema([name], **{name: {"type": "string"}}))
    assert check(valid_args(tool)[name])


async def test_a_destination_is_a_real_writable_directory():
    """A tool that writes a file checks its parent before fetching anything."""
    tool = _Tool("t", _schema(["destination"], destination={"type": "string"}))
    assert Path(valid_args(tool)["destination"]).parent.is_dir()


async def test_a_tool_with_no_required_parameters_still_gets_a_term():
    """Search and browse tools declare everything optional but refuse empty."""
    tool = _Tool(
        "browse_waypoints",
        _schema(
            None,
            collection_id={"type": "string", "default": ""},
            waypoint_id={"type": "string", "default": ""},
        ),
    )
    assert valid_args(tool)["collection_id"] == "1417683"


async def test_a_required_parameter_is_never_skipped_for_a_search_term():
    """The search-term fallback is for tools that require nothing."""
    tool = _Tool(
        "t", _schema(["ark"], ark={"type": "string"}, surname={"type": "string", "default": ""})
    )
    args = valid_args(tool)
    assert "ark" in args
    assert "surname" not in args


async def test_overrides_win_over_everything_derived():
    """A caller testing a specific case must be able to force a value."""
    tool = _Tool("t", _schema(["ark"], ark={"type": "string"}))
    assert valid_args(tool, ark="ZZZZ-999")["ark"] == "ZZZZ-999"


async def test_none_required_is_treated_as_no_requirements():
    """The schema reports `required: null`, not an empty list."""
    assert valid_args(_Tool("auth_status", _schema(None))) == {}
