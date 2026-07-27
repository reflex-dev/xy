#!/usr/bin/env python3
"""Re-run the three audited PDSH xy cells and capture only affected figures."""

from __future__ import annotations

import hashlib
import json
import os
import zlib
from pathlib import Path
from typing import Any

import numpy as np

import xy.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
TARGETS = (
    {
        "notebook": "pdsh_04_01_simple_line_plots.ipynb",
        "raw_cell_index": 36,
        "execution_ordinal": 14,
        "source_id": "cb1e1581032b452c9409d6c6813c49d1",
    },
    {
        "notebook": "pdsh_04_07_customizing_colorbars.ipynb",
        "raw_cell_index": 23,
        "execution_ordinal": 8,
        "source_id": "59bbdb311c014d738909a11f9e486628",
    },
    {
        "notebook": "pdsh_04_10_customizing_ticks.ipynb",
        "raw_cell_index": 14,
        "execution_ordinal": 4,
        "source_id": "7623eae2785240b9bd12b16a66d81610",
    },
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save(figure: Any, name: str) -> dict[str, Any]:
    path = OUTPUT / name
    figure.savefig(path, dpi=100)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "figure_number": figure.number,
        "axes_count": len(figure.axes),
    }


def _xy_cells(notebook: dict[str, Any], through: int) -> list[tuple[int, dict[str, Any]]]:
    return [
        (index, cell)
        for index, cell in enumerate(notebook["cells"])
        if index <= through
        and cell.get("cell_type") == "code"
        and cell.get("metadata", {}).get("xy_pdsh_engine") == "xy"
    ]


def _run(target: dict[str, Any]) -> dict[str, Any]:
    plt.close("all")
    path = ROOT / "examples" / "pdsh" / target["notebook"]
    notebook = json.loads(path.read_text(encoding="utf-8"))
    target_cell = notebook["cells"][target["raw_cell_index"]]
    assert target_cell["metadata"]["xy_pdsh_source_id"] == target["source_id"]
    namespace: dict[str, Any] = {"__name__": "__main__"}
    before_mutation: dict[str, Any] | None = None
    source_ownership: list[bool] = []

    old_cwd = Path.cwd()
    os.chdir(path.parent)
    try:
        for index, cell in _xy_cells(notebook, target["raw_cell_index"]):
            source_id = cell["metadata"]["xy_pdsh_source_id"]
            np.random.seed(zlib.crc32(f"{path.name}:{source_id}".encode()))
            if index == target["raw_cell_index"] and target["execution_ordinal"] in {4, 14}:
                # Preserve notebook variables but isolate the cell's own
                # figure, matching an inline backend's close-after-display
                # lifecycle instead of accumulating earlier cell figures.
                plt.close("all")
            if target["execution_ordinal"] == 8 and index == target["raw_cell_index"]:
                source_figure = plt.figure(1)
                before_mutation = _save(
                    source_figure,
                    "04_07-ordinal-08-raw-23-source-figure-before.png",
                )
                logical = namespace["I"]
                source_ownership = [
                    not np.shares_memory(np.asarray(image.get_array()), logical)
                    and not np.shares_memory(np.asarray(image._entry["z"]), logical)
                    for image in source_figure.axes[0].images
                ]
            exec(
                compile("".join(cell.get("source", [])), f"{path.name}:cell-{index}", "exec"),
                namespace,
            )
    finally:
        os.chdir(old_cwd)

    current = plt.gcf()
    if target["execution_ordinal"] == 14:
        outputs = [_save(current, "04_01-ordinal-14-raw-36-current-figure.png")]
        assertions = {
            "fresh_axes_count": len(current.axes),
            "new_axes_is_current": current.gca() is current.axes[-1],
            "new_axes_title": current.axes[-1].get_title(),
        }
    elif target["execution_ordinal"] == 8:
        assert before_mutation is not None
        source_after = _save(
            plt.figure(1),
            "04_07-ordinal-08-raw-23-source-figure-after.png",
        )
        target_output = _save(current, "04_07-ordinal-08-raw-23-target-figure.png")
        outputs = [before_mutation, source_after, target_output]
        assertions = {
            "preexisting_image_arrays_owned": source_ownership,
            "preexisting_figure_unchanged_by_I_mutation": (
                before_mutation["sha256"] == source_after["sha256"]
            ),
            "target_axes_count": len(current.axes),
        }
    else:
        outputs = [_save(current, "04_10-ordinal-04-raw-14-current-figure.png")]
        assertions = {
            "fresh_axes_count": len(current.axes),
            "new_axes_is_current": current.gca() is current.axes[-1],
            "target_xscale": current.axes[-1]._scale_specs["x"]["name"],
            "new_y_major_locator": type(current.axes[-1].yaxis.get_major_locator()).__name__,
        }
    return {
        **target,
        "source": "".join(target_cell.get("source", [])),
        "outputs": outputs,
        "assertions": assertions,
    }


def main() -> None:
    report = {
        "base_commit": "a2ac10e",
        "capture_scope": (
            "Exact affected xy cell after executing its preceding xy notebook variables. "
            "04_01 and 04_10 close earlier figures before the target, matching inline "
            "cell lifecycle; 04_07 additionally preserves its mutation-affected source "
            "figure for before/after ownership evidence."
        ),
        "targets": [_run(target) for target in TARGETS],
    }
    (OUTPUT / "provenance.json").write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
