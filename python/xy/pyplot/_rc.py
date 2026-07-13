"""rcParams subset. Unknown keys warn once and are ignored — scripts that
tune exotic rcParams keep running, and the warning names the compat table."""

from __future__ import annotations

import contextlib
import warnings
from typing import Any

from ._translate import COMPAT_URL


class _PropCycle:
    def __init__(self, colors: Any = None) -> None:
        self._colors = None if colors is None else tuple(str(color) for color in colors)

    def by_key(self) -> dict[str, list[str]]:
        from ._colors import PROP_CYCLE

        return {"color": list(self._colors or PROP_CYCLE)}


_DEFAULTS: dict[str, Any] = {
    "figure.figsize": (6.4, 4.8),  # inches, matplotlib default
    "figure.dpi": 100.0,
    "figure.facecolor": "white",
    "lines.linewidth": 1.5,
    "lines.markersize": 6.0,
    "font.size": 10.0,
    "font.family": ["sans-serif"],
    "axes.grid": False,
    "grid.color": "#b0b0b0",
    "axes.facecolor": "white",
    "axes.edgecolor": "black",
    "axes.labelcolor": "black",
    "axes.labelsize": "medium",
    "axes.titlesize": "large",
    "axes.titlecolor": "auto",
    "axes.spines.left": True,
    "axes.spines.bottom": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "xtick.color": "black",
    "ytick.color": "black",
    "xtick.labelcolor": "inherit",
    "ytick.labelcolor": "inherit",
    "xtick.labelsize": "medium",
    "ytick.labelsize": "medium",
    "legend.loc": "best",
    "legend.fontsize": "medium",
    "legend.facecolor": "inherit",
    "legend.edgecolor": "#cccccc",
    "legend.frameon": True,
    "text.usetex": False,
    "image.cmap": "viridis",
    "image.origin": "upper",
    "axes.prop_cycle": _PropCycle(),
}

_warned: set[str] = set()


class RcParams(dict):
    """Dict with matplotlib's validate-on-set flavor, reduced to warn-on-unknown."""

    def __setitem__(self, key: str, value: Any) -> None:
        if key not in _DEFAULTS and key not in _warned:
            _warned.add(key)
            warnings.warn(
                f"xy.pyplot ignores rcParams[{key!r}] — see {COMPAT_URL}",
                stacklevel=2,
            )
        if key in {"axes.spines.left", "axes.spines.bottom"} and value is not True:
            raise NotImplementedError(
                f"xy.pyplot cannot hide {key.removeprefix('axes.spines.')} spines independently"
            )
        if key in {"axes.spines.top", "axes.spines.right"} and value is not False:
            raise NotImplementedError(
                f"xy.pyplot does not render {key.removeprefix('axes.spines.')} spines"
            )
        if key == "axes.prop_cycle":
            by_key = getattr(value, "by_key", None)
            colors = by_key().get("color") if by_key is not None else None
            if not colors:
                raise ValueError("axes.prop_cycle must provide a non-empty color cycle")
        if key in {"font.size"}:
            value = float(value)
            if value <= 0:
                raise ValueError(f"{key} must be positive")
        if isinstance(value, list):
            value = list(value)  # never share list defaults; rcdefaults() must stay pristine
        super().__setitem__(key, value)

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        # C-level dict.update skips __setitem__; route every entry point
        # (style.use, rc_context, reset) through the same validation.
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def reset(self) -> None:
        self.clear()
        self.update(_DEFAULTS)


rcParams = RcParams()
rcParams.update(_DEFAULTS)


def rc(group: str, **kwargs: Any) -> None:
    """Set the supported ``group.key`` rcParams used by gallery-style scripts."""
    aliases = {"lw": "linewidth", "ms": "markersize"}
    for key, value in kwargs.items():
        rcParams[f"{group}.{aliases.get(key, key)}"] = value


def rc_figsize_px(figsize: Any = None, dpi: Any = None) -> tuple[int, int]:
    """(figsize inches, dpi) → engine pixel dimensions."""
    w_in, h_in = figsize if figsize is not None else rcParams["figure.figsize"]
    d = float(dpi if dpi is not None else rcParams["figure.dpi"])
    return max(1, round(w_in * d)), max(1, round(h_in * d))


def rcdefaults() -> None:
    rcParams.reset()


@contextlib.contextmanager
def rc_context(rc: dict[str, Any] | None = None):
    old = dict(rcParams)
    try:
        if rc:
            rcParams.update(rc)
        yield
    finally:
        rcParams.clear()
        rcParams.update(old)
