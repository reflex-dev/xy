"""Shared stdlib-only dependency checks for xy release artifacts."""

from __future__ import annotations

import re
from email.message import Message

BASE_DEPENDENCY_FLOORS = (("anywidget", "0.9"), ("numpy", "1.24"))
REFLEX_REQUIREMENT = "Requires-Dist: reflex>=0.9.6; extra == 'reflex'"


def _dependency_name(requirement: str) -> str:
    requirement = requirement.split(";", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
    return "" if match is None else match.group(1).replace("_", "-").lower()


def _is_valid_base_requirement(requirement: str, package: str, minimum: str) -> bool:
    """Require the exact stable numeric floor, without markers or conflicts."""
    match = re.fullmatch(
        rf"\s*{re.escape(package)}\s*"
        rf">=\s*(?P<version>[0-9]+(?:\.[0-9]+)*)\s*",
        requirement,
        flags=re.IGNORECASE,
    )
    if match is None:
        return False
    version = tuple(int(part) for part in match.group("version").split("."))
    floor = tuple(int(part) for part in minimum.split("."))
    width = max(len(version), len(floor))
    return version + (0,) * (width - len(version)) == floor + (0,) * (width - len(floor))


def _is_exact_reflex_extra(requirement: str) -> bool:
    """Accept whitespace/quote normalization, but no extra constraints."""
    return bool(
        re.fullmatch(
            r"\s*reflex\s*>=\s*0\.9\.6\s*;\s*extra\s*==\s*['\"]reflex['\"]\s*",
            requirement,
            flags=re.IGNORECASE,
        )
    )


def dependency_metadata_errors(metadata: Message) -> list[str]:
    """Return violations of xy's base/optional dependency metadata policy."""
    requirements = metadata.get_all("Requires-Dist") or []
    errors: list[str] = []

    for package, minimum in BASE_DEPENDENCY_FLOORS:
        package_requirements = [
            requirement for requirement in requirements if _dependency_name(requirement) == package
        ]
        if len(package_requirements) != 1 or not _is_valid_base_requirement(
            package_requirements[0], package, minimum
        ):
            errors.append(
                f"Requires-Dist: {package}>={minimum} "
                "(exactly one requirement, with no conflicts; exact stable lower bound required)"
            )

    reflex_requirements = [
        requirement for requirement in requirements if _dependency_name(requirement) == "reflex"
    ]
    if len(reflex_requirements) != 1 or not _is_exact_reflex_extra(reflex_requirements[0]):
        errors.append(f"{REFLEX_REQUIREMENT} (exactly one requirement, with no conflicts)")

    base_floors = dict(BASE_DEPENDENCY_FLOORS)
    unexpected_requirements = []
    for requirement in requirements:
        name = _dependency_name(requirement)
        base_minimum = base_floors.get(name)
        if base_minimum is not None and _is_valid_base_requirement(requirement, name, base_minimum):
            continue
        if _is_exact_reflex_extra(requirement):
            continue
        unexpected_requirements.append(requirement)
    if unexpected_requirements:
        errors.append(
            "only xy base dependencies plus the Reflex extra in Requires-Dist "
            f"({unexpected_requirements})"
        )

    provided_extras = {extra.strip().lower() for extra in metadata.get_all("Provides-Extra") or []}
    if provided_extras != {"reflex"}:
        errors.append(f"Provides-Extra: reflex (got {sorted(provided_extras)})")
    return errors
