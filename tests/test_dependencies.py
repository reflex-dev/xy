from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGE = ROOT / "python" / "xy"


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
        _dependency_name(requirement) == "reflex" and ">=0.9.6" in requirement
        for requirement in extras["reflex"]
    ), (
        "xy[reflex] must select the supported Reflex floor while the adapter "
        "source remains bundled in the xy distribution"
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
