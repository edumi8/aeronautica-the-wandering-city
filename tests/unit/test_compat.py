"""Unit tests for the shared compatibility matrix (scripts/validate.py and
the test pipeline both import this -- see compat.py docstring)."""
from __future__ import annotations

import pytest

from aeronautica_testing import compat


def test_clean_pinned_trio_has_no_issues():
    versions = {
        "create-clockwork": "1.20.1-forge-0.5.6",
        "valkyrien-skies": "1.20.1-forge-2.4.11",
        "eureka": "1.20.1-forge-1.6.3",
    }
    pins = {"create-clockwork": "1.20.1-forge-0.5.6", "valkyrien-skies": "1.20.1-forge-2.4.11", "eureka": "1.20.1-forge-1.6.3"}
    assert compat.evaluate(versions, pins) == []


def test_clockwork_requires_valkyrien_skies_2_4_6_or_newer():
    versions = {"create-clockwork": "1.20.1-forge-0.5.6", "valkyrien-skies": "1.20.1-forge-2.4.5"}
    issues = compat.evaluate(versions, {})
    assert any(i.rule == "clockwork-requires-valkyrien-skies-2.4.6" for i in issues)


def test_clockwork_with_sufficiently_new_valkyrien_skies_is_clean():
    versions = {"create-clockwork": "1.20.1-forge-0.5.6", "valkyrien-skies": "1.20.1-forge-2.4.11"}
    issues = compat.evaluate(versions, {})
    assert not any(i.rule == "clockwork-requires-valkyrien-skies-2.4.6" for i in issues)


def test_clockwork_without_valkyrien_skies_present_is_not_flagged_by_this_rule():
    # Absence of VS entirely is a *different* problem (a hard install/build
    # failure upstream); this rule only fires when both are present.
    versions = {"create-clockwork": "1.20.1-forge-0.5.6"}
    issues = compat.evaluate(versions, {})
    assert not any(i.rule == "clockwork-requires-valkyrien-skies-2.4.6" for i in issues)


def test_eureka_requires_valkyrien_skies_present():
    versions = {"eureka": "1.20.1-forge-1.6.3"}
    issues = compat.evaluate(versions, {})
    assert any(i.rule == "eureka-requires-valkyrien-skies" for i in issues)


def test_eureka_with_valkyrien_skies_is_clean():
    versions = {"eureka": "1.20.1-forge-1.6.3", "valkyrien-skies": "1.20.1-forge-2.4.11"}
    issues = compat.evaluate(versions, {})
    assert not any(i.rule == "eureka-requires-valkyrien-skies" for i in issues)


def test_physics_trio_partial_pin_is_flagged():
    versions = {"create-clockwork": "x", "valkyrien-skies": "y"}
    pins = {"create-clockwork": "x", "valkyrien-skies": None}
    issues = compat.evaluate(versions, pins)
    assert any(i.rule == "physics-trio-pins-aligned" for i in issues)


def test_physics_trio_fully_pinned_is_clean():
    pins = {"create-clockwork": "a", "valkyrien-skies": "b", "eureka": "c"}
    issues = compat.evaluate({}, pins)
    assert not any(i.rule == "physics-trio-pins-aligned" for i in issues)


def test_physics_trio_fully_unpinned_is_not_flagged():
    # Nothing pinned at all is a legitimate (if less strict) state; the rule
    # only fires on a *mix* of pinned/unpinned within the trio.
    pins: dict[str, str | None] = {}
    issues = compat.evaluate({}, pins)
    assert not any(i.rule == "physics-trio-pins-aligned" for i in issues)


def test_verify_core_compatibility_raises_on_violation():
    versions = {"create-clockwork": "1.20.1-forge-0.5.6", "valkyrien-skies": "1.20.1-forge-2.4.5"}
    with pytest.raises(RuntimeError, match="Incompatible mod versions"):
        compat.verify_core_compatibility(versions)


def test_verify_core_compatibility_does_not_raise_when_clean():
    versions = {"create-clockwork": "1.20.1-forge-0.5.6", "valkyrien-skies": "1.20.1-forge-2.4.11"}
    compat.verify_core_compatibility(versions)  # must not raise
