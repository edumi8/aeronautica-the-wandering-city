"""Single source of truth for cross-mod compatibility rules.

``scripts/validate.py`` (the build-time validator) and the test pipeline's
static validation suite both import from this module so the rule set can
never drift between "what blocks a build" and "what the tests assert".

To add a new compatibility rule: write a ``CompatRule`` and append it to
``CORE_RULES``. See ``TESTING.md`` -> "How to add a new mod compatibility
rule" for the full walkthrough.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

VersionMap = dict[str, str]
PinMap = dict[str, str | None]


@dataclass(frozen=True)
class CompatIssue:
    rule: str
    message: str


@dataclass(frozen=True)
class CompatRule:
    name: str
    description: str
    # check receives {slug: version_number} for every resolved mod and
    # {slug: pinned_version_or_None} for every mod listed in manifest.json's
    # source "mods" array. It returns an error message, or None if satisfied.
    check: Callable[[VersionMap, PinMap], str | None]


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    """Extract the leading dotted numeric run from a free-form mod version
    string, e.g. "1.20.1-forge-2.4.11" -> depends on caller pre-slicing;
    this helper just turns "2.4.11" -> (2, 4, 11). Non-numeric segments stop
    the parse. Used only for ordering comparisons, never for identity.
    """
    numbers = re.findall(r"\d+", version)
    return tuple(int(n) for n in numbers)


def _extract_after(version: str, marker: str) -> str | None:
    """Return the substring of ``version`` after the last occurrence of
    ``marker``, e.g. _extract_after("1.20.1-forge-2.4.11", "forge-") ->
    "2.4.11". Returns None if the marker is absent.
    """
    if marker not in version:
        return None
    return version.rsplit(marker, 1)[-1]


def _clockwork_requires_valkyrien_skies(versions: VersionMap, _pins: PinMap) -> str | None:
    """Historical, previously-shipped bug (see CHANGELOG 0.1.0-alpha.2):
    Clockwork 0.5.6 refuses to start against Valkyrien Skies < 2.4.6. Both
    mods embed their MC/loader tag in the version string
    (e.g. "1.20.1-forge-0.5.6"), so compare the trailing dotted run.
    """
    clockwork = versions.get("create-clockwork")
    vs = versions.get("valkyrien-skies")
    if not clockwork or not vs:
        return None

    clockwork_tail = _extract_after(clockwork, "forge-") or clockwork
    vs_tail = _extract_after(vs, "forge-") or vs
    clockwork_num = _parse_version_tuple(clockwork_tail)
    vs_num = _parse_version_tuple(vs_tail)

    if clockwork_num >= (0, 5, 6) and vs_num and vs_num < (2, 4, 6):
        return (
            f"Clockwork {clockwork} requires Valkyrien Skies 2.4.6 or newer, "
            f"but {vs} is selected. Update the 'valkyrien-skies' pin in "
            f"modpack/manifest.json to a compatible release (see CHANGELOG.md "
            f"0.1.0-alpha.2 for the original incident)."
        )
    return None


def _eureka_requires_valkyrien_skies(versions: VersionMap, _pins: PinMap) -> str | None:
    """Eureka ("Eureka! Ships! for Valkyrien Skies") is a Valkyrien Skies
    addon and cannot function without VS installed alongside it.
    """
    if "eureka" in versions and "valkyrien-skies" not in versions:
        return (
            "Eureka is selected but Valkyrien Skies is not present. Eureka "
            "is a Valkyrien Skies addon and requires it at runtime."
        )
    return None


def _physics_trio_pins_stay_aligned(_versions: VersionMap, pins: PinMap) -> str | None:
    """CONTRIBUTING.md: 'these mods participate in the same physics and
    movement ecosystem... keep them aligned unless a coordinated
    compatibility update has been validated'. Enforce that as a machine
    check: if any of the three carries an explicit version pin in
    manifest.json, all three present mods in the trio must be pinned too,
    so a dependency-resolution change cannot silently float one of them.
    """
    trio = ("create-clockwork", "valkyrien-skies", "eureka")
    present = [slug for slug in trio if slug in pins]
    if len(present) < 2:
        return None
    pinned = [slug for slug in present if pins.get(slug)]
    unpinned = [slug for slug in present if not pins.get(slug)]
    if pinned and unpinned:
        return (
            "The Clockwork / Valkyrien Skies / Eureka physics trio must be "
            "version-pinned together. Pinned: "
            f"{', '.join(pinned)}; missing an explicit 'version' in "
            f"manifest.json for: {', '.join(unpinned)}."
        )
    return None


CORE_RULES: tuple[CompatRule, ...] = (
    CompatRule(
        name="clockwork-requires-valkyrien-skies-2.4.6",
        description="Clockwork >=0.5.6 requires Valkyrien Skies >=2.4.6.",
        check=_clockwork_requires_valkyrien_skies,
    ),
    CompatRule(
        name="eureka-requires-valkyrien-skies",
        description="Eureka is a Valkyrien Skies addon and requires VS present.",
        check=_eureka_requires_valkyrien_skies,
    ),
    CompatRule(
        name="physics-trio-pins-aligned",
        description="Clockwork/Valkyrien Skies/Eureka pins must move together.",
        check=_physics_trio_pins_stay_aligned,
    ),
)


def evaluate(versions: VersionMap, pins: PinMap) -> list[CompatIssue]:
    issues: list[CompatIssue] = []
    for rule in CORE_RULES:
        message = rule.check(versions, pins)
        if message:
            issues.append(CompatIssue(rule=rule.name, message=message))
    return issues


def verify_core_compatibility(versions: VersionMap, pins: PinMap | None = None) -> None:
    """Backwards-compatible strict entry point used by scripts/validate.py:
    raises RuntimeError on the first violation instead of returning a list.
    """
    issues = evaluate(versions, pins or {})
    if issues:
        raise RuntimeError("Incompatible mod versions: " + issues[0].message)
