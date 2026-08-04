from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_check_typing_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_typing.py"
    spec = importlib.util.spec_from_file_location("check_typing", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_typing = _load_check_typing_module()


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
