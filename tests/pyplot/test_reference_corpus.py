"""Run the complete corpus in fresh processes against xy and pinned Matplotlib."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap

import pytest
from tests.pyplot.test_corpus import CORPUS


def _adapt_reference_source(path: pathlib.Path, source: str) -> str:
    """Normalize the few intentional xy shorthand signatures for Matplotlib.

    The source corpus remains dependency-free.  Matplotlib's triangular APIs
    require a ``Triangulation`` positional object where xy also accepts a
    ``triangles=`` keyword alongside x/y arrays.
    """
    if path.name == "49_unstructured_mesh.py":
        source = source.replace(
            "fig, axes = plt.subplots(1, 3, figsize=(10, 3))",
            "from matplotlib.tri import Triangulation\n\n"
            "triangulation = Triangulation(x, y, triangles)\n\n"
            "fig, axes = plt.subplots(1, 3, figsize=(10, 3))",
        )
        source = source.replace(
            'axes[0].tripcolor(x, y, z, triangles=triangles, cmap="viridis")',
            'axes[0].tripcolor(triangulation, z, cmap="viridis")',
        )
        source = source.replace(
            'axes[1].triplot(x, y, "k-", triangles=triangles)',
            'axes[1].triplot(triangulation, "k-")',
        )
        source = source.replace(
            "axes[1].tricontour(x, y, z, triangles=triangles, levels=4)",
            "axes[1].tricontour(triangulation, z, levels=4)",
        )
        source = source.replace(
            'axes[2].tricontourf(x, y, z, triangles=triangles, levels=5, cmap="plasma")',
            'axes[2].tricontourf(triangulation, z, levels=5, cmap="plasma")',
        )
    return source


def _has_reference_surface() -> bool:
    try:
        from matplotlib.axes import Axes
    except ImportError:
        return False
    return hasattr(Axes, "grouped_bar") and hasattr(Axes, "pie_label")


pytestmark = pytest.mark.skipif(
    not _has_reference_surface(),
    reason="requires the pinned Matplotlib 3.11 development reference",
)


@pytest.mark.parametrize("path", CORPUS, ids=lambda path: path.name)
@pytest.mark.parametrize("engine", ["xy", "matplotlib"])
def test_corpus_in_isolated_reference_process(path: pathlib.Path, engine: str) -> None:
    source = path.read_text()
    if engine == "matplotlib":
        source = source.replace("import xy.pyplot as plt", "import matplotlib.pyplot as plt")
        source = _adapt_reference_source(path, source)
    bootstrap = ""
    if engine == "matplotlib":
        # HTML is an xy exporter, not part of Matplotlib's renderer contract.
        # Keep those corpus cases exercising all chart construction while making
        # their final exporter call an explicit reference-side no-op.
        bootstrap = textwrap.dedent(
            """
            from pathlib import Path
            from matplotlib.figure import Figure
            _reference_savefig = Figure.savefig
            def _savefig(self, target, *args, **kwargs):
                if isinstance(target, (str, Path)) and Path(target).suffix == ".html":
                    return None
                return _reference_savefig(self, target, *args, **kwargs)
            Figure.savefig = _savefig
            """
        )
    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    subprocess.run(
        [sys.executable, "-c", bootstrap + "\n" + source],
        check=True,
        capture_output=True,
        env=env,
        text=True,
        timeout=60,
    )
