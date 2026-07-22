from __future__ import annotations

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
