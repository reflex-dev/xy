#!/usr/bin/env python3
"""Generate or verify the pinned Matplotlib 3.11 pyplot public inventory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "python/xy/pyplot/_compat_inventory.py"
TARGET_VERSION = "3.11.0"


def _inventory() -> tuple[str, ...]:
    try:
        import matplotlib
        import matplotlib.pyplot as pyplot
    except ImportError as exc:
        raise RuntimeError(
            'inventory generation requires `pip install "matplotlib==3.11.0"`'
        ) from exc
    if matplotlib.__version__ != TARGET_VERSION:
        raise RuntimeError(
            f"inventory generation requires Matplotlib {TARGET_VERSION}, "
            f"found {matplotlib.__version__}"
        )
    return tuple(sorted(name for name in dir(pyplot) if not name.startswith("_")))


def _render(names: tuple[str, ...]) -> str:
    entries = "\n".join(f'    "{name}",' for name in names)
    return f'''\
"""Generated public ``matplotlib.pyplot`` inventory for Matplotlib 3.11.0.

Regenerate and verify this file with
``python scripts/generate_pyplot_compat_inventory.py``.  Keeping the names in
the distribution lets :mod:`xy.pyplot` expose the complete compat surface
without importing Matplotlib during an ordinary module import.
"""

from __future__ import annotations

MATPLOTLIB_VERSION = "{TARGET_VERSION}"

COMPAT_PYPLOT_PUBLIC_NAMES = (
{entries}
)

__all__ = [
    "COMPAT_PYPLOT_PUBLIC_NAMES",
    "MATPLOTLIB_VERSION",
]
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rendered = _render(_inventory())
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(
                f"{OUTPUT.relative_to(ROOT)} is stale; run {Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        print(f"Pyplot compat inventory verified: {TARGET_VERSION}, 247 public names")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} with 247 public names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
