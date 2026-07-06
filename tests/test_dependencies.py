from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        "fastcharts core must stay Reflex-free; put Reflex support in the example app "
        "or a separate optional adapter package"
    )
