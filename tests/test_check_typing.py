from __future__ import annotations

import importlib.util
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import xy


def _load_check_typing_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_typing.py"
    spec = importlib.util.spec_from_file_location("check_typing", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        previous = sys.modules[spec.name]
        had_previous = True
    except KeyError:
        previous = module
        had_previous = False
    previous_sys_path = sys.path.copy()
    sys.path.insert(0, str(path.parent))
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous_sys_path
        if had_previous:
            sys.modules[spec.name] = previous
        else:
            sys.modules.pop(spec.name, None)
    return module


check_typing = _load_check_typing_module()


def test_check_typing_loader_does_not_leak_module(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "check_typing", raising=False)

    loaded = _load_check_typing_module()

    assert loaded is not None
    assert "check_typing" not in sys.modules


def test_check_typing_loader_restores_existing_module(monkeypatch) -> None:
    previous = ModuleType("check_typing")
    monkeypatch.setitem(sys.modules, "check_typing", previous)

    loaded = _load_check_typing_module()

    assert loaded is not previous
    assert sys.modules["check_typing"] is previous


def test_external_consumer_fixture_is_runtime_side_effect_free(monkeypatch) -> None:
    path = Path(__file__).with_name("typing_pep561_consumer.py")
    namespace = runpy.run_path(str(path))
    check = namespace["check_root_typing_surface"]
    before = xy.registered_marks()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("runtime consumer fixture called register_mark")

    monkeypatch.setattr(xy, "register_mark", fail_if_called)

    check()
    check()

    assert xy.registered_marks() == before


def test_canonical_public_names_come_from_source_exports(tmp_path: Path) -> None:
    init_path = tmp_path / "__init__.py"
    init_path.write_text(
        '_EXPORTS = {"Second": ".second", "First": ".first"}\n',
        encoding="utf-8",
    )

    assert check_typing._canonical_public_names(init_path) == [
        "First",
        "Second",
        "__version__",
    ]


def test_canonical_public_names_match_the_current_root_contract() -> None:
    names = check_typing._canonical_public_names()

    assert len(names) == 105  # +funnel/funnel_chart and +structural_probe
    assert names == sorted(xy.__all__)


def test_public_name_drift_reports_missing_and_extra_exports() -> None:
    missing, extra = check_typing._public_name_drift(
        ["First", "Second", "__version__"],
        ["Second", "Unexpected", "__version__"],
    )

    assert missing == ["First"]
    assert extra == ["Unexpected"]


def test_installed_consumer_rejects_missing_and_extra_wheel_exports(monkeypatch, capsys) -> None:
    monkeypatch.setattr(check_typing, "_canonical_public_names", lambda: ["First", "Second"])
    monkeypatch.setattr(check_typing, "_installed_public_names", lambda *_args, **_kwargs: [])

    assert check_typing._run_installed_consumer_check(Path("python"), Path("ty")) is False
    assert "missing canonical exports: ['First', 'Second']" in capsys.readouterr().err

    monkeypatch.setattr(
        check_typing,
        "_installed_public_names",
        lambda *_args, **_kwargs: ["First", "Unexpected"],
    )

    assert check_typing._run_installed_consumer_check(Path("python"), Path("ty")) is False
    error = capsys.readouterr().err
    assert "missing canonical exports: ['Second']" in error
    assert "unexpected exports: ['Unexpected']" in error


def test_installed_consumer_typecheck_removes_pythonpath(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/tmp/checkout-shadow")
    monkeypatch.setattr(check_typing, "_canonical_public_names", lambda: ["Only"])
    monkeypatch.setattr(
        check_typing,
        "_installed_public_names",
        lambda *_args, **_kwargs: ["Only"],
    )
    captured_env: dict[str, str] = {}

    def fake_run(command, **kwargs):
        captured_env.update(kwargs["env"])
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="/tmp/consumer.py:5:13: info[revealed-type] Revealed type: `int`\n",
            stderr="",
        )

    monkeypatch.setattr(check_typing.subprocess, "run", fake_run)

    assert check_typing._run_installed_consumer_check(Path("python"), Path("ty")) is True

    assert "PYTHONPATH" not in captured_env
    assert os.environ["PYTHONPATH"] == "/tmp/checkout-shadow"


def test_revealed_type_parser_accepts_current_and_legacy_ty_wording() -> None:
    output = "\n".join(
        (
            "/tmp/consumer.py:5:13: info[revealed-type] Revealed type: `str`",
            "/tmp/consumer.py:6:13: info[revealed-type] Revealed type is `Any`",
        )
    )

    revealed = check_typing._parse_revealed_types(output, {5: "version", 6: "missing"})

    assert revealed == {"version": "str", "missing": "Any"}


def test_dynamic_root_check_does_not_reject_typed_signatures_containing_any() -> None:
    revealed = {
        "dynamic": "Any",
        "unknown": "Unknown",
        "factory": "def chart(**props: Any) -> Chart",
        "klass": "<class 'Chart'>",
    }

    assert check_typing._dynamic_root_names(revealed) == ["dynamic", "unknown"]
