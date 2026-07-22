from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_floor_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_python_floor.py"
    spec = importlib.util.spec_from_file_location("check_python_floor", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_python_floor = _load_floor_module()


def _write_floor_repo(
    root: Path,
    *,
    requires_python: str = ">=3.11",
    ruff_target: str = "py311",
    readme: str = "Install with Python 3.11+.\n",
    production_readiness: str = "The current contract is Python 3.11+ only.\n",
) -> None:
    root.joinpath("spec", "process").mkdir(parents=True)
    root.joinpath("pyproject.toml").write_text(
        "[project]\n"
        f'requires-python = "{requires_python}"\n'
        "\n"
        "[tool.ruff]\n"
        f'target-version = "{ruff_target}"\n',
        encoding="utf-8",
    )
    root.joinpath("README.md").write_text(readme, encoding="utf-8")
    root.joinpath("spec", "process", "production-readiness.md").write_text(
        production_readiness,
        encoding="utf-8",
    )


def test_python_floor_accepts_current_declarations(tmp_path: Path) -> None:
    _write_floor_repo(tmp_path)

    assert check_python_floor.check_declared_floor(tmp_path) == []


def test_python_floor_rejects_lower_project_floor(tmp_path: Path) -> None:
    _write_floor_repo(tmp_path, requires_python=">=3.10")

    errors = check_python_floor.check_declared_floor(tmp_path)

    assert any("requires-python" in error and ">=3.11" in error for error in errors)


def test_python_floor_rejects_mismatched_ruff_target(tmp_path: Path) -> None:
    _write_floor_repo(tmp_path, ruff_target="py310")

    errors = check_python_floor.check_declared_floor(tmp_path)

    assert any("target-version" in error and "py311" in error for error in errors)


def test_python_floor_rejects_missing_docs_floor(tmp_path: Path) -> None:
    _write_floor_repo(tmp_path, readme="Install with Python.\n")

    errors = check_python_floor.check_declared_floor(tmp_path)

    assert any("README.md" in error and "Python 3.11+" in error for error in errors)


def test_python_floor_accepts_annotated_file_with_future_annotations(tmp_path: Path) -> None:
    path = tmp_path / "ok.py"
    path.write_text(
        "from __future__ import annotations\n\n"
        "def f(x: int | str) -> list[str]:\n"
        "    return [str(x)]\n",
        encoding="utf-8",
    )

    assert check_python_floor.check_file(path) == []


def test_python_floor_accepts_python_310_match_syntax(tmp_path: Path) -> None:
    path = tmp_path / "match_syntax.py"
    path.write_text(
        "from __future__ import annotations\n\n"
        "def f(x):\n"
        "    match x:\n"
        "        case 1:\n"
        "            return True\n",
        encoding="utf-8",
    )

    assert check_python_floor.check_file(path) == []


def test_python_floor_rejects_python_312_only_syntax(tmp_path: Path) -> None:
    path = tmp_path / "type_statement.py"
    path.write_text(
        "from __future__ import annotations\n\ntype Point = tuple[float, float]\n",
        encoding="utf-8",
    )

    errors = check_python_floor.check_file(path)
    assert len(errors) == 1
    assert "not valid Python 3.11 syntax" in errors[0]


def test_python_floor_rejects_annotations_without_future_import(tmp_path: Path) -> None:
    path = tmp_path / "eager_annotations.py"
    path.write_text("def f(x: int) -> int:\n    return x\n", encoding="utf-8")

    errors = check_python_floor.check_file(path)
    assert len(errors) == 1
    assert "from __future__ import annotations" in errors[0]
