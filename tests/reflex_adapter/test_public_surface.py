"""`reflex_xy`'s public surface must be statically visible, not just lazy.

The package resolves every export through ``__getattr__`` (an explicit
``_EXPORTS`` map plus the curated ``_XY_REEXPORTS`` set) so ``import
reflex_xy`` stays cheap. A type checker cannot follow that hook: to a
consumer, an export that is only reachable dynamically is missing or
``Any``, which silently drops the typed signatures the data-bound API is
sold on. Every name in ``__all__`` therefore also needs a static
declaration — a ``TYPE_CHECKING`` import, or a real module-level
definition.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

reflex_xy = pytest.importorskip("reflex_xy")

INIT_PATH = Path(reflex_xy.__file__)


def _statically_declared(tree: ast.Module) -> set[str]:
    """Names a type checker can see without executing ``__getattr__``."""
    declared: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            declared.add(statement.name)
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            declared.add(statement.target.id)
        elif isinstance(statement, ast.Assign):
            declared.update(
                target.id for target in statement.targets if isinstance(target, ast.Name)
            )
        elif (
            isinstance(statement, ast.If)
            and isinstance(statement.test, ast.Name)
            and statement.test.id == "TYPE_CHECKING"
        ):
            for child in statement.body:
                if isinstance(child, ast.ImportFrom):
                    declared.update(
                        alias.asname or alias.name for alias in child.names if alias.name != "*"
                    )
                elif isinstance(child, ast.Import):
                    declared.update(
                        alias.asname or alias.name.split(".", 1)[0] for alias in child.names
                    )
    return declared


def test_every_public_export_is_statically_typed():
    tree = ast.parse(INIT_PATH.read_text(encoding="utf-8"), filename=str(INIT_PATH))
    missing = sorted(set(reflex_xy.__all__) - _statically_declared(tree))
    assert not missing, (
        "reflex_xy public names have no static TYPE_CHECKING import or "
        f"definition (they type as Any/missing for consumers): {missing}"
    )


def test_every_public_export_actually_resolves():
    """The mirror check: a static declaration with no runtime route behind it
    is a typed name that fails at import."""
    unresolvable = []
    for name in reflex_xy.__all__:
        try:
            getattr(reflex_xy, name)
        except AttributeError:  # noqa: PERF203 - one report per broken name
            unresolvable.append(name)
    assert not unresolvable
