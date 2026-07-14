"""Run the complete corpus in fresh processes against xy and pinned Matplotlib."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import textwrap
from io import BytesIO

import numpy as np
import pytest
from tests.pyplot.test_corpus import CORPUS

import xy.pyplot as xyplt


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
        import matplotlib
        from matplotlib.axes import Axes
    except ImportError:
        return False
    version = tuple(int(part) for part in matplotlib.__version__.split(".")[:2])
    return version >= (3, 11) and hasattr(Axes, "grouped_bar") and hasattr(Axes, "pie_label")


pytestmark = pytest.mark.skipif(
    not _has_reference_surface(),
    reason="requires the pinned released Matplotlib 3.11 reference",
)


def _run_engine(path: pathlib.Path, engine: str, artifact: pathlib.Path) -> None:
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
    env["XY_REFERENCE_ARTIFACT"] = str(artifact)
    capture = textwrap.dedent(
        """
        import os as _os
        if plt.get_fignums():
            plt.gcf().savefig(_os.environ["XY_REFERENCE_ARTIFACT"], format="png")
        """
    )
    subprocess.run(
        [sys.executable, "-c", bootstrap + "\n" + source + "\n" + capture],
        check=True,
        capture_output=True,
        env=env,
        text=True,
        timeout=60,
    )


def _artifact_geometry(path: pathlib.Path) -> tuple[float, float]:
    pixels = np.asarray(xyplt.imread(BytesIO(path.read_bytes())))
    rgb = pixels[..., :3].astype(np.float64)
    corners = np.stack((rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]))
    background = np.median(corners, axis=0)
    foreground = np.linalg.norm(rgb - background, axis=-1) > 12.0
    if pixels.shape[-1] == 4:
        foreground &= pixels[..., 3] > 12
    ys, xs = np.nonzero(foreground)
    assert len(xs), f"blank reference artifact: {path}"
    ink_fraction = float(np.mean(foreground))
    bbox_aspect = float((xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1))
    return ink_fraction, bbox_aspect


@pytest.mark.parametrize("path", CORPUS, ids=lambda path: path.name)
def test_corpus_in_isolated_reference_process(path: pathlib.Path, tmp_path: pathlib.Path) -> None:
    artifacts = {engine: tmp_path / f"{engine}.png" for engine in ("xy", "matplotlib")}
    for engine, artifact in artifacts.items():
        _run_engine(path, engine, artifact)
        assert artifact.exists(), f"{engine} did not produce a comparison artifact"
    xy_ink, xy_aspect = _artifact_geometry(artifacts["xy"])
    mpl_ink, mpl_aspect = _artifact_geometry(artifacts["matplotlib"])
    # These are deliberately renderer-tolerant but materially compare output:
    # a missing family, wildly wrong layout, or mostly blank render fails.
    assert 0.2 < xy_ink / mpl_ink < 5.0
    assert 0.5 < xy_aspect / mpl_aspect < 2.0
