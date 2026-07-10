"""rcParams subset. Unknown keys warn once and are ignored — scripts that
tune exotic rcParams keep running, and the warning names the compat table."""

from __future__ import annotations

import warnings
from typing import Any

from ._translate import COMPAT_URL

_DEFAULTS: dict[str, Any] = {
    "figure.figsize": (6.4, 4.8),  # inches, matplotlib default
    "figure.dpi": 100.0,
    "lines.linewidth": 1.5,
    "lines.markersize": 6.0,
    "font.size": 10.0,
    "axes.grid": False,
    "axes.titlesize": "large",
    "legend.loc": "best",
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
        super().__setitem__(key, value)

    def reset(self) -> None:
        self.clear()
        self.update(_DEFAULTS)


rcParams = RcParams()
rcParams.update(_DEFAULTS)


def rc_figsize_px(figsize: Any = None, dpi: Any = None) -> tuple[int, int]:
    """(figsize inches, dpi) → engine pixel dimensions."""
    w_in, h_in = figsize if figsize is not None else rcParams["figure.figsize"]
    d = float(dpi if dpi is not None else rcParams["figure.dpi"])
    return max(1, round(w_in * d)), max(1, round(h_in * d))
