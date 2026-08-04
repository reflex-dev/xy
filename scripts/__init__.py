"""Repository-only maintenance scripts."""

from __future__ import annotations

import sys

from scripts import _ty_tools

# Direct path execution imports helpers from the scripts directory by their
# local name. Package execution loads this module first, so make that name
# resolve to the same helper without duplicating fallbacks in every entry point.
sys.modules["_ty_tools"] = _ty_tools
