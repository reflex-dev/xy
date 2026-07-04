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
