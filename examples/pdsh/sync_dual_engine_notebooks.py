#!/usr/bin/env python3
"""Keep the Matplotlib and xy sections inside each PDSH notebook synchronized."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED_ID = "xy-pdsh-dual-engine-intro"
IMPORT_REPLACEMENTS = {
    # xy.pyplot serves as both `plt` and `mpl` (it carries the `dates` module
    # etc.); the reference engine needs the real top-level package for `mpl`.
    # Ordered before the generic rule so it wins for the `mpl` alias.
    "import xy.pyplot as mpl\n": "import matplotlib as mpl\n",
    "import xy.pyplot as ": "import matplotlib.pyplot as ",
    "from xy.pyplot import LinearSegmentedColormap": (
        "from matplotlib.colors import LinearSegmentedColormap"
    ),
    "from xy.pyplot import Legend": "from matplotlib.legend import Legend",
    "from xy.pyplot import Triangulation": "from matplotlib.tri import Triangulation",
    "from xy.pyplot import cycler": "from matplotlib import cycler",
}
ENGINE_NAMES = (
    "plt",
    "mpl",
    "LinearSegmentedColormap",
    "Legend",
    "Triangulation",
    "cycler",
)
# Cross-cell engine state: these variables are written in one cell and read in
# a later cell of the same engine, so the paired cells must not share them —
# an unprefixed `grid = xy_plt.GridSpec(...)` overwrote the matplotlib cell's
# `grid` and fed an xy object into real matplotlib. Prefixed like the aliases,
# but never in kwarg (`ax=ax`), attribute (`ax.grid(...)`), or string
# (`plt.rc("grid", ...)`) positions.
STATE_NAMES = ("fig", "ax", "grid")


def _prefix_state(line: str, prefix: str) -> str:
    for name in STATE_NAMES:
        line = re.sub(
            rf"""(?<![.'"]) \b{name}\b (?!['"]|=(?!=))""",
            f"{prefix}_{name}",
            line,
            flags=re.VERBOSE,
        )
    return line


def notebooks() -> list[Path]:
    return sorted(ROOT.glob("pdsh_*.ipynb"))


def _xy_cells(notebook: dict) -> list[dict]:
    marked = [
        cell
        for cell in notebook["cells"]
        if cell.get("metadata", {}).get("xy_pdsh_engine") == "xy"
        or cell.get("metadata", {}).get("xy_pdsh_source") is True
    ]
    if marked:
        canonical = copy.deepcopy(marked)
        for cell in canonical:
            metadata = cell.setdefault("metadata", {})
            cell["id"] = metadata.get("xy_pdsh_source_id", cell["id"])
            if cell.get("cell_type") == "code":
                if cell.get("source", [None])[0] == "# xy.pyplot\n":
                    cell["source"] = cell["source"][1:]
                if metadata.get("xy_pdsh_auto_show") is True:
                    cell["source"] = cell["source"][:-3]
                for index, line in enumerate(cell.get("source", [])):
                    for name in (*ENGINE_NAMES, *STATE_NAMES):
                        line = re.sub(rf"\bxy_{re.escape(name)}\b", name, line)
                    for name in ENGINE_NAMES[2:]:
                        line = line.replace(f" import {name} as {name}", f" import {name}")
                    cell["source"][index] = line
            for key in (
                "xy_pdsh_engine",
                "xy_pdsh_source",
                "xy_pdsh_source_id",
                "xy_pdsh_auto_show",
            ):
                metadata.pop(key, None)
        return canonical
    return notebook["cells"]


def _engine_cell(cell: dict, engine: str) -> dict:
    made = copy.deepcopy(cell)
    made.setdefault("metadata", {})["xy_pdsh_engine"] = engine
    made["metadata"]["xy_pdsh_source_id"] = cell["id"]
    prefix = "mpl" if engine == "matplotlib" else "xy"
    made["id"] = f"{prefix}-{made['id']}"
    replaced = []
    for line in made.get("source", []):
        if engine == "matplotlib":
            for old, new in IMPORT_REPLACEMENTS.items():
                line = line.replace(old, new)
        for name in ENGINE_NAMES:
            line = re.sub(rf"\b{re.escape(name)}\b", f"{prefix}_{name}", line)
        line = _prefix_state(line, prefix)
        for name in ENGINE_NAMES[2:]:
            line = line.replace(f" import {prefix}_{name}", f" import {name} as {prefix}_{name}")
        replaced.append(line)
    title = "Matplotlib reference" if engine == "matplotlib" else "xy.pyplot"
    made["source"] = [f"# {title}\n", *replaced]
    made["execution_count"] = None
    made["outputs"] = []
    return made


def build(notebook: dict) -> dict:
    xy_cells = copy.deepcopy(_xy_cells(notebook))
    intro = {
        "cell_type": "markdown",
        "id": SHARED_ID,
        "metadata": {"xy_pdsh_engine": "shared"},
        "source": [
            "# Cell-by-cell Matplotlib ↔ xy comparison\n",
            "\n",
            "Run all cells from the top. Every Matplotlib example is immediately followed "
            "by its matching xy.pyplot example, using distinct plotting aliases so the two "
            "engines do not replace one another. xy.pyplot itself flushes open figures at "
            "the end of each Jupyter cell.\n",
        ],
    }
    paired = []
    for cell in xy_cells:
        if cell.get("cell_type") == "markdown":
            shared = copy.deepcopy(cell)
            shared.setdefault("metadata", {})["xy_pdsh_engine"] = "shared"
            shared["metadata"]["xy_pdsh_source"] = True
            shared["metadata"]["xy_pdsh_source_id"] = cell["id"]
            paired.append(shared)
            continue
        paired.extend([_engine_cell(cell, "matplotlib"), _engine_cell(cell, "xy")])
    result = copy.deepcopy(notebook)
    result["cells"] = [intro, *paired]
    result.setdefault("metadata", {})["xy_pdsh_dual_engine"] = True
    return result


def serialized(path: Path) -> str:
    notebook = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(build(notebook), indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path in notebooks():
        expected = serialized(path)
        if args.check:
            if path.read_text(encoding="utf-8") != expected:
                stale.append(path.name)
        else:
            path.write_text(expected, encoding="utf-8")
            print(f"updated {path.name}")
    if stale:
        parser.error("stale dual-engine notebook(s): " + ", ".join(stale))
    if args.check:
        print(f"{len(notebooks())} dual-engine notebooks are fresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
