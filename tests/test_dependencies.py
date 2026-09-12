from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGE = ROOT / "python" / "xy"

# TEMPORARY, tracked in spec/design/reflex-integration.md § Status: the data
# plane needs Reflex's channel transport, which is unreleased, so `xy[reflex]`
# names an immutable commit instead of a version floor. A direct reference is
# unpublishable by design — a release cut from this tree fails at upload rather
# than shipping a floor that installs a Reflex where every chart stays blank.
# It is a commit and not the branch so that an install which bypasses the
# lockfile still gets the reviewed framework code. Restore the `>=<version>`
# assertion, and drop `test_docs_app_pins_the_same_reflex_commit`, when
# channels are released.
REFLEX_REQUIREMENT = (
    "git+https://github.com/benedikt-bartscher/reflex.git@609b2f515fc9d00e9a63a056d00a7782c77323b0"
)


def _dependency_name(requirement: str) -> str:
    requirement = requirement.split(";", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
    assert match is not None, requirement
    return match.group(1).replace("_", "-").lower()


def test_core_runtime_dependencies_do_not_include_reflex() -> None:
    data = tomllib.loads(ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = (data.get("project") or {}).get("dependencies") or []

    runtime_names = {_dependency_name(requirement) for requirement in dependencies}

    assert not any(name == "reflex" or name.startswith("reflex-") for name in runtime_names), (
        "plain xy must stay Reflex-free; publish the supported framework floor "
        "through the reflex extra"
    )


def test_core_publishes_only_the_reflex_optional_dependency() -> None:
    data = tomllib.loads(ROOT.joinpath("pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project") or {}
    groups = data.get("dependency-groups") or {}
    extras = project.get("optional-dependencies") or {}

    assert set(extras) == {"reflex"}
    assert any(
        _dependency_name(requirement) == "reflex" and REFLEX_REQUIREMENT in requirement
        for requirement in extras["reflex"]
    ), (
        "xy[reflex] must select the Reflex the adapter actually needs while the "
        "adapter source remains bundled in the xy distribution"
    )
    assert {"dev", "codspeed"} <= groups.keys()
    group_names = {
        _dependency_name(requirement)
        for requirements in groups.values()
        for requirement in requirements
        if isinstance(requirement, str)
    }
    assert "plotly" not in group_names, (
        "Plotly is an external comparison baseline installed by benchmark workflows, "
        "not an xy development or runtime dependency"
    )


def test_docs_app_pins_the_same_reflex_commit() -> None:
    """Six requirement strings name this commit; they have to agree.

    uv refuses two URLs for one package, so the docs app cannot resolve at all
    if its Reflex requirements drift from the root extra's — and a half-updated
    pin would otherwise only surface as a resolution error in a separate CI job.
    """
    docs = tomllib.loads(ROOT.joinpath("docs/app/pyproject.toml").read_text(encoding="utf-8"))
    requirements = (docs.get("project") or {}).get("dependencies") or []
    reflex_requirements = [
        requirement
        for requirement in requirements
        if _dependency_name(requirement).startswith("reflex")
    ]

    assert reflex_requirements, "the docs app must depend on Reflex"
    for requirement in reflex_requirements:
        assert REFLEX_REQUIREMENT in requirement, (
            f"docs/app pins a different Reflex than xy[reflex]: {requirement}"
        )


def test_core_package_does_not_import_reflex() -> None:
    forbidden = ("reflex", "reflex_core", "reflex_base")
    violations: list[str] = []
    for path in sorted(CORE_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    if root in forbidden or root.startswith("reflex_"):
                        violations.append(f"{path.relative_to(ROOT)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in forbidden or root.startswith("reflex_"):
                    violations.append(f"{path.relative_to(ROOT)} imports from {node.module}")

    assert violations == [], (
        "python/xy must stay framework-free; Reflex imports belong in the "
        f"bundled python/reflex_xy integration: {violations}"
    )
