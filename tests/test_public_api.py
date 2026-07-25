from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_public_api_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_public_api.py"
    spec = importlib.util.spec_from_file_location("check_public_api", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_public_api = _load_public_api_module()


def _fresh_import_stdout(
    *,
    elapsed_ms: float = 5.0,
    eager: object | None = None,
    missing_from_dir: object | None = None,
    public_all: object | None = None,
    version: object = "0.1.0",
) -> str:
    return json.dumps(
        {
            "elapsed_ms": elapsed_ms,
            "eager": [] if eager is None else eager,
            "missing_from_dir": [] if missing_from_dir is None else missing_from_dir,
            "public_all": ["__version__", "Figure"] if public_all is None else public_all,
            "version": version,
        }
    )


def test_public_api_checker_accepts_current_surface() -> None:
    assert check_public_api.check_public_api() == []


def test_fresh_import_budget_rejects_eager_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(eager=["numpy"]),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any("third-party" in error and "numpy" in error for error in errors)


def test_fresh_import_budget_splits_third_party_and_xy_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(eager=["numpy", "xy._figure", "xy.kernels"]),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any("third-party" in error and "numpy" in error for error in errors)
    assert any(
        "xy submodules" in error and "xy._figure" in error and "xy.kernels" in error
        for error in errors
    )


def test_fresh_import_budget_rejects_invalid_eager_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(eager="numpy"),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any("invalid eager list" in error and "numpy" in error for error in errors)


def test_all_import_budgets_probe_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    def fake_run(*args, **kwargs):
        del args
        seen.append(kwargs["env"].get("XY_FORCE_FALLBACK"))
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_all_fresh_import_budgets()

    assert errors == []
    # Native-only: there is no forced-fallback probe, so the env is never set.
    assert seen == [None]


def test_fresh_import_budget_rejects_eager_widget_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(eager=["anywidget", "traitlets"]),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any(
        "third-party" in error and "anywidget" in error and "traitlets" in error for error in errors
    )


def test_fresh_import_budget_rejects_slow_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(elapsed_ms=250.0),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any("budget" in error for error in errors)


def test_fresh_import_budget_probes_public_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_code = ""

    def fake_run(*args, **kwargs):
        del kwargs
        nonlocal seen_code
        seen_code = args[0][2]
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert errors == []
    assert "xy.__all__" in seen_code
    assert "dir(xy)" in seen_code


def test_fresh_import_budget_rejects_invalid_public_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(public_all=["Figure"]),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any("__version__" in error and "__all__" in error for error in errors)


def test_fresh_import_budget_rejects_dir_public_name_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_fresh_import_stdout(missing_from_dir=["scatter_chart"]),
            stderr="",
        )

    monkeypatch.setattr(check_public_api.subprocess, "run", fake_run)

    errors = check_public_api.check_fresh_import_budget()

    assert any("dir(xy)" in error and "scatter_chart" in error for error in errors)


def test_public_api_checker_rejects_stale_all_entry() -> None:
    fake = ModuleType("xy")
    fake.__all__ = ["Figure", "__version__", "old_name"]
    fake._EXPORTS = {"Figure": ".figure"}

    errors = check_public_api.validate_public_api(fake)

    assert any("old_name" in error for error in errors)


def test_public_api_checker_rejects_missing_all_entry() -> None:
    fake = ModuleType("xy")
    fake.__all__ = ["__version__"]
    fake._EXPORTS = {"Figure": ".figure"}

    errors = check_public_api.validate_public_api(fake)

    assert any("Figure" in error for error in errors)


def test_public_api_checker_accepts_component_module_all() -> None:
    fake = ModuleType("xy")
    fake._EXPORTS = {
        "CHART_DOM_SLOTS": ".dom",
        "Chart": ".components",
        "scatter": ".components",
        "Figure": ".figure",
    }
    fake_components = ModuleType("xy.components")
    fake_components.__all__ = ["CHART_DOM_SLOTS", "Chart", "scatter"]
    fake_components.CHART_DOM_SLOTS = ()
    fake_components.Chart = object()
    fake_components.scatter = object()

    errors = check_public_api.validate_component_public_api(fake, fake_components)

    assert errors == []


def _fake_declarative_modules() -> tuple[ModuleType, ModuleType]:
    fake = ModuleType("xy")
    fake.__all__ = ["__version__", *check_public_api.DECLARATIVE_API_EXPORTS]
    fake._EXPORTS = {name: ".components" for name in check_public_api.DECLARATIVE_API_EXPORTS}

    fake_components = ModuleType("xy.components")
    fake_components.__all__ = list(check_public_api.DECLARATIVE_API_EXPORTS)
    for name in check_public_api.DECLARATIVE_API_EXPORTS:
        setattr(fake_components, name, object())

    class Chart:
        pass

    for method in check_public_api.DECLARATIVE_CHART_READOUTS:
        setattr(Chart, method, lambda self: None)
    fake_components.Chart = Chart
    return fake, fake_components


def test_public_api_checker_accepts_declarative_api_contract() -> None:
    fake, fake_components = _fake_declarative_modules()

    errors = check_public_api.validate_declarative_api_contract(fake, fake_components)

    assert errors == []


def test_public_api_checker_rejects_missing_declarative_export() -> None:
    fake, fake_components = _fake_declarative_modules()
    fake.__all__.remove("tooltip")
    fake._EXPORTS.pop("tooltip")
    fake_components.__all__.remove("tooltip")
    del fake_components.tooltip
    delattr(fake_components.Chart, "html")

    errors = check_public_api.validate_declarative_api_contract(fake, fake_components)

    assert any("tooltip" in error and "xy.__all__" in error for error in errors)
    assert any("tooltip" in error and "'.components'" in error for error in errors)
    assert any("tooltip" in error and "xy.components.__all__" in error for error in errors)
    assert any("tooltip" in error and "undefined" in error for error in errors)
    assert any("html" in error and "readout" in error for error in errors)


def test_public_api_checker_rejects_misrouted_declarative_export() -> None:
    fake, fake_components = _fake_declarative_modules()
    fake._EXPORTS["chart"] = ".figure"

    errors = check_public_api.validate_declarative_api_contract(fake, fake_components)

    assert any(
        "chart" in error and "'.components'" in error and ".figure" in error for error in errors
    )


def test_public_api_checker_rejects_stale_component_module_all() -> None:
    fake = ModuleType("xy")
    fake._EXPORTS = {"Chart": ".components", "scatter": ".components", "line": ".components"}
    fake_components = ModuleType("xy.components")
    fake_components.__all__ = ["Chart", "scatter", "old_name", "missing_value"]
    fake_components.Chart = object()
    fake_components.scatter = object()
    fake_components.old_name = object()

    errors = check_public_api.validate_component_public_api(fake, fake_components)

    assert any("line" in error and "missing root exports" in error for error in errors)
    assert any("old_name" in error and "not exported from xy" in error for error in errors)
    assert any("missing_value" in error and "undefined name" in error for error in errors)


def test_public_api_checker_accepts_matching_project_version(tmp_path: Path) -> None:
    fake = ModuleType("xy")
    fake.__version__ = "1.2.3"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    errors = check_public_api.validate_version_consistency(fake, pyproject)

    assert errors == []


def test_public_api_checker_rejects_version_mismatch(tmp_path: Path) -> None:
    fake = ModuleType("xy")
    fake.__version__ = "1.2.3"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "1.2.4"\n', encoding="utf-8")

    errors = check_public_api.validate_version_consistency(fake, pyproject)

    assert any("__version__" in error and "project.version" in error for error in errors)


def test_public_api_checker_rejects_missing_public_version(tmp_path: Path) -> None:
    fake = ModuleType("xy")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    errors = check_public_api.validate_version_consistency(fake, pyproject)

    assert any("__version__" in error and "non-empty string" in error for error in errors)


def test_public_api_checker_rejects_unreadable_project_version(tmp_path: Path) -> None:
    fake = ModuleType("xy")
    fake.__version__ = "1.2.3"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project\n", encoding="utf-8")

    errors = check_public_api.validate_version_consistency(fake, pyproject)

    assert any("cannot read project version" in error for error in errors)


def test_public_api_checker_accepts_empty_pep561_marker(tmp_path: Path) -> None:
    marker = tmp_path / "py.typed"
    marker.write_bytes(b"")

    errors = check_public_api.validate_pep561_marker(marker)

    assert errors == []


def test_public_api_checker_rejects_missing_pep561_marker(tmp_path: Path) -> None:
    errors = check_public_api.validate_pep561_marker(tmp_path / "py.typed")

    assert any("missing PEP 561 marker" in error for error in errors)


def test_public_api_checker_rejects_partial_pep561_marker(tmp_path: Path) -> None:
    marker = tmp_path / "py.typed"
    marker.write_text("partial\n", encoding="utf-8")

    errors = check_public_api.validate_pep561_marker(marker)

    assert any("full-package PEP 561 marker" in error for error in errors)
