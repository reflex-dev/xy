"""`export.write_images` batch API: contract + browser-free native branch.

The browser branch (persistent CDP session amortizing browser startup) is
exercised by live-browser measurement, not unit tests, matching the repo's
convention that real-browser paths are validated by scripts/*smoke*. These
tests pin the argument contract and the native loop, which need no browser.
"""

from __future__ import annotations

import numpy as np
import pytest

from xy import export
from xy._figure import Figure


def _fig(seed: int) -> Figure:
    rng = np.random.default_rng(seed)
    return Figure(width=320, height=200).scatter(rng.uniform(0, 1, 500), rng.uniform(0, 1, 500))


def test_write_images_native_batch(tmp_path):
    figs = [_fig(1), _fig(2), _fig(3)]
    paths = [tmp_path / f"chart-{i}.png" for i in range(3)]
    out = export.write_images(figs, paths)
    assert len(out) == 3
    for data, path in zip(out, paths, strict=True):
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert path.read_bytes() == data


def test_write_images_length_mismatch_rejected(tmp_path):
    with pytest.raises(ValueError, match="2 figures but 1 paths"):
        export.write_images([_fig(1), _fig(2)], [tmp_path / "one.png"])


def test_write_images_rejects_bad_engine_and_gl(tmp_path):
    with pytest.raises(ValueError, match="engine"):
        export.write_images([_fig(1)], [tmp_path / "x.png"], engine="webgpu")
    with pytest.raises(ValueError, match="gl"):
        export.write_images([_fig(1)], [tmp_path / "x.png"], gl="metal")


def test_write_images_chromium_engine_is_deprecated_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "find_browser", lambda explicit=None: None)
    with (
        pytest.warns(DeprecationWarning, match="string export engines"),
        pytest.raises(RuntimeError, match="browser PNG export"),
    ):
        export.write_images(
            [_fig(1)],
            [tmp_path / "x.png"],
            engine="chromium",
        )
