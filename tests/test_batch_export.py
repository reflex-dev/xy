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
    with pytest.raises(ValueError, match=r"custom_css requires engine=Engine.chromium"):
        export.write_images(
            [_fig(1)],
            [tmp_path / "x.png"],
            engine=export.Engine.default,
            custom_css=".xy { color: red; }",
        )


def test_write_images_auto_engine_routes_custom_css_to_browser(tmp_path, monkeypatch):
    # Engine.auto is deterministic: custom_css needs a real CSS engine, so the
    # batch resolves to the browser path (and reports the dependency clearly
    # when no browser is installed) instead of rejecting the argument.
    monkeypatch.setattr(export, "find_browser", lambda explicit=None: None)
    with pytest.raises(RuntimeError, match="browser image export"):
        export.write_images(
            [_fig(1)],
            [tmp_path / "x.png"],
            custom_css=".xy { color: red; }",
        )


def test_write_images_chromium_engine_is_deprecated_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(export, "find_browser", lambda explicit=None: None)
    with (
        pytest.warns(DeprecationWarning, match="string export engines"),
        pytest.raises(RuntimeError, match="browser image export"),
    ):
        export.write_images(
            [_fig(1)],
            [tmp_path / "x.png"],
            engine="chromium",
        )


def test_write_images_chromium_threads_custom_css(tmp_path, monkeypatch):
    from xy import _chromium

    seen = []

    class FakeSession:
        def __init__(self, *_args, **_kwargs):
            pass

        def close(self):
            pass

        def render_image(self, html, _width, _height, *, format, scale, quality, transparent):
            seen.append((html, format, scale, quality, transparent))
            return b"\x89PNG\r\n\x1a\nbatch"

    monkeypatch.setattr(export, "find_browser", lambda explicit=None: "/fake/chrome")
    monkeypatch.setattr(_chromium, "ChromiumSession", FakeSession)
    css = '[data-xy-slot="title"] { color: rebeccapurple; }'
    path = tmp_path / "x.png"

    result = export.write_images(
        [_fig(1)],
        [path],
        engine=export.Engine.chromium,
        custom_css=css,
    )

    assert result == [path.read_bytes()]
    assert f"<style>{css}</style>" in seen[0][0]
    assert seen[0][1] == "png"
    assert seen[0][2] == 2.0
