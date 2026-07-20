"""Built-in declarative theme presets and their pure resolver."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .config import DEFAULT_PALETTE

PALETTES: dict[str, tuple[str, ...]] = {
    "xy": tuple(DEFAULT_PALETTE),
    "okabe_ito": (
        "#0072b2",
        "#e69f00",
        "#009e73",
        "#d55e00",
        "#56b4e9",
        "#cc79a7",
        "#f0e442",
        "#000000",
    ),
    "vibrant": (
        "#6366f1",
        "#f59e0b",
        "#10b981",
        "#ef4444",
        "#06b6d4",
        "#8b5cf6",
        "#ec4899",
        "#84cc16",
        "#f97316",
        "#64748b",
    ),
    "muted": (
        "#5b7b9a",
        "#c9975b",
        "#7a9a6d",
        "#b0666a",
        "#7f9c9a",
        "#b3a35c",
        "#96809b",
        "#8f7c6e",
        "#a8a29e",
        "#78716c",
    ),
}
PALETTES["colorblind"] = PALETTES["okabe_ito"]

SCHEMES = ("light", "dark", "system")
CONTRASTS = ("normal", "high")


def _tokens(values: dict[str, str]) -> Mapping[str, str]:
    return MappingProxyType(values)


@dataclass(frozen=True)
class ThemePreset:
    """An immutable pair of light/dark token mappings and mark defaults."""

    name: str
    light: Mapping[str, str]
    dark: Mapping[str, str]
    palette: str
    accent: str


PRESETS: dict[str, ThemePreset] = {
    "xy": ThemePreset(
        "xy",
        _tokens(
            {
                "background": "#ffffff",
                "--chart-text": "#374151",
                "--chart-axis": "#6b7280",
                "--chart-grid": "#e5e7eb",
                "--chart-crosshair": "#9ca3af",
                "--chart-tooltip-bg": "#ffffff",
                "--chart-tooltip-text": "#111827",
            }
        ),
        _tokens(
            {
                "background": "#18181b",
                "--chart-text": "#e4e4e7",
                "--chart-axis": "#a1a1aa",
                "--chart-grid": "#ffffff1f",
                "--chart-crosshair": "#71717a",
                "--chart-tooltip-bg": "#27272a",
                "--chart-tooltip-text": "#fafafa",
            }
        ),
        "xy",
        "#6366f1",
    ),
    "minimal": ThemePreset(
        "minimal",
        _tokens(
            {
                "background": "#ffffff",
                "--chart-text": "#374151",
                "--chart-axis": "#9ca3af",
                "--chart-grid": "transparent",
                "--chart-crosshair": "#9ca3af",
                "--chart-tooltip-bg": "#ffffff",
                "--chart-tooltip-text": "#111827",
                "--chart-legend-bg": "transparent",
            }
        ),
        _tokens(
            {
                "background": "#18181b",
                "--chart-text": "#e4e4e7",
                "--chart-axis": "#71717a",
                "--chart-grid": "transparent",
                "--chart-crosshair": "#71717a",
                "--chart-tooltip-bg": "#27272a",
                "--chart-tooltip-text": "#fafafa",
                "--chart-legend-bg": "transparent",
            }
        ),
        "muted",
        "#6366f1",
    ),
    "dashboard": ThemePreset(
        "dashboard",
        _tokens(
            {
                "background": "#ffffff",
                "--chart-bg": "#f8fafc",
                "--chart-grid": "#e2e8f0",
                "--chart-text": "#334155",
                "--chart-axis": "#64748b",
                "--chart-tooltip-bg": "#0f172a",
                "--chart-tooltip-text": "#f8fafc",
            }
        ),
        _tokens(
            {
                "background": "#09090b",
                "--chart-bg": "#111318",
                "--chart-grid": "#ffffff14",
                "--chart-text": "#d4d4d8",
                "--chart-axis": "#a1a1aa",
                "--chart-tooltip-bg": "#18181b",
                "--chart-tooltip-text": "#fafafa",
            }
        ),
        "vibrant",
        "#8b5cf6",
    ),
    "publication": ThemePreset(
        "publication",
        _tokens(
            {
                "background": "#ffffff",
                "--chart-text": "#111827",
                "--chart-axis": "#111827",
                "--chart-grid": "#d1d5db",
                "--chart-crosshair": "#6b7280",
            }
        ),
        _tokens(
            {
                "background": "#111111",
                "--chart-text": "#f5f5f5",
                "--chart-axis": "#f5f5f5",
                "--chart-grid": "#4b5563",
                "--chart-crosshair": "#9ca3af",
            }
        ),
        "muted",
        "#1f2937",
    ),
    "high_contrast": ThemePreset(
        "high_contrast",
        _tokens(
            {
                "background": "#ffffff",
                "--chart-text": "#000000",
                "--chart-axis": "#000000",
                "--chart-grid": "#00000066",
                "--chart-crosshair": "#000000",
                "--chart-tooltip-bg": "#000000",
                "--chart-tooltip-text": "#ffffff",
            }
        ),
        _tokens(
            {
                "background": "#000000",
                "--chart-text": "#ffffff",
                "--chart-axis": "#ffffff",
                "--chart-grid": "#ffffff66",
                "--chart-crosshair": "#ffffff",
                "--chart-tooltip-bg": "#ffffff",
                "--chart-tooltip-text": "#000000",
            }
        ),
        "okabe_ito",
        "#0072b2",
    ),
}

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _normalize_accent(accent: str) -> str:
    if not isinstance(accent, str) or _HEX_COLOR.fullmatch(accent) is None:
        raise ValueError(
            f"accent must be a hex color (#rgb, #rrggbb, or #rrggbbaa), got {accent!r}"
        )
    value = accent.lower()
    if len(value) == 4:
        value = "#" + "".join(character * 2 for character in value[1:])
    return value[:7]


def accent_tokens(accent: str) -> dict[str, str]:
    """Expand an accent color into selection, zoom, focus, and active tokens."""
    opaque = _normalize_accent(accent)
    return {
        "--chart-selection": opaque,
        "--chart-selection-fill": f"{opaque}26",
        "--chart-zoom-selection": opaque,
        "--chart-zoom-selection-fill": f"{opaque}26",
        "--chart-focus": opaque,
        "--chart-modebar-active": opaque,
    }


@dataclass(frozen=True)
class ResolvedTheme:
    style: dict[str, str]
    dark_style: dict[str, str]
    palette: tuple[str, ...] | None
    color_scheme: str | None


def _known(value: str | None, name: str, choices: tuple[str, ...]) -> None:
    if value is not None and value not in choices:
        raise ValueError(f"unknown {name} {value!r}; expected one of {choices}")


def _high_contrast(dark: bool) -> dict[str, str]:
    foreground = "#ffffff" if dark else "#000000"
    return {
        "--chart-text": foreground,
        "--chart-axis": foreground,
        "--chart-grid": "#ffffff59" if dark else "#00000059",
    }


def resolve_theme(
    *,
    preset: str | None = None,
    color_scheme: str | None = None,
    palette: str | None = None,
    accent: str | None = None,
    contrast: str | None = None,
) -> ResolvedTheme:
    """Resolve high-level choices into concrete tokens and a mark palette."""
    _known(preset, "preset", tuple(sorted(PRESETS)))
    _known(color_scheme, "color_scheme", SCHEMES)
    _known(palette, "palette", tuple(sorted(PALETTES)))
    _known(contrast, "contrast", CONTRASTS)
    if accent is not None:
        _normalize_accent(accent)
    if all(value is None for value in (preset, color_scheme, palette, accent, contrast)):
        return ResolvedTheme({}, {}, None, None)

    chosen = PRESETS[preset or "xy"]
    scheme = color_scheme or "light"
    style = dict(chosen.dark if scheme == "dark" else chosen.light)
    dark_style = dict(chosen.dark) if scheme == "system" else {}
    accent_style = accent_tokens(accent or chosen.accent)
    style.update(accent_style)
    dark_style.update(accent_style)
    if contrast == "high":
        style.update(_high_contrast(scheme == "dark"))
        if dark_style:
            dark_style.update(_high_contrast(True))
    palette_name = palette or ("okabe_ito" if contrast == "high" else chosen.palette)
    return ResolvedTheme(style, dark_style, PALETTES[palette_name], color_scheme)


def theme_presets() -> tuple[str, ...]:
    """Return the available declarative theme preset names."""
    return tuple(sorted(PRESETS))


def theme_palettes() -> tuple[str, ...]:
    """Return the available declarative theme palette names."""
    return tuple(sorted(PALETTES))
