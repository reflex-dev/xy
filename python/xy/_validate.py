"""Shared public-argument validators.

Before this module the same "reject bool → coerce → assert finite", "positive
int", and "finite-increasing pair" primitives were hand-reimplemented across
`figure`, `components`, `channels`, `_native`, `lod`, `interaction`, and
`export` — several under identical names with identical error strings. They now
live here once; the other modules alias these (so `Figure._finite_scalar`,
`components._axis_id`, etc. keep working with zero call-site churn) and the
error messages are unchanged, which the builder/mutation-safety tests assert.

Every function takes `(value, label)` and either returns the validated value or
raises `ValueError` (occasionally `TypeError`) naming `label`.
"""

from __future__ import annotations

import itertools
import re
from functools import lru_cache
from typing import Any, Optional

import numpy as np

_TICK_LABEL_STRATEGIES = frozenset({"auto", "hide", "rotate", "stagger", "none", "off"})
# Canonical anchors plus the matplotlib `ha` vocabulary the pyplot shim emits.
_TICK_LABEL_ANCHORS = {
    "start": "start",
    "center": "center",
    "end": "end",
    "left": "start",
    "middle": "center",
    "right": "end",
}
_LABEL_POSITIONS = frozenset(
    {"start", "center", "end", "inside_start", "inside_center", "inside_end"}
)
_CURVES = frozenset({"linear", "smooth"})
_FILL_SPACES = frozenset({"mark", "plot"})
# CSS `<side-or-corner>` keywords -> wire direction. In mark space the gradient
# line runs along each mark's value axis ("bottom" = the base, "top" = the
# tip/line, matching the visual for vertical marks); in plot space it runs
# across the plot box in screen directions. Angles and corner keywords are
# rejected — GPU marks get the four axis-aligned directions.
_GRADIENT_DIRS = {"to top": "up", "to bottom": "down", "to left": "left", "to right": "right"}


def finite_scalar(value: Any, label: str) -> float:
    """A finite real number (rejects bool and non-finite)."""
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite real number")
    try:
        out = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must be a finite real number") from e
    if not np.isfinite(out):
        raise ValueError(f"{label} must be finite")
    return out


def finite_increasing_pair(values: Any, label: str) -> tuple[float, float]:
    """Exactly two finite values with `hi > lo`."""
    try:
        lo_raw, hi_raw = values
    except (TypeError, ValueError) as e:
        raise ValueError(f"{label} must contain exactly two finite values") from e
    lo = finite_scalar(lo_raw, f"{label}[0]")
    hi = finite_scalar(hi_raw, f"{label}[1]")
    if hi <= lo:
        raise ValueError(f"{label} must be finite and increasing")
    return lo, hi


def positive_scalar(value: Any, label: str) -> float:
    out = finite_scalar(value, label)
    if out <= 0:
        raise ValueError(f"{label} must be positive")
    return out


def nonnegative_scalar(value: Any, label: str) -> float:
    out = finite_scalar(value, label)
    if out < 0:
        raise ValueError(f"{label} must be non-negative")
    return out


def optional_finite_scalar(value: Any, label: str) -> Optional[float]:
    if value is None:
        return None
    return finite_scalar(value, label)


def optional_nonnegative_scalar(value: Any, label: str) -> Optional[float]:
    if value is None:
        return None
    return nonnegative_scalar(value, label)


def optional_positive_int(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{label} must be a positive integer")
    out = int(value)
    if out <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return out


def opacity(value: Any, label: str) -> float:
    out = finite_scalar(value, label)
    if out < 0 or out > 1:
        raise ValueError(f"{label} must be between 0 and 1")
    return out


def optional_bool(value: Any, label: str) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise ValueError(f"{label} must be True, False, or None")


def bool_param(value: Any, label: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    raise ValueError(f"{label} must be True or False")


def optional_text(value: Any, label: str) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    raise ValueError(f"{label} must be a string or None")


#: Legend placements, in Matplotlib's vocabulary. `best` is resolved to one of
#: the others at payload-build time (`xy._legendfit`).
LEGEND_LOCATIONS: tuple[str, ...] = (
    "best",
    "upper right",
    "upper left",
    "lower left",
    "lower right",
    "upper center",
    "lower center",
    "center left",
    "center right",
    "center",
)


#: Unambiguous synonyms for the vertical band. Matplotlib says `upper`/`lower`;
#: CSS, Plotly and XY's own docs say `top`/`bottom`. Both name the same edge, so
#: both are accepted rather than made into a trap.
_LEGEND_LOC_SYNONYMS: dict[str, str] = {"top": "upper", "bottom": "lower"}


def legend_loc(value: Any, label: str) -> Optional[str]:
    """A legend placement, or None for the default.

    The writers resolve a location by substring and by token, so an
    unrecognized string never failed — it silently landed somewhere.
    `"northeast"` and `"best"` parked the legend dead center, on top of the
    data. Close the vocabulary instead: refuse what is genuinely a guess.

    The caller's **spelling is preserved** (lowercased, so `_legend_layout`'s
    token match sees it). `top`/`bottom` are public core aliases for
    `upper`/`lower` that `_svg._legend_layout` resolves to the same geometry;
    rewriting them here would change a value the pyplot compatibility suite
    pins as passthrough.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or None")
    normalized = " ".join(value.lower().split())
    tokens = [token for token in re.split(r"[\s_-]+", normalized) if token]
    # Aliases are folded for the CHECK only, never in what is returned.
    canonical = " ".join(_LEGEND_LOC_SYNONYMS.get(token, token) for token in tokens)
    recognized = (
        canonical in LEGEND_LOCATIONS
        # Matplotlib takes either word order for the two-word forms.
        or (len(tokens) == 2 and " ".join(reversed(canonical.split())) in LEGEND_LOCATIONS)
        # `right`/`left` alone are Matplotlib's codes 5/6 — the centered edges.
        or canonical in ("right", "left")
    )
    if recognized:
        return normalized
    options = ", ".join(repr(name) for name in LEGEND_LOCATIONS)
    raise ValueError(f"{label} {value!r} is not a legend location; expected one of: {options}")


def axis_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    if value[0] not in {"x", "y"}:
        raise ValueError(f"{label} must start with 'x' or 'y'")
    if not all(ch.isalnum() or ch in {"_", "-"} for ch in value):
        raise ValueError(f"{label} may only contain letters, digits, '_' and '-'")
    return value


def axis_tick_label_strategy(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or None")
    normalized = value.replace("-", "_")
    if normalized not in _TICK_LABEL_STRATEGIES:
        raise ValueError(f"{label} must be one of {sorted(_TICK_LABEL_STRATEGIES)}")
    return normalized


def axis_tick_label_anchor(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string or None")
    normalized = _TICK_LABEL_ANCHORS.get(value.lower())
    if normalized is None:
        raise ValueError(
            f"{label} must be one of ['center', 'end', 'start'] "
            "(or the aliases 'left', 'middle', 'right')"
        )
    return normalized


def string_mapping(value: dict[str, Any], label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dict[str, str]")
    out: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"{label} must be a dict[str, str]")
        out[key] = item
    return out


# xy_css_check error codes -> human reasons (the negated CssErr
# discriminants; keep in sync with src/css.rs).
_CSS_ERROR_REASONS = {
    -1: "is empty",
    -2: "contains an unsafe character (';', '{', '}', '</', or a control character)",
    -3: "has unbalanced quotes or parentheses",
    -4: "is not a valid hex color (use #rgb, #rgba, #rrggbb, or #rrggbbaa)",
    -5: "is not valid color syntax",
    -6: "is not a recognized CSS color name",
    -7: "has an invalid number",
    -8: "has an unknown unit",
    -9: "uses an unknown function",
    -10: "is not a valid CSS property name",
}


@lru_cache(maxsize=1024)
def _css_check(kind: int, value: str, prop: str = "") -> int:
    # Pure function of its string arguments (the native grammar is static),
    # so the verdict is memoized — dashboards re-validate the same palette
    # colors and style declarations on every chart build.
    # Lazy import: these validators run at chart-build time, inside the
    # compute import boundary (§33) — but this module itself must stay
    # importable without loading the native core.
    from . import kernels

    return kernels.css_check(kind, value, prop)[0]


def _css_reason(status: int) -> str:
    return _CSS_ERROR_REASONS.get(status, "is not valid CSS")


def css_color(value: Any, label: str) -> str:
    """A CSS `<color>` literal. Closed grammars (hex, `rgb()`/`hsl()`, the
    full named-color table, `transparent`, `currentColor`) parse strictly in
    the native core (src/css.rs); browser-resolved forms (`var()`,
    `oklch()`, `color-mix()`, ...) are shape-checked and passed through. A
    malformed color errors loudly here instead of rendering as a silently
    wrong mark color (§28: no silent decisions)."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a CSS color string")
    from . import kernels

    status = _css_check(kernels.CSS_COLOR, value)
    if status <= 0:
        raise ValueError(f"{label} {value!r} {_css_reason(status)}")
    return value.strip()


def optional_css_color(value: Any, label: str) -> Optional[str]:
    if value is None:
        return None
    return css_color(value, label)


def _css_property_name(key: str) -> str:
    """The declaration-check name for a style key: the Python API accepts
    snake_case (`font_size`), CSS wants kebab (`font-size`); custom
    properties keep their `--` prefix."""
    if key.startswith("--"):
        return "--" + key[2:].replace("_", "-")
    return key.replace("_", "-")


# Validated style dicts, keyed by their exact items. Chart chrome ships the
# same few style dicts on every build (theme fonts, rc-derived title/tick
# slots), and validating one is pure — so each distinct dict validates once
# per process, not once per chart build (the pyplot perf guardrail counts on
# this). Only successful validations are cached; the type names keep e.g.
# True from hitting a cached 1 (equal, same hash, different verdict).
_STYLE_MAPPING_CACHE: dict[tuple, dict[str, str | int | float]] = {}


def style_mapping(value: dict[str, Any], label: str) -> dict[str, str | int | float]:
    if isinstance(value, dict):
        try:
            key = (
                label,
                tuple((k, v, type(v).__name__) for k, v in value.items()),
            )
            cached = _STYLE_MAPPING_CACHE.get(key)
        except TypeError:  # unhashable value: validate (and likely raise) below
            key = cached = None
        if cached is not None:
            return dict(cached)
    else:
        key = None
    out = _validate_style_mapping(value, label)
    if key is not None:
        if len(_STYLE_MAPPING_CACHE) > 4096:
            _STYLE_MAPPING_CACHE.clear()
        _STYLE_MAPPING_CACHE[key] = dict(out)
    return out


def _validate_style_mapping(value: dict[str, Any], label: str) -> dict[str, str | int | float]:
    from . import kernels

    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a dict[str, str | int | float]")
    out: dict[str, str | int | float] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(
            item, (str, int, float, np.integer, np.floating)
        ):
            raise ValueError(f"{label} must be a dict[str, str | int | float]")
        if isinstance(item, (bool, np.bool_)):
            raise ValueError(f"{label} must be a dict[str, str | int | float]")
        number = float(item) if isinstance(item, (int, float, np.integer, np.floating)) else None
        if number is not None and not np.isfinite(number):
            raise ValueError(f"{label} numeric values must be finite")
        if isinstance(item, str):
            # A string value is one CSS declaration: closed grammars
            # (color/length/number properties) parse strictly, unknown
            # properties pass through with declaration-context safety intact
            # (src/css.rs; numeric values follow the px convention instead).
            status = _css_check(kernels.CSS_DECLARATION, item, _css_property_name(key))
            if status <= 0:
                raise ValueError(f"{label}[{key!r}] {item!r} {_css_reason(status)}")
        out[key] = item.item() if isinstance(item, (np.integer, np.floating)) else item
    return out


def plot_padding(value: Any, label: str) -> Optional[list[float]]:
    """Plot-margin override: None (auto), a scalar (all four sides), or a
    (top, right, bottom, left) sequence — each a non-negative px value."""
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, (bool, np.bool_)
    ):
        side = nonnegative_scalar(value, label)
        return [side, side, side, side]
    if isinstance(value, str) or not hasattr(value, "__iter__"):
        raise ValueError(f"{label} must be a number or a (top, right, bottom, left) sequence")
    sides = list(value)
    if len(sides) != 4:
        raise ValueError(f"{label} sequence must have 4 values (top, right, bottom, left)")
    return [nonnegative_scalar(s, f"{label}[{i}]") for i, s in enumerate(sides)]


def curve(value: Any, label: str) -> str:
    """Line/area interpolation: 'linear' or 'smooth' (monotone cubic)."""
    if not isinstance(value, str) or value not in _CURVES:
        raise ValueError(f"{label} must be one of {sorted(_CURVES)}")
    return value


_POINT_SYMBOLS = frozenset(
    {
        "circle",
        "square",
        "diamond",
        "triangle",
        "triangle_down",
        "triangle_left",
        "triangle_right",
        "cross",
        "x",
        "hexagon",
        "pentagon",
        "star",
        "point",
        "pixel",
        "thin_diamond",
        "plus_line",
        "x_line",
        "horizontal_line",
        "vertical_line",
    }
)


def point_symbol(value: Any, label: str) -> str:
    """Scatter marker shape."""
    if not isinstance(value, str) or value not in _POINT_SYMBOLS:
        raise ValueError(f"{label} must be one of {sorted(_POINT_SYMBOLS)}")
    return value


# Named dash patterns -> on/off (…) lengths in CSS px, the SVG/CSS convention.
_DASH_PRESETS = {
    "solid": None,
    "dashed": [6.0, 4.0],
    "dotted": [1.5, 3.0],
    "dashdot": [6.0, 3.0, 1.5, 3.0],
}


def dash(value: Any, label: str) -> Optional[list[float]]:
    """Line dash: None/"solid", a preset name ("dashed"/"dotted"/"dashdot"),
    or an explicit [on, off, …] px sequence (2–8 positive lengths)."""
    if value is None:
        return None
    if isinstance(value, str):
        if value not in _DASH_PRESETS:
            raise ValueError(f"{label} must be one of {sorted(_DASH_PRESETS)} or an [on, off] list")
        return _DASH_PRESETS[value]
    if isinstance(value, (int, float)) or not hasattr(value, "__iter__"):
        raise ValueError(f"{label} must be a preset name or an [on, off, …] sequence")
    lengths = [positive_scalar(v, f"{label}[{i}]") for i, v in enumerate(value)]
    if not 2 <= len(lengths) <= 8:
        raise ValueError(f"{label} sequence must have between 2 and 8 lengths")
    return lengths


def _split_top_level(text: str) -> list[str]:
    """Split on commas that sit outside parentheses (rgb()/var() stay intact)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts]


def _gradient_stop(item: str, label: str) -> tuple[Optional[float], str]:
    """One CSS color stop: `<color> [<percentage>]` -> (position 0..1 | None, color)."""
    tokens = item.rsplit(None, 1)
    if len(tokens) == 2 and tokens[1].endswith("%"):
        try:
            pos = float(tokens[1][:-1]) / 100.0
        except ValueError as e:
            raise ValueError(f"{label} has an invalid stop position {tokens[1]!r}") from e
        if not np.isfinite(pos):
            raise ValueError(f"{label} stop positions must be finite")
        return min(max(pos, 0.0), 1.0), tokens[0].strip()
    return None, item.strip()


def mark_fill(value: Any, label: str) -> Optional[dict[str, Any]]:
    """Mark fill: a CSS `linear-gradient(...)` string, or `{"gradient": <that
    string>, "space": "mark"|"plot"}`. Returns the normalized wire spec
    `{"space", "dir", "stops": [[t, color], ...]}` with 2–8 resolved stops;
    color strings stay unresolved for the client (`var()`/`currentColor` need
    the live DOM)."""
    if value is None:
        return None
    space = "mark"
    if isinstance(value, dict):
        unknown = sorted(set(value) - {"gradient", "space"})
        if unknown:
            raise ValueError(f"{label} has unknown key(s) {unknown}; expected gradient, space")
        space = value.get("space", "mark")
        if space not in _FILL_SPACES:
            raise ValueError(f"{label} space must be one of {sorted(_FILL_SPACES)}")
        value = value.get("gradient")
    if not isinstance(value, str):
        raise ValueError(
            f"{label} must be a 'linear-gradient(...)' string or a dict with a 'gradient' key"
        )
    text = value.strip()
    lowered = text.lower()
    if not lowered.startswith("linear-gradient(") or not text.endswith(")"):
        raise ValueError(f"{label} must be a CSS 'linear-gradient(...)' value")
    args = _split_top_level(text[len("linear-gradient(") : -1])
    direction = "down"
    if args and args[0].lower() in _GRADIENT_DIRS:
        direction = _GRADIENT_DIRS[args[0].lower()]
        args = args[1:]
    elif args and (args[0].lower().startswith("to ") or args[0].lower().endswith("deg")):
        raise ValueError(
            f"{label} direction must be one of {sorted(_GRADIENT_DIRS)} (angles unsupported)"
        )
    if direction in {"left", "right"} and space == "mark":
        raise ValueError(
            f"{label}: 'to left'/'to right' need space='plot' — mark-space gradients run "
            "along each mark's value axis"
        )
    if not 2 <= len(args) <= 8:
        raise ValueError(f"{label} must have between 2 and 8 color stops")
    positions: list[Optional[float]] = []
    colors: list[str] = []
    for item in args:
        pos, color = _gradient_stop(item, label)
        if not color:
            raise ValueError(f"{label} has an empty color stop")
        positions.append(pos)
        colors.append(css_color(color, f"{label} stop {len(colors) + 1} color"))
    # CSS stop-position resolution: unpositioned endpoints default to 0%/100%,
    # positions never decrease (each anchor clamps to its predecessor), and
    # unpositioned interior stops spread evenly between their positioned
    # neighbors — implemented as anchor points + linear fill between them.
    count = len(positions)
    anchors: dict[int, float] = {i: p for i, p in enumerate(positions) if p is not None}
    anchors.setdefault(0, 0.0)
    anchors.setdefault(count - 1, 1.0)
    keys = sorted(anchors)
    prev = 0.0
    for i in keys:
        prev = anchors[i] = max(anchors[i], prev)
    resolved = [0.0] * count
    for i0, i1 in itertools.pairwise(keys):
        v0, v1 = anchors[i0], anchors[i1]
        for k in range(i0, i1):
            resolved[k] = v0 + (v1 - v0) * (k - i0) / (i1 - i0)
    resolved[count - 1] = anchors[count - 1]
    return {
        "space": space,
        "dir": direction,
        "stops": [[p, c] for p, c in zip(resolved, colors, strict=True)],
    }


def resolvable_paint(css: str, label: str, subject: str) -> tuple[float, float, float, float]:
    """Assert a validated CSS color has fixed channels, and return them.

    The gate for every paint XY must resolve *itself* rather than hand to the
    browser — colormap stops and palette entries. Both are indexed lookups
    consumed by renderers with no DOM (SVG, native raster, the density plane),
    so a `var()`/`oklch()`/`color-mix()` value cannot produce the same result
    there as on screen. Refusing it with the reason beats every alternative:
    a shared fallback collapses distinct entries onto one color, and a silent
    per-renderer difference is what §28 exists to prevent."""
    from . import kernels

    status, rgba = kernels.css_check(kernels.CSS_COLOR, css)
    if status != 1 or rgba is None:
        raise ValueError(
            f"{label} {css!r} cannot be resolved to fixed channels; {subject} must be "
            "hex, rgb()/rgba(), hsl()/hsla(), or a named color (var()/oklch()/color-mix() "
            "resolve only in a browser, and XY has to resolve this one itself for SVG, "
            "native PNG, and aggregated density surfaces)"
        )
    return rgba


def resolved_hex_paint(value: Any, label: str, subject: str) -> str:
    """A CSS color normalized to `#rrggbb` / `#rrggbbaa`.

    Resolving and then shipping the *original* string would be the worst of
    both: the value is checked here, but every consumer still has to resolve it
    again — and the browser client's only DOM-free path is `hexColor`, so a
    `tomato` or `rgb(...)` entry would fall through to a `getComputedStyle`
    probe. That probe returns "" on a root that is not yet in the document
    (notebook webviews attach asynchronously), which yields black, and nothing
    later rebuilds the cached LUT. Normalizing here means every renderer reads
    the same bytes off the wire with no cascade involved."""
    css = css_color(value, label)
    red, green, blue, alpha = resolvable_paint(css, label, subject)
    hex_rgb = "#{:02x}{:02x}{:02x}".format(*(int(round(c * 255)) for c in (red, green, blue)))
    return hex_rgb if alpha >= 1.0 else f"{hex_rgb}{int(round(alpha * 255)):02x}"


def _resolved_rgb(color: Any, label: str) -> tuple[int, int, int]:
    """One colormap stop as 8-bit sRGB.

    A colormap becomes a LUT in three renderers — the WebGL client, the SVG
    writer, and the native rasterizer — and only the first of those has a DOM.
    So a stop must parse to concrete channels *here* (hex, `rgb()`, `hsl()`,
    named colors: the closed grammars in src/css.rs). Browser-resolved forms
    (`var()`, `oklch()`, `color-mix()`) are legal everywhere XY takes a single
    paint color, but they cannot produce the same ramp in a headless export, so
    they are refused with the reason rather than silently baked to a fallback
    (§28).

    A colormap LUT is opaque RGB by construction — every builder writes alpha
    255, and a mark's transparency comes from `opacity`/`fill-opacity`, which
    the density compositor accounts for separately. A translucent stop is
    therefore refused too: dropping its alpha would turn `["transparent",
    "#0000ff"]` into an opaque BLACK→blue ramp, which is exactly the silent
    misrender this function exists to prevent."""
    css = css_color(color, label)
    rgba = resolvable_paint(css, label, "colormap stops")
    if len(rgba) > 3 and float(rgba[3]) < 1.0:
        raise ValueError(
            f"{label} {css!r} is translucent; colormap stops are opaque RGB (a LUT carries "
            "no alpha). Set the mark's opacity/fill-opacity instead, or use the color the "
            "stop should blend to."
        )
    red, green, blue = (int(round(channel * 255)) for channel in rgba[:3])
    return red, green, blue


def _colormap_stop_item(item: Any, index: int, label: str) -> tuple[Optional[float], Any]:
    """One entry of a colormap sequence: a color, or a `(position, color)` pair."""
    if isinstance(item, str) or not hasattr(item, "__iter__"):
        return None, item
    pair = list(item)
    if len(pair) != 2:
        raise ValueError(
            f"{label}[{index}] must be a color or a (position, color) pair, got {item!r}"
        )
    position, color = pair
    if isinstance(position, bool) or not isinstance(
        position, (int, float, np.integer, np.floating)
    ):
        raise ValueError(f"{label}[{index}] position must be a number between 0 and 1")
    pos = float(position)
    if not np.isfinite(pos) or not 0.0 <= pos <= 1.0:
        raise ValueError(f"{label}[{index}] position must be between 0 and 1, got {position!r}")
    return pos, color


# Positioned ramps resample onto the client's LUT width, so the shipped stops
# reproduce the declared gradient exactly rather than approximately.
_LUT_TEXELS = 256


def _resample_stops(positions: list[float], rgb: list[tuple[int, int, int]]) -> list[list[int]]:
    """Positioned stops -> `_LUT_TEXELS` evenly spaced stops.

    The wire form for a colormap is always *evenly spaced* stops — the same
    shape the built-in tables use — so every renderer keeps one interpolation
    path. Sampling at the LUT's own texel count makes the round trip exact."""
    grid = np.linspace(0.0, 1.0, _LUT_TEXELS)
    pos = np.asarray(positions, dtype=np.float64)
    channels = np.asarray(rgb, dtype=np.float64)
    out = np.empty((_LUT_TEXELS, 3), dtype=np.int64)
    for c in range(3):
        out[:, c] = np.rint(np.interp(grid, pos, channels[:, c]))
    return [[int(v) for v in row] for row in out]


def colormap_stops(value: Any, label: str) -> list[list[int]]:
    """A custom colormap as evenly spaced 8-bit RGB stops.

    Accepts a `linear-gradient(...)` string or a sequence of 2–256 CSS colors,
    optionally as `(position, color)` pairs. Uniformly spaced input ships as
    given; positioned input resamples onto the LUT grid."""
    if isinstance(value, str):
        gradient = mark_fill(value, label)
        assert gradient is not None
        if gradient["dir"] != "down":
            # A mark fill runs along a direction in space; a colormap maps a
            # VALUE to a color and has no spatial axis, so a direction keyword
            # here would be accepted and ignored. Refuse it instead (§28).
            raise ValueError(
                f"{label} gradient has a direction keyword, but a colormap maps values to "
                "colors and has no direction; drop it, or reverse the stop order"
            )
        stops = gradient["stops"]
        positions = [float(p) for p, _ in stops]
        rgb = [_resolved_rgb(c, f"{label} stop {i + 1}") for i, (_, c) in enumerate(stops)]
    else:
        items = list(value)
        if not 2 <= len(items) <= 256:
            raise ValueError(f"{label} must have between 2 and 256 color stops, got {len(items)}")
        raw = [_colormap_stop_item(item, i, label) for i, item in enumerate(items)]
        rgb = [_resolved_rgb(c, f"{label}[{i}]") for i, (_, c) in enumerate(raw)]
        declared = [p for p, _ in raw]
        if all(p is None for p in declared):
            return [list(c) for c in rgb]
        count = len(declared)
        anchors: dict[int, float] = {i: p for i, p in enumerate(declared) if p is not None}
        anchors.setdefault(0, 0.0)
        anchors.setdefault(count - 1, 1.0)
        keys = sorted(anchors)
        previous = 0.0
        for i in keys:
            previous = anchors[i] = max(anchors[i], previous)
        positions = [0.0] * count
        for i0, i1 in itertools.pairwise(keys):
            v0, v1 = anchors[i0], anchors[i1]
            for k in range(i0, i1):
                positions[k] = v0 + (v1 - v0) * (k - i0) / (i1 - i0)
        positions[count - 1] = anchors[count - 1]
    uniform = np.linspace(positions[0], positions[-1], len(positions))
    if positions[0] == 0.0 and positions[-1] == 1.0 and np.allclose(positions, uniform):
        return [list(c) for c in rgb]
    return _resample_stops(positions, rgb)


def axis_label_position(value: Any, label: str) -> Optional[str | dict[str, str | int | float]]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.replace("-", "_")
        if normalized not in _LABEL_POSITIONS:
            raise ValueError(
                f"{label} must be one of {sorted(_LABEL_POSITIONS)} or a CSS style dict"
            )
        return normalized
    return style_mapping(value, label)
