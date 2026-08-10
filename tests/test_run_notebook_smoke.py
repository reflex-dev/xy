from __future__ import annotations

import json
from pathlib import Path

import pytest
import scripts.run_notebook_smoke as notebook_smoke


def _write_notebook(path: Path, sources: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "execution_count": None,
                        "metadata": {},
                        "outputs": [],
                        "source": source.splitlines(keepends=True),
                    }
                    for source in sources
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )


def test_execute_notebook_runs_cells_top_to_bottom(tmp_path: Path) -> None:
    notebook = tmp_path / "ok.ipynb"
    marker = tmp_path / "marker.txt"
    _write_notebook(
        notebook,
        [
            "value = 40\n",
            f"from pathlib import Path\nPath({str(marker)!r}).write_text(str(value + 2))\n",
        ],
    )

    case = notebook_smoke.NotebookCase("ok", notebook, {})

    notebook_smoke._execute_notebook(case, cell_timeout=5)

    assert marker.read_text(encoding="utf-8") == "42"


def test_execute_notebook_fails_on_cell_error(tmp_path: Path) -> None:
    notebook = tmp_path / "broken.ipynb"
    _write_notebook(notebook, ["answer = 42\n", "raise RuntimeError('boom')\n"])

    case = notebook_smoke.NotebookCase("broken", notebook, {})

    with pytest.raises(RuntimeError, match="boom"):
        notebook_smoke._execute_notebook(case, cell_timeout=5)


def test_smoke_profile_preseeds_reduced_gaia_fixture(tmp_path: Path) -> None:
    cases = notebook_smoke.smoke_cases(tmp_path)

    gaia = next(case for case in cases if case.name == "real-world-gaia-reduced")
    csv_path = Path(gaia.env["XY_REAL_WORLD_DATA"]) / f"gaia-dr3-hr-{gaia.env['GAIA_ROWS']}.csv"

    assert csv_path.exists()
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "bp_rp,phot_g_mean_mag,parallax"
