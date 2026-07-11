"""Returned handles: the mutation surface of matplotlib's artist model.

A handle wraps the *declarative spec entry* an Axes call appended — mutating
it (``set_ydata``, ``set_color``, ``remove``) edits the spec and invalidates
the Axes' cached chart, so the next render/export rebuilds. This covers the
dominant mutation idioms without reproducing matplotlib's artist graph.
"""

from __future__ import annotations

from typing import Any, Optional

from ._colors import resolve_color


class Artist:
    def __init__(self, axes: Any, entry: dict[str, Any]) -> None:
        self._axes = axes
        self._entry = entry  # the mutable spec dict the Axes rendered from

    def _touch(self) -> None:
        self._axes._invalidate()

    def remove(self) -> None:
        self._axes._remove_entry(self._entry)

    def set_label(self, label: str) -> None:
        self._entry["kwargs"]["name"] = str(label)
        self._touch()

    def get_label(self) -> Optional[str]:
        return self._entry["kwargs"].get("name")

    def set_alpha(self, alpha: float) -> None:
        self._entry["kwargs"]["opacity"] = float(alpha)
        self._touch()

    def set_color(self, color: Any) -> None:
        self._entry["kwargs"]["color"] = resolve_color(color)
        self._touch()

    def get_color(self) -> Any:
        return self._entry["kwargs"].get("color")


class Line2D(Artist):
    """Handle for plt.plot lines (and their marker overlays)."""

    def _set_xy(self, index: int, value: Any) -> None:
        if self._entry["kind"] == "@mark" and self._entry.get("factory") == "step":
            args = list(self._entry["args"])
            args[index] = value
            self._entry["args"] = tuple(args)
            self._entry["x" if index == 0 else "y"] = value
            return
        key = "x" if index == 0 else "y"
        if key not in self._entry:
            raise NotImplementedError(
                f"set_{key}data is not supported for segment-backed Line2D handles"
            )
        self._entry[key] = value

    def set_data(self, x: Any, y: Any) -> None:
        self._set_xy(0, x)
        self._set_xy(1, y)
        self._touch()

    def set_xdata(self, x: Any) -> None:
        self._set_xy(0, x)
        self._touch()

    def set_ydata(self, y: Any) -> None:
        self._set_xy(1, y)
        self._touch()

    def get_xdata(self) -> Any:
        return self._entry["x"]

    def get_ydata(self) -> Any:
        return self._entry["y"]

    def set_linewidth(self, w: float) -> None:
        self._entry["kwargs"]["width"] = float(w)
        self._touch()

    set_lw = set_linewidth


class PathCollection(Artist):
    """Handle for plt.scatter marks."""

    def set_offsets(self, xy: Any) -> None:
        import numpy as np

        arr = np.asarray(xy, dtype=np.float64)
        self._entry["x"] = arr[:, 0]
        self._entry["y"] = arr[:, 1]
        self._touch()


class BarContainer(Artist):
    """Handle for plt.bar/barh groups."""

    def __init__(self, axes: Any, entry: dict[str, Any]) -> None:
        super().__init__(axes, entry)
        self.datavalues = entry.get("y")
        self.orientation = entry.get("kwargs", {}).get("orientation", "vertical")
        self.errorbar = None

    @property
    def position_centers(self) -> Any:
        return self._entry.get("x")

    @property
    def bottoms(self) -> Any:
        import numpy as np

        values = np.asarray(self.datavalues, dtype=np.float64)
        base = self._entry.get("kwargs", {}).get("base", 0.0)
        return np.broadcast_to(np.asarray(base, dtype=np.float64), values.shape)

    @property
    def tops(self) -> Any:
        import numpy as np

        return self.bottoms + np.asarray(self.datavalues, dtype=np.float64)


class StepPatch(Artist):
    """Handle for ``stairs`` output backed by a compact core stairs mark."""

    def get_data(self) -> tuple[Any, Any, Any]:
        return (
            self._entry["values"],
            self._entry.get("edges"),
            self._entry["kwargs"].get("base", self._entry.get("baseline", 0.0)),
        )


class StemContainer:
    """Small tuple-compatible analogue of matplotlib's StemContainer."""

    def __init__(self, artist: Artist) -> None:
        self.markerline = artist
        self.stemlines = artist
        self.baseline = artist

    def __iter__(self):
        return iter((self.markerline, self.stemlines, self.baseline))

    def remove(self) -> None:
        self.stemlines.remove()


class ErrorbarContainer:
    """Tuple-compatible errorbar handle without reproducing mpl's artist graph."""

    def __init__(self, artist: Artist, data_line: Optional[Line2D] = None) -> None:
        self.lines = (data_line, (), (artist,))
        self.has_xerr = artist._entry["kwargs"].get("xerr") is not None
        self.has_yerr = artist._entry["kwargs"].get("yerr") is not None
        self._artist = artist

    def __iter__(self):
        return iter(self.lines)

    def remove(self) -> None:
        self._artist.remove()


class ContourSet(Artist):
    """Contour result exposing the commonly inspected compatibility fields."""

    @property
    def levels(self) -> Any:
        return self._entry.get("levels", self._entry["kwargs"].get("levels"))


class PolyCollection(Artist):
    """Generic collection handle used by adapter-composed chart families."""


class Wedge(PolyCollection):
    """Pie wedge backed by a grouped subset of one native sector mesh."""


class PieContainer:
    """Matplotlib 3.11-compatible pie result with legacy tuple unpacking."""

    def __init__(
        self,
        wedges: list[Wedge],
        values: Any,
        normalize: bool,
        texts: list["Text"],
        autotexts: list["Text"],
    ) -> None:
        import numpy as np

        self.wedges = wedges
        self.values = np.asarray(values, dtype=np.float64)
        total = float(np.sum(self.values)) if normalize else 1.0
        self.fracs = self.values / total
        self.normalize = bool(normalize)
        self._texts: list[list[Text]] = [texts]
        if autotexts:
            self._texts.append(autotexts)

    @property
    def texts(self) -> list[list["Text"]]:
        return self._texts

    def add_texts(self, texts: list["Text"]) -> None:
        self._texts.append(texts)

    def remove(self) -> None:
        for wedge in self.wedges:
            wedge.remove()
        for group in self._texts:
            for item in group:
                item.remove()

    def __iter__(self):
        """Keep the pre-3.11 ``wedges, texts[, autotexts]`` idiom working."""
        yield self.wedges
        yield self._texts[0] if self._texts else []
        if len(self._texts) > 1:
            yield self._texts[1]


class GroupedBarReturn:
    """Provisional Matplotlib 3.11 grouped-bar result container."""

    def __init__(self, bar_containers: list[BarContainer]) -> None:
        self.bar_containers = bar_containers

    def remove(self) -> None:
        for container in self.bar_containers:
            container.remove()


class Table:
    """Composite table handle backed by generic mesh, segment, and text marks."""

    def __init__(self, artists: list[Artist], cells: dict[tuple[int, int], "Text"]) -> None:
        self._artists = artists
        self._cells = cells

    def get_celld(self) -> dict[tuple[int, int], "Text"]:
        return dict(self._cells)

    def remove(self) -> None:
        for artist in self._artists:
            artist.remove()


class Text(Artist):
    """Small mutable text handle for pie labels and percentage annotations."""

    def set_text(self, text: str) -> None:
        x, y, _old = self._entry["args"]
        self._entry["args"] = (x, y, str(text))
        self._touch()

    def get_text(self) -> str:
        return str(self._entry["args"][2])


class StreamplotSet:
    """Result container matching Matplotlib's ``lines``/``arrows`` surface."""

    def __init__(self, lines: PolyCollection, arrows: PolyCollection) -> None:
        self.lines = lines
        self.arrows = arrows
