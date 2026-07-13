from __future__ import annotations

import builtins

import numpy as np
import pytest

from xy import pyplot as plt
from xy.pyplot._transforms import Affine2D, Bbox, IdentityTransform


def test_owned_artist_views_children_and_removal_are_stable() -> None:
    _fig, ax = plt.subplots()
    line = ax.plot([0, 1], [1, 2])[0]
    points = ax.scatter([0, 1], [2, 3])
    image = ax.imshow([[0, 1], [1, 0]])
    text = ax.text(0.5, 0.5, "hello")
    bars = ax.bar([0, 1], [2, 3])

    assert ax.lines == [line]
    assert points in ax.collections
    assert ax.images == [image]
    assert ax.texts == [text]
    assert bars in ax.containers
    children = ax.get_children()
    assert children == ax.get_children()
    assert all(item in children for item in (line, points, image, text, bars))

    points.remove()
    bars.remove()
    assert points not in ax.collections
    assert bars not in ax.containers
    assert points not in ax.get_children()


def test_artist_common_properties_apply_or_fail_loudly() -> None:
    _fig, ax = plt.subplots()
    low, high = ax.plot([0, 1], [0, 1], [0, 1], [1, 0])
    low.set_label("diagonal")
    low.set_alpha(0.4)
    low.set_visible(False)
    assert not low.get_visible()
    low.set_visible(True)
    assert low.get_visible() and low.get_alpha() == pytest.approx(0.4)

    high.set_zorder(-2)
    assert high.get_zorder() == -2
    assert ax._entries[0] is high._entry
    low.set_transform(IdentityTransform())
    assert isinstance(low.get_transform(), IdentityTransform)
    with pytest.raises(NotImplementedError, match="transformed images"):
        low.set_transform(Affine2D().translate(1, 2))
    with pytest.raises(NotImplementedError, match="unclipped"):
        low.set_clip_on(False)
    with pytest.raises(NotImplementedError, match="clip paths"):
        low.set_clip_path(object())


def test_dependency_free_bbox_affine_image_norm_and_text_extent(monkeypatch) -> None:
    real_import = builtins.__import__

    def block_matplotlib(name, *args, **kwargs):
        if name.startswith("matplotlib"):
            raise ImportError("blocked by dependency-free contract")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_matplotlib)
    _fig, ax = plt.subplots()
    assert isinstance(ax.get_position(), Bbox)
    transform = Affine2D().scale(2).translate(3, 4)
    np.testing.assert_allclose(
        transform.inverted().transform(transform.transform([[1, 2]])), [[1, 2]]
    )

    cmap = plt.get_cmap("viridis").with_extremes(bad="red", under="blue", over="yellow")
    image = ax.imshow([[np.nan, -1], [0.5, 2]], cmap=cmap, vmin=0, vmax=1)
    assert image._entry["z"].shape == (2, 2, 4)
    image.set_transform(Affine2D().translate(1, 1))
    assert image._entry["z"].shape[-1] == 4
    assert ax.text(0.5, 0.5, "extent").get_window_extent().width > 0


def test_add_adapters_are_bounded_and_unknown_artists_are_rejected() -> None:
    _fig, ax = plt.subplots()

    class LineLike:
        def get_data(self):
            return [0, 1], [2, 3]

        def get_color(self):
            return "red"

    line = ax.add_line(LineLike())
    assert line in ax.lines and line.get_color() == "red"
    assert ax.add_container(ax.bar([0], [1])) in ax.containers
    with pytest.raises(TypeError, match="supported container"):
        ax.add_container(object())
    with pytest.raises(TypeError, match="create tables"):
        ax.add_table(object())
    with pytest.raises(TypeError, match=r"use text\(\), imshow\(\)"):
        ax.add_artist(object())
