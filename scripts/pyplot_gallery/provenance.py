"""Portable interpreter provenance for gallery reports and result caches."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def current_python_interpreter() -> dict[str, str]:
    """Return patch-precise, platform-neutral interpreter identity."""

    version = sys.version_info
    return {
        "implementation": sys.implementation.name,
        "version": f"{version.major}.{version.minor}.{version.micro}",
    }


def valid_python_interpreter(value: object) -> bool:
    """Whether *value* is the exact interpreter-provenance schema."""

    if not isinstance(value, Mapping) or set(value) != {"implementation", "version"}:
        return False
    implementation = value.get("implementation")
    version = value.get("version")
    if not isinstance(implementation, str) or not implementation:
        return False
    if not isinstance(version, str):
        return False
    parts = version.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def query_python_interpreter(python: Path) -> dict[str, str]:
    """Read provenance from the interpreter selected for gallery execution."""

    probe = (
        "import json, sys; "
        "v = sys.version_info; "
        "print(json.dumps({'implementation': sys.implementation.name, "
        "'version': f'{v.major}.{v.minor}.{v.micro}'}, sort_keys=True))"
    )
    completed = subprocess.run(
        [str(python), "-P", "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            f"failed to inspect gallery interpreter {python}: {detail or completed.returncode}"
        )
    try:
        value: Any = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gallery interpreter {python} emitted invalid provenance") from exc
    if not valid_python_interpreter(value):
        raise RuntimeError(f"gallery interpreter {python} emitted invalid provenance: {value!r}")
    return dict(value)
