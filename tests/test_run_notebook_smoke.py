from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
                "metadata": {
                    "kernelspec": {
                        "display_name": "Python 3",
                        "language": "python",
                        "name": "python3",
                    }
                },
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
            f"from pathlib import Path\nPath({str(marker)!r}).write_text(str(value + 2));\n",
        ],
    )

    case = notebook_smoke.NotebookCase("ok", notebook, {})

    result = notebook_smoke._execute_notebook(case, cell_timeout=5)

    assert marker.read_text(encoding="utf-8") == "42"
    assert result == notebook_smoke.NotebookResult(code_cells=2, display_outputs=0)


def test_execute_notebook_fails_on_cell_error(tmp_path: Path) -> None:
    notebook = tmp_path / "broken.ipynb"
    _write_notebook(notebook, ["answer = 42\n", "raise RuntimeError('boom')\n"])

    case = notebook_smoke.NotebookCase("broken", notebook, {})

    with pytest.raises(RuntimeError, match="boom"):
        notebook_smoke._execute_notebook(case, cell_timeout=5)


def test_execute_notebook_renders_final_expression(tmp_path: Path) -> None:
    notebook = tmp_path / "display.ipynb"
    marker = tmp_path / "display.txt"
    _write_notebook(
        notebook,
        [
            f"""
class Displayed:
    def _repr_html_(self):
        from pathlib import Path
        Path({str(marker)!r}).write_text("rendered")
        return "<b>ok</b>"

Displayed()
""",
        ],
    )

    case = notebook_smoke.NotebookCase("display", notebook, {})

    result = notebook_smoke._execute_notebook(case, cell_timeout=5)

    assert marker.read_text(encoding="utf-8") == "rendered"
    assert result == notebook_smoke.NotebookResult(code_cells=1, display_outputs=1)


def test_execute_notebook_flushes_xy_pyplot_figures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notebook = tmp_path / "pyplot.ipynb"
    marker = tmp_path / "flush.txt"
    _write_notebook(notebook, ["value = 1\n"])

    class Figure:
        def _repr_html_(self) -> str:
            marker.write_text("flushed", encoding="utf-8")
            return "<div>figure</div>"

    fake_pyplot = SimpleNamespace(
        all_figures=lambda: [Figure()],
        close=lambda target: marker.write_text(
            marker.read_text(encoding="utf-8") + f":{target}",
            encoding="utf-8",
        ),
    )
    monkeypatch.setitem(sys.modules, "xy.pyplot", fake_pyplot)
    case = notebook_smoke.NotebookCase("pyplot", notebook, {})

    result = notebook_smoke._execute_notebook(case, cell_timeout=5)

    assert marker.read_text(encoding="utf-8") == "flushed:all"
    assert result == notebook_smoke.NotebookResult(code_cells=1, display_outputs=1)


def test_execute_notebook_deduplicates_final_expression_pyplot_figure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notebook = tmp_path / "dedupe.ipynb"
    marker = tmp_path / "renders.txt"

    class Figure:
        def __init__(self) -> None:
            self.count = 0

        def _repr_html_(self) -> str:
            self.count += 1
            marker.write_text(str(self.count), encoding="utf-8")
            return "<div>figure</div>"

    figure = Figure()
    fake_pyplot = SimpleNamespace(
        figure=figure,
        all_figures=lambda: [figure],
        close=lambda target: None,
    )
    monkeypatch.setitem(sys.modules, "xy.pyplot", fake_pyplot)
    _write_notebook(
        notebook,
        [
            """
import sys
fig = sys.modules["xy.pyplot"].figure
fig
""",
        ],
    )
    case = notebook_smoke.NotebookCase("dedupe", notebook, {})

    result = notebook_smoke._execute_notebook(case, cell_timeout=5)

    assert marker.read_text(encoding="utf-8") == "1"
    assert result == notebook_smoke.NotebookResult(code_cells=1, display_outputs=1)


def test_execute_notebook_closes_matplotlib_figures_after_each_cell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notebook = tmp_path / "mpl.ipynb"
    closed: list[str] = []
    fake_matplotlib = SimpleNamespace(close=lambda target: closed.append(target))
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", fake_matplotlib)
    _write_notebook(notebook, ["value = 1\n", "value += 1\n"])

    case = notebook_smoke.NotebookCase("mpl", notebook, {})

    result = notebook_smoke._execute_notebook(case, cell_timeout=5)

    assert closed == ["all", "all"]
    assert result == notebook_smoke.NotebookResult(code_cells=2, display_outputs=0)


def test_execute_notebook_rejects_incompatible_kernelspec(tmp_path: Path) -> None:
    notebook = tmp_path / "ruby.ipynb"
    _write_notebook(notebook, ["value = 1\n"])
    payload = json.loads(notebook.read_text(encoding="utf-8"))
    payload["metadata"]["kernelspec"] = {
        "display_name": "Ruby",
        "language": "ruby",
        "name": "ruby",
    }
    notebook.write_text(json.dumps(payload), encoding="utf-8")

    case = notebook_smoke.NotebookCase("ruby", notebook, {})

    with pytest.raises(ValueError, match="unsupported kernelspec"):
        notebook_smoke._execute_notebook(case, cell_timeout=5)


def test_execute_notebook_rejects_nonpositive_timeout(tmp_path: Path) -> None:
    notebook = tmp_path / "timeout.ipynb"
    _write_notebook(notebook, ["value = 1\n"])

    case = notebook_smoke.NotebookCase("timeout", notebook, {})

    with pytest.raises(ValueError, match="timeout must be positive"):
        notebook_smoke._execute_notebook(case, cell_timeout=0)


def test_smoke_profile_preseeds_reduced_gaia_fixture(tmp_path: Path) -> None:
    cases = notebook_smoke.smoke_cases(tmp_path)

    gaia = next(case for case in cases if case.name == "real-world-gaia-reduced")
    csv_path = Path(gaia.env["XY_REAL_WORLD_DATA"]) / f"gaia-dr3-hr-{gaia.env['GAIA_ROWS']}.csv"

    assert csv_path.exists()
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == "bp_rp,phot_g_mean_mag,parallax"
