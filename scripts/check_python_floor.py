#!/usr/bin/env python3
"""Check the repository's declared Python floor.

`requires-python >=3.11` is a contract. Running tests on one modern interpreter
does not prove it: newer syntax can sneak in, and annotations can execute at
import time on older interpreters unless postponed. This checker stays stdlib
only so CI can run it before dependency installation.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

DEFAULT_PATHS = (
    Path("python"),
    Path("scripts"),
    Path("benchmarks"),
    Path("tests"),
    Path("reflex_fastcharts_app"),
    Path("hatch_build.py"),
)

SKIP_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}


def iter_python_files(paths: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            if path.suffix == ".py" and not _skip(path):
                out.append(path)
            continue
        for child in path.rglob("*.py"):
            if not _skip(child):
                out.append(child)
    return sorted(set(out))


def _skip(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts)


def _has_future_annotations(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__" and any(
                alias.name == "annotations" for alias in node.names
            ):
                return True
            continue
        if isinstance(node, (ast.Expr, ast.Constant)) and _is_docstring_node(node):
            continue
        return False
    return False


def _is_docstring_node(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _has_annotations(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None:
                return True
            args = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
            if node.args.vararg is not None:
                args.append(node.args.vararg)
            if node.args.kwarg is not None:
                args.append(node.args.kwarg)
            if any(arg.annotation is not None for arg in args):
                return True
    return False


def check_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        tree = ast.parse(source, filename=str(path), feature_version=(3, 11))
    except SyntaxError as e:
        errors.append(f"{path}: not valid Python 3.11 syntax: {e.msg} at {e.lineno}:{e.offset}")
        return errors

    if _has_annotations(tree) and not _has_future_annotations(tree):
        errors.append(
            f"{path}: annotated files must use 'from __future__ import annotations' "
            "to keep imports side-effect free on Python 3.11"
        )
    return errors


def check_paths(paths: Iterable[Path]) -> list[str]:
    errors: list[str] = []
    for path in iter_python_files(paths):
        errors.extend(check_file(path))
    return errors


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, default=list(DEFAULT_PATHS))
    args = parser.parse_args(argv)
    errors = check_paths(args.paths)
    if errors:
        print("Python floor check failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("Python floor check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
