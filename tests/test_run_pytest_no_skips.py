from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_checker():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_pytest_no_skips.py"
    spec = importlib.util.spec_from_file_location("run_pytest_no_skips", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = _load_checker()


def test_no_skip_runner_accepts_a_passing_suite(tmp_path: Path) -> None:
    test_file = tmp_path / "test_pass.py"
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    assert runner.main(["-q", str(test_file)]) == 0


def test_no_skip_runner_rejects_runtime_skip(tmp_path: Path) -> None:
    test_file = tmp_path / "test_skip.py"
    test_file.write_text(
        "import pytest\n\ndef test_not_available():\n    pytest.skip('host missing')\n",
        encoding="utf-8",
    )

    assert runner.main(["-q", str(test_file)]) == 1


def test_no_skip_runner_rejects_collection_skip(tmp_path: Path) -> None:
    test_file = tmp_path / "test_collection_skip.py"
    test_file.write_text(
        "import pytest\npytest.skip('host missing', allow_module_level=True)\n",
        encoding="utf-8",
    )

    assert runner.main(["-q", str(test_file)]) == 1
