"""Shared helpers for tests that load the standalone public API checker."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def load_public_api_module(module_name: str):
    """Load the checker without leaving a temporary module in ``sys.modules``."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_public_api.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module
