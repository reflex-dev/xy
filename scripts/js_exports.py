"""Shared stdlib-only ESM export parsing for the built render-client bundles.

Production builds minify local declarations, so the public surface can only be
checked through the export block: `renderStandalone` survives as an alias of
whatever short name the minifier chose. Parsing that block instead of grepping
for spellings keeps the checks honest in both directions — a name-preserving
build (`export{decodeFrame}`) and a minified one (`export{p as decodeFrame}`)
both satisfy it, and a genuinely missing export fails either way.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Vite lib mode emits one trailing `export {...}` per ESM bundle. Declaration
# exports (`export function f()`) and `export * from` re-exports are not parsed:
# the bundles never emit them, and a build that started to would fail these
# checks loudly rather than pass silently.
_EXPORT_BLOCK = re.compile(r"\bexport\s*\{([^}]*)\}")
_EXPORTED_NAME = re.compile(r"(?:[A-Za-z_$][\w$]*\s+as\s+)?([A-Za-z_$][\w$]*)")


def esm_exported_names(text: str) -> set[str]:
    """Public names an ESM bundle exports, seeing through minifier renames."""
    return {
        match.group(1)
        for block in _EXPORT_BLOCK.findall(text)
        for item in block.split(",")
        if (match := _EXPORTED_NAME.fullmatch(item.strip()))
    }


def missing_esm_exports(text: str, required: Iterable[str]) -> list[str]:
    """Which of `required` the bundle does not export, sorted for stable errors."""
    exported = esm_exported_names(text)
    return sorted(name for name in required if name not in exported)
