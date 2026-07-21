#!/usr/bin/env python3
"""Find and replace remnants of the project's old name (``fc`` / ``fastchart``).

The project was renamed to ``xy``, but the old short name survived in several
distinct roles. Each role needs a different rewrite, and a couple of look-alike
tokens must be left alone, so this is rule-driven rather than a blind sed:

rewritten
  - C-ABI symbols            ``fc_*``            -> ``xy_*``   (src/lib.rs, _native.py, smoke/tests)
  - JS module constants      ``FC_*``            -> ``XY_*``   (js/src, committed static/ artifacts)
  - security-audit IDs       ``FC-SEC-* FC-CI-*`` -> ``XY-*``
  - DOM/CSS contract         ``data-fc-* fc-*``  -> ``data-xy-* xy-*``
  - SVG facet id prefix      ``f"fc{i}-"``       -> ``f"xy{i}-"``
  - module alias             ``import xy as fc`` -> ``import xy`` (+ ``fc.`` -> ``xy.``,
                             ``getattr(fc, ...)`` -> ``getattr(xy, ...)``)
  - pyproject                drop ``fastcharts`` from known-first-party
  - a few file-local ``fc`` variables that aliased the library (benchmarks, smoke scripts)

left alone (reported by the audit as allowed)
  - matplotlib's own ``fc`` facecolor alias — quoted ``"fc"`` keys and ``fc=...``
    kwargs in the pyplot shim, its corpus tests, and the PDSH notebooks are
    matplotlib API compatibility, not branding
  - ``fc`` inside base64 blobs, sha hashes, hex colors, and vendored plotly
  - lockfiles and the frozen benchmark baselines under benchmarks/launch_baselines/

Usage:
  python3 scripts/rename_fc_to_xy.py --check   # report what would change + audit leftovers
  python3 scripts/rename_fc_to_xy.py --apply   # rewrite files in place, then audit

Idempotent: a second --apply run changes nothing. Exit code is non-zero when
the audit finds an occurrence that is neither rewritten nor whitelisted.

Note: renaming the ``fc_*`` exported symbols is an ABI change — bump
``ABI_VERSION`` in src/lib.rs and python/xy/_native.py together, and
regenerate the static client (``node js/build.mjs``) after applying.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Files where the old name must stay: lockfile hashes, frozen benchmark
# artifacts, and vendored third-party code are not ours to rewrite.
EXCLUDED_BASENAMES = {
    "uv.lock",
    "Cargo.lock",
    "package-lock.json",
}
EXCLUDED = (
    "benchmarks/launch_baselines/",
    "examples/reflex/assets/charts/plotly_colored_scatter.html",
)

# Global rules, applied in order to every non-excluded text file.
RULES: list[tuple[str, str]] = [
    # pyproject known-first-party: drop the stale entry instead of duplicating "xy"
    (r'"fastcharts",\s*"xy"', '"xy"'),
    (r"(?i)fastcharts?", "xy"),
    # identifiers: C-ABI symbols, JS constants, and camelCase JS names
    # (fcMap, dataset.fcSlot -> data-fc-slot, etc.)
    (r"\bfc_", "xy_"),
    (r"\bFC_", "XY_"),
    (r"\bfc(?=[A-Z])", "xy"),
    # security-audit finding IDs
    (r"\bFC-(?=(?:SEC|CI)-)", "XY-"),
    # DOM/CSS contract: data attributes, class names, facet group ids
    (r"\bfc-", "xy-"),
    # SVG per-facet id prefix in f-strings: f"fc{i}-"
    (r"\bfc(?=\{)", "xy"),
    # module alias: drop it, then rewrite attribute access on it
    (r"\bimport xy as fc\b", "import xy"),
    (r"\bfc\\\.", r"xy\\."),  # regex-escaped form inside test match patterns
    (r"\bfc\.", "xy."),
    (r"\b(getattr|hasattr)\(\s*fc\s*,", r"\1(xy,"),
]

# File-local rules for scripts that used a bare `fc` variable as an alias for
# the library (JS `const fc = window.xy`, benchmark builder closures named to
# match the library under test).
PER_FILE_RULES: dict[str, list[tuple[str, str]]] = {
    "benchmarks/bench_2d_charts.py": [(r"\bfc\b", "xy")],
    "benchmarks/bench_scatter_native.py": [(r"\bfc\b", "xy")],
    "scripts/reflex_lifecycle_smoke.py": [(r"\bfc\b", "xy")],
}
# Rules never touch lines longer than this: embedded base64 blobs and minified
# vendor payloads live on very long lines and can contain look-alike tokens
# (URL-safe base64 allows `-` and `_`, so even `fc-`/`fc_` could match there).
MAX_LINE = 2000

# Audit whitelist: occurrences of fc/fastchart that are correct to keep.
# - "fc"/fc= is matplotlib's facecolor alias (quotes may be JSON-escaped in .ipynb)
# - Fc is matplotlib's center-frequency parameter (psd/*_spectrum signatures)
MPL_PATHS = (
    "python/xy/pyplot/",
    "tests/pyplot/",
    "examples/pdsh/",
    "spec/matplotlib-compat.md",
)
MPL_FC = re.compile(r"""["']fc["']|\bfc=\\?["'0-9]|\bFc\b""")
AUDIT = re.compile(r"(?i:\bfc\b|fastchart)|\bfc(?=[A-Z])")
# base64 blobs / minified vendor payloads live on very long lines
MAX_AUDIT_LINE = 1000
# `const fc = new Float32Array(...)` in the bad-apple demo is an unrelated
# local variable (frame column buffer), not the old library name
ALLOWED_LINES = {
    (
        "examples/bad_apple/player_template.html",
        re.compile(r"\bfc\[k\]|\bconst fc = new Float32Array"),
    ),
}


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout
    return [REPO / p for p in out.split("\0") if p]


def is_excluded(rel: str) -> bool:
    return Path(rel).name in EXCLUDED_BASENAMES or any(
        rel == entry or rel.startswith(entry) for entry in EXCLUDED
    )


def rewrite(rel: str, text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    rules = [(pat, repl, re.compile(pat)) for pat, repl in RULES + PER_FILE_RULES.get(rel, [])]
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if len(line) > MAX_LINE:
            continue  # base64 / minified payload
        for pat, repl, rx in rules:
            line, n = rx.subn(repl, line)
            if n:
                counts[pat] = counts.get(pat, 0) + n
        lines[i] = line
    return "\n".join(lines), counts


def allowed_leftover(rel: str, line: str) -> bool:
    if len(line) > MAX_AUDIT_LINE:
        return True  # base64 / minified payload
    if rel.startswith(MPL_PATHS) and MPL_FC.search(line):
        return True  # matplotlib facecolor alias
    return any(rel == arel and rx.search(line) for arel, rx in ALLOWED_LINES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report only, change nothing")
    mode.add_argument("--apply", action="store_true", help="rewrite files in place")
    args = ap.parse_args()

    changed = 0
    leftovers: list[str] = []
    allowed = 0
    for path in tracked_files():
        rel = path.relative_to(REPO).as_posix()
        if is_excluded(rel) or rel == "scripts/rename_fc_to_xy.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary or removed
        new, counts = rewrite(rel, text)
        if counts:
            changed += 1
            total = sum(counts.values())
            print(f"{'rewrite' if args.apply else 'would rewrite'} {rel}: {total} occurrence(s)")
            for pat, n in counts.items():
                print(f"    {n:4d}  {pat}")
            if args.apply:
                path.write_text(new, encoding="utf-8")
        for i, line in enumerate(new.split("\n"), 1):
            for m in AUDIT.finditer(line):
                if allowed_leftover(rel, line):
                    allowed += 1
                else:
                    ctx = line.strip()[:120]
                    leftovers.append(f"{rel}:{i}: {m.group(0)!r} in: {ctx}")

    print(f"\n{changed} file(s) {'rewritten' if args.apply else 'needing rewrite'};", end=" ")
    print(f"{allowed} allowed leftover occurrence(s) (matplotlib fc=facecolor, base64 blobs).")
    if leftovers:
        print(f"\n{len(leftovers)} occurrence(s) need manual review:", file=sys.stderr)
        for entry in leftovers:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print("audit clean: every remaining fc/fastchart occurrence is whitelisted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
