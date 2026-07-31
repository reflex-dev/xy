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


def _dependency_satisfies_floor(requirement: str, package: str, minimum: str) -> bool:
    return bool(
        re.match(
            rf"^\s*{re.escape(package)}\s*(?:\[[^\]]+\])?\s*>=\s*"
            rf"{re.escape(minimum)}(?:\b|[,;\s])",
            requirement,
            flags=re.IGNORECASE,
        )
    )


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
        if not any(
            _dependency_satisfies_floor(requirement, package, minimum)
            for requirement in requirements
        ):
            errors.append(f"Requires-Dist: {package}>={minimum}")

    reflex_requirements = [
        requirement for requirement in requirements if _dependency_name(requirement) == "reflex"
    ]
    if len(reflex_requirements) != 1 or not _is_exact_reflex_extra(reflex_requirements[0]):
        errors.append(f"{REFLEX_REQUIREMENT} (exactly one requirement, with no conflicts)")

    unexpected_requirements = []
    for requirement in requirements:
        name = _dependency_name(requirement)
        if name in {"anywidget", "numpy"} and ";" not in requirement:
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
