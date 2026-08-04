"""Repository-only maintenance scripts."""

from __future__ import annotations

import sys

from . import _ty_tools

# Direct path execution imports helpers from the scripts directory by their
# local name. Package execution loads this module first, so expose that same
# name once here instead of duplicating fallbacks in every entry point.
sys.modules.setdefault("_ty_tools", _ty_tools)
