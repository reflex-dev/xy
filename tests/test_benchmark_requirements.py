from __future__ import annotations

import ast
from pathlib import Path


def _exact_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "-")) or "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.lower()] = version.split(" ;", 1)[0].strip()
    return pins


def test_benchmark_lock_contains_every_direct_pin() -> None:
    direct = _exact_pins(Path("benchmarks/requirements-ci.in"))
    locked = _exact_pins(Path("benchmarks/requirements-ci.lock"))

    assert direct
    assert {name: locked.get(name) for name in direct} == direct


def test_workflow_benchmark_explicitly_trusts_its_generated_chromium_html() -> None:
    source = Path("benchmarks/bench_workflows.py").read_text(encoding="utf-8")
    module = ast.parse(source)

    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to_png"
        and any(
            keyword.arg == "engine"
            and isinstance(keyword.value, ast.Attribute)
            and keyword.value.attr == "chromium"
            for keyword in node.keywords
        )
        and any(
            keyword.arg == "sandbox"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in node.keywords
        )
        for node in ast.walk(module)
    )
