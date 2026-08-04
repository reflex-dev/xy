#!/usr/bin/env python3
"""Type-check the shipped package and its installed lazy root surface."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ("python", "tests/typing_pep561_consumer.py")
REVEAL_RE = re.compile(
    r"consumer\.py:(?P<line>\d+):\d+: info\[revealed-type\] "
    r"Revealed type(?: is)?(?::)? `(?P<type>.*)`$"
)


def _absolute_executable(value: str | os.PathLike[str]) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        resolved = shutil.which(str(path))
        path = Path(resolved) if resolved is not None else Path.cwd() / path
    return path.absolute()


def _default_ty(python: Path) -> Path:
    executable = "ty.exe" if os.name == "nt" else "ty"
    sibling = python.with_name(executable)
    if sibling.is_file():
        return sibling
    found = shutil.which("ty")
    if found is None:
        raise FileNotFoundError("cannot find ty beside Python or on PATH")
    return Path(found).absolute()


def _print_command(command: list[str], *, cwd: Path) -> None:
    print(f"$ (cd {shlex.quote(str(cwd))} && {shlex.join(command)})")


def _run_package_check(ty: Path) -> bool:
    command = [str(ty), "check", *SOURCE_PATHS, "--output-format", "concise"]
    _print_command(command, cwd=ROOT)
    proc = subprocess.run(command, cwd=ROOT, check=False, text=True)
    return proc.returncode == 0


def _installed_public_names(python: Path, *, cwd: Path) -> list[str]:
    code = "import json, xy; print(json.dumps(xy.__all__))"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    proc = subprocess.run(
        [str(python), "-c", code],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise RuntimeError(f"cannot import installed xy with {python}: {detail}")
    try:
        value = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"installed xy.__all__ probe returned invalid JSON: {exc}") from exc
    if not isinstance(value, list) or any(
        not isinstance(name, str) or not name.isidentifier() for name in value
    ):
        raise RuntimeError(f"installed xy.__all__ must be a list of identifiers, got {value!r}")
    if len(value) != len(set(value)):
        raise RuntimeError("installed xy.__all__ contains duplicate names")
    return sorted(value)


def _parse_revealed_types(output: str, line_names: dict[int, str]) -> dict[str, str]:
    revealed: dict[str, str] = {}
    for raw_line in output.splitlines():
        match = REVEAL_RE.search(raw_line)
        if match is None:
            continue
        line = int(match.group("line"))
        name = line_names.get(line)
        if name is not None:
            revealed[name] = match.group("type")
    return revealed


def _dynamic_root_names(revealed: dict[str, str]) -> list[str]:
    """Return exports whose value itself is dynamic, not merely parametrized by Any."""
    return sorted(name for name, type_name in revealed.items() if type_name in {"Any", "Unknown"})


def _run_installed_consumer_check(python: Path, ty: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="xy-typing-consumer-") as raw_tmp:
        tmp = Path(raw_tmp)
        names = _installed_public_names(python, cwd=tmp)
        lines = ["from typing import reveal_type", "", "import xy", ""]
        line_names: dict[int, str] = {}
        for name in names:
            lines.append(f"reveal_type(xy.{name})")
            line_names[len(lines)] = name
        consumer = tmp / "consumer.py"
        consumer.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (tmp / "pyproject.toml").write_text(
            """\
[project]
name = "xy-typing-consumer"
version = "0"
requires-python = ">=3.11"
""",
            encoding="utf-8",
        )

        command = [
            str(ty),
            "check",
            "--project",
            str(tmp),
            "--python",
            str(python),
            str(consumer),
            "--output-format",
            "concise",
            "--no-progress",
            "--color",
            "never",
        ]
        _print_command(command, cwd=tmp)
        proc = subprocess.run(
            command,
            cwd=tmp,
            check=False,
            capture_output=True,
            text=True,
        )
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
        if proc.returncode != 0:
            print(output, file=sys.stderr)
            return False

        revealed = _parse_revealed_types(output, line_names)
        missing = sorted(set(names) - set(revealed))
        dynamic = _dynamic_root_names(revealed)
        if missing:
            print(f"installed consumer did not reveal types for: {missing}", file=sys.stderr)
        if dynamic:
            print(f"installed xy root exports resolve dynamically: {dynamic}", file=sys.stderr)
        if missing or dynamic:
            print(output, file=sys.stderr)
            return False

        print(f"installed typing consumer OK: {len(names)} xy.__all__ exports have concrete types")
        return True


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--consumer-only",
        action="store_true",
        help="skip the source-tree package check (for an isolated wheel smoke)",
    )
    parser.add_argument(
        "--python-executable",
        help="Python environment containing the xy installation to inspect",
    )
    parser.add_argument("--ty-executable", help="ty executable used for both checks")
    args = parser.parse_args(argv)

    python = _absolute_executable(args.python_executable or sys.executable)
    ty = _absolute_executable(args.ty_executable) if args.ty_executable else _default_ty(python)

    package_ok = args.consumer_only or _run_package_check(ty)
    consumer_ok = _run_installed_consumer_check(python, ty)
    return 0 if package_ok and consumer_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
