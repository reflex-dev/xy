#!/usr/bin/env python3
"""Run the dependency-advisory gates used locally and in CI."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from scripts.verify_dependency_lock_inventory import AUDITED_LOCKFILES
except ModuleNotFoundError:
    from verify_dependency_lock_inventory import AUDITED_LOCKFILES

ROOT = Path(__file__).resolve().parents[1]


def _run(label: str, command: tuple[str, ...], *, cwd: Path = ROOT) -> None:
    print(f"\n==> {label}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def _require_tools() -> None:
    required = ("uv", "uvx", "cargo-audit", "npm", "bun")
    missing = [tool for tool in required if shutil.which(tool) is None]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"missing dependency-audit tools: {names}; "
            "install cargo-audit with `cargo install cargo-audit --locked`"
        )


def _verify_audit_coverage() -> None:
    implemented = set(AUDIT_HANDLERS)
    missing = sorted(AUDITED_LOCKFILES - implemented)
    untracked = sorted(implemented - AUDITED_LOCKFILES)
    if missing or untracked:
        raise RuntimeError(
            "dependency audit handlers do not match the lock inventory: "
            f"missing={missing}, untracked={untracked}"
        )


def _audit_uv_project(label: str, project: str) -> None:
    """Audit every dependency variant in a universal uv lockfile."""
    with tempfile.TemporaryDirectory(prefix="xy-pylock-audit-") as temp_dir:
        _run(
            f"export {label} universal Python lock",
            (
                "uv",
                "export",
                "--project",
                project,
                "--locked",
                "--all-extras",
                "--all-groups",
                "--no-emit-project",
                "--format",
                "pylock.toml",
                "--output-file",
                str(Path(temp_dir) / "pylock.toml"),
                "--quiet",
            ),
        )
        _run(
            f"audit {label} universal Python lock",
            (
                "uv",
                "run",
                "--project",
                project,
                "--no-sync",
                "--with",
                "pip-audit",
                "pip-audit",
                "--locked",
                temp_dir,
                "--progress-spinner",
                "off",
            ),
        )


def _audit_benchmark_python_lock() -> None:
    _run(
        "audit benchmark Python lock",
        (
            "uvx",
            "--from",
            "pip-audit",
            "pip-audit",
            "-r",
            "benchmarks/requirements-ci.lock",
            "--progress-spinner",
            "off",
        ),
    )


def _audit_root_rust_lock() -> None:
    _run("audit root Rust lock", ("cargo", "audit"))


def _audit_osmium_rust_lock() -> None:
    _run(
        "audit osmium example Rust lock",
        ("cargo", "audit", "--file", "examples/osm/osmium-rs/Cargo.lock"),
    )


def _audit_npm_lock() -> None:
    _run("audit npm lock", ("npm", "audit", "--package-lock-only", "--audit-level=high"))


def _audit_bun_lock() -> None:
    bun_dir = ROOT / "docs" / "app" / "reflex.lock"
    _run("install frozen Bun lock", ("bun", "install", "--frozen-lockfile"), cwd=bun_dir)
    _run("audit Bun lock", ("bun", "audit", "--audit-level=high"), cwd=bun_dir)


AUDIT_HANDLERS = {
    "uv.lock": lambda: _audit_uv_project("root", "."),
    "docs/app/uv.lock": lambda: _audit_uv_project("documentation", "docs/app"),
    "benchmarks/requirements-ci.lock": _audit_benchmark_python_lock,
    "Cargo.lock": _audit_root_rust_lock,
    "examples/osm/osmium-rs/Cargo.lock": _audit_osmium_rust_lock,
    "package-lock.json": _audit_npm_lock,
    "docs/app/reflex.lock/bun.lock": _audit_bun_lock,
}


def main() -> int:
    try:
        _verify_audit_coverage()
        _require_tools()
        _run(
            "verify dependency lock inventory",
            (sys.executable, "scripts/verify_dependency_lock_inventory.py"),
        )
        for audit_handler in AUDIT_HANDLERS.values():
            audit_handler()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"dependency audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
