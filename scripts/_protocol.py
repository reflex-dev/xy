"""Read the payload protocol without importing the optional Python package."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _ROOT / "python" / "xy" / "config.py"
_MATCH = re.search(
    r"^PROTOCOL_VERSION\s*=\s*(\d+)\s*$",
    _CONFIG.read_text(encoding="utf-8"),
    re.MULTILINE,
)
if _MATCH is None:
    raise RuntimeError(f"could not read PROTOCOL_VERSION from {_CONFIG}")

PROTOCOL_VERSION = int(_MATCH.group(1))
