#!/usr/bin/env python3
"""Fail on accepted pyplot options that have no effect or reviewed no-op contract."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "python" / "xy" / "pyplot"
POLICY = ROOT / "spec" / "testing" / "pyplot-noops.json"


@dataclass(frozen=True, order=True)
class Noop:
    path: str
    function: str
    option: str


def _qualnames(tree: ast.AST) -> dict[ast.AST, str]:
    result: dict[ast.AST, str] = {}

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        next_parents = parents
        if isinstance(node, ast.ClassDef):
            next_parents = (*parents, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[node] = ".".join((*parents, node.name))
            next_parents = (*parents, node.name)
        for child in ast.iter_child_nodes(node):
            visit(child, next_parents)

    visit(tree)
    return result


def _is_stub_or_rejection(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any(
        (isinstance(decorator, ast.Name) and decorator.id == "overload")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
        for decorator in function.decorator_list
    ):
        return True
    statements = list(function.body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if len(statements) != 1:
        return False
    statement = statements[0]
    return isinstance(statement, (ast.Pass, ast.Raise)) or (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _function_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Walk one function without crediting nested definitions for parameter use."""
    nodes: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        nodes.append(node)
        for child in ast.iter_child_nodes(node):
            if child is not function and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
            ):
                # Keep the definition node so callers can decide whether its
                # closure is reachable, but do not credit its body yet.
                nodes.append(child)
                continue
            visit(child)

    visit(function)
    return nodes


def _loaded_names(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names read by a function, including only reachable local closures.

    A nested helper may legitimately consume an outer option (``findobj``'s
    predicate is one example), but an unreferenced nested definition must not
    be enough to disguise an unused public parameter.  Follow local function
    definitions only when their name is read by the containing scope.
    """
    nodes = _function_nodes(function)
    loaded = {
        node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    closures = {
        node.name: node
        for node in nodes
        if node is not function and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    pending = [closures[name] for name in sorted(loaded & closures.keys())]
    followed: set[str] = set()
    while pending:
        closure = pending.pop()
        if closure.name in followed:
            continue
        followed.add(closure.name)
        closure_nodes = _function_nodes(closure)
        closure_loads = {
            node.id
            for node in closure_nodes
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        loaded.update(closure_loads)
        nested = {
            node.name: node
            for node in closure_nodes
            if node is not closure and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        pending.extend(nested[name] for name in sorted(closure_loads & nested.keys()))
    return loaded


def discover_noops(root: Path = SOURCE_ROOT, *, project_root: Path = ROOT) -> set[Noop]:
    found: set[Noop] = set()
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        qualnames = _qualnames(tree)
        parents: dict[ast.AST, ast.AST] = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        relpath = path.relative_to(project_root).as_posix()
        for function in (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            parent = parents.get(function)
            nested = False
            while parent is not None:
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested = True
                    break
                parent = parents.get(parent)
            if nested:
                continue
            leaf_name = qualnames[function].rsplit(".", 1)[-1]
            if leaf_name.startswith("_") and leaf_name not in {"__init__", "__call__"}:
                continue
            if _is_stub_or_rejection(function):
                continue
            nodes = _function_nodes(function)
            loads = _loaded_names(function)
            parameters = {
                arg.arg
                for arg in (
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                )
                if arg.arg not in {"self", "cls"}
            }
            for option in parameters - loads:
                found.add(Noop(relpath, qualnames[function], option))

            for node in nodes:
                call: ast.Call | None = None
                assigned: str | None = None
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                    call = node.value
                elif (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                ):
                    call = node.value
                    assigned = node.targets[0].id
                if not call or not isinstance(call.func, ast.Attribute) or call.func.attr != "pop":
                    continue
                if not isinstance(call.func.value, ast.Name) or call.func.value.id not in {
                    "kwargs",
                    "options",
                }:
                    continue
                if (
                    not call.args
                    or not isinstance(call.args[0], ast.Constant)
                    or not isinstance(call.args[0].value, str)
                ):
                    continue
                if assigned is None or assigned not in loads:
                    found.add(Noop(relpath, qualnames[function], call.args[0].value))
    return found


def load_policy(path: Path = POLICY, *, project_root: Path = ROOT) -> tuple[set[Noop], list[str]]:
    errors: list[str] = []
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return set(), [f"cannot read no-op policy: {exc}"]
    if not isinstance(data, dict) or set(data) != {"schema_version", "noops"}:
        return set(), ["policy must contain exactly schema_version and noops"]
    if data["schema_version"] != 1 or not isinstance(data["noops"], list):
        return set(), ["policy schema_version must be 1 and noops must be a list"]
    noops: set[Noop] = set()
    for index, entry in enumerate(data["noops"]):
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "function",
            "options",
            "rationale",
            "test",
        }:
            errors.append(f"noops[{index}] has invalid fields")
            continue
        if not all(
            isinstance(entry[field], str) and entry[field].strip()
            for field in ("path", "function", "rationale", "test")
        ):
            errors.append(f"noops[{index}] path/function/rationale/test must be strings")
            continue
        if not isinstance(entry["rationale"], str) or len(entry["rationale"].strip()) < 20:
            errors.append(f"noops[{index}] needs a substantive rationale")
        test = entry["test"]
        if not isinstance(test, str) or "::" not in test:
            errors.append(f"noops[{index}] test must be path::function")
        else:
            test_path, test_name = test.split("::", 1)
            candidate = project_root / test_path
            if not candidate.is_file() or f"def {test_name}(" not in candidate.read_text(
                encoding="utf-8"
            ):
                errors.append(f"noops[{index}] references missing test {test!r}")
        options = entry["options"]
        if (
            not isinstance(options, list)
            or not options
            or not all(isinstance(option, str) and option for option in options)
        ):
            errors.append(f"noops[{index}] options must be a nonempty string list")
            continue
        for option in options:
            noop = Noop(entry["path"], entry["function"], option)
            if noop in noops:
                errors.append(f"noops[{index}] duplicates {noop}")
            noops.add(noop)
    return noops, errors


def validate(
    root: Path = SOURCE_ROOT, policy_path: Path = POLICY, *, project_root: Path = ROOT
) -> list[str]:
    discovered = discover_noops(root, project_root=project_root)
    policy, errors = load_policy(policy_path, project_root=project_root)
    for noop in sorted(discovered - policy):
        errors.append(f"accepted option has no effect and no reviewed contract: {noop}")
    for noop in sorted(policy - discovered):
        errors.append(f"stale no-op policy entry now appears effectful or absent: {noop}")
    return errors


def _record(noop: Noop) -> dict[str, str]:
    return {"path": noop.path, "function": noop.function, "option": noop.option}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="write machine-readable JSON evidence")
    args = parser.parse_args(argv)
    discovered = discover_noops()
    policy, policy_errors = load_policy()
    errors = list(policy_errors)
    errors.extend(
        f"accepted option has no effect and no reviewed contract: {noop}"
        for noop in sorted(discovered - policy)
    )
    errors.extend(
        f"stale no-op policy entry now appears effectful or absent: {noop}"
        for noop in sorted(policy - discovered)
    )
    if args.report is not None:
        report = {
            "schema_version": 1,
            "status": "failed" if errors else "passed",
            "reviewed_noop_count": len(discovered),
            "discovered": [_record(noop) for noop in sorted(discovered)],
            "errors": errors,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if errors:
        print("pyplot option contract failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"pyplot option contract OK: {len(discovered)} reviewed no-op options")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
