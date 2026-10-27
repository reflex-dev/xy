"""The mount-free native cascade: classes and author CSS resolved without a
browser, through the optional `xy-cascade` extension.

The extension (cascade/, its own cdylib) parses stylesheets with Lightning
CSS and cascades the published profile over the synthetic chart DOM below;
this module is the lazy ctypes boundary plus the snapshot construction. It
is imported only when a native-cascade export is requested — the core
import-weight contract does not pay for it — and a missing extension
raises with the build instruction rather than degrading silently.

Everything the resolver cannot honor arrives in an `unsupported` list with
the reason (out-of-profile selector, at-rule, percentage length, …) and is
surfaced through the compatibility machinery: warn mode says it, strict
mode refuses on it. Nothing outside the profile resolves to a guess (§28).
"""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
from typing import Any, Optional

from ..dom import CHART_DOM_SLOTS
from .resolved import ResolvedStyleSnapshot, SnapshotBuilder, SnapshotEnvironment, assert_resolved

#: The synthetic slot tree the cascade matches against — (slot, parent),
#: parents before children. Provenance: the parent of every slot a rendered
#: scatter+colorbar+annotation chart mounts was probed from a live headless
#: Chromium DOM (el.parentElement.closest('[data-xy-slot]')); the slots that
#: fixture does not render (legend family, tooltip/badge parts, colorbar
#: extension/line/minor, crosshairs) follow their client mount sites
#: (js/src/50_chartview.ts, 52_tooltip.ts, 53_interaction.ts). A slot whose
#: client nesting changes must change here — the differential smoke compares
#: cascade output against live-browser capture and catches a drifted parent
#: through any descendant selector that crosses it.
SYNTHETIC_TREE: tuple[tuple[str, Optional[str]], ...] = (
    ("root", None),
    ("title", "root"),
    ("chrome", "root"),
    ("canvas", "root"),
    ("annotation_layer", "root"),
    ("labels", "root"),
    ("axis_band", "root"),
    ("axis_line", "labels"),
    ("tick_mark", "labels"),
    ("tick_label", "labels"),
    ("axis_title", "labels"),
    ("annotation_label", "labels"),
    ("legend", "root"),
    ("legend_title", "legend"),
    ("legend_item", "legend"),
    ("legend_swatch", "legend_item"),
    ("legend_label", "legend_item"),
    ("colorbar", "root"),
    ("colorbar_bar", "colorbar"),
    ("colorbar_extension", "colorbar"),
    ("colorbar_line", "colorbar"),
    ("colorbar_tick", "colorbar"),
    ("colorbar_minor_tick", "colorbar"),
    ("colorbar_title", "colorbar"),
    ("tooltip", "root"),
    ("tooltip_title", "tooltip"),
    ("tooltip_row", "tooltip"),
    ("tooltip_label", "tooltip_row"),
    ("tooltip_value", "tooltip_row"),
    ("modebar", "root"),
    ("modebar_drag_handle", "modebar"),
    ("modebar_control_group", "modebar"),
    ("modebar_separator", "modebar"),
    ("modebar_button", "modebar"),
    ("modebar_icon", "modebar_button"),
    ("modebar_zoom_value", "modebar_button"),
    ("modebar_indicator", "modebar_button"),
    ("modebar_selection_icon", "modebar_button"),
    ("modebar_menu", "modebar"),
    ("modebar_menu_separator", "modebar_menu"),
    ("modebar_menu_icon", "modebar_button"),
    ("modebar_menu_label", "modebar_button"),
    ("modebar_history_controls", "modebar_menu"),
    ("selection", "root"),
    ("crosshair_x", "root"),
    ("crosshair_y", "root"),
    ("badge", "root"),
    ("badge_item", "badge"),
)

_LIB_ENV = "XY_CASCADE_LIB"


def _lib_filename() -> str:
    import sys

    if sys.platform == "darwin":
        return "libxy_cascade.dylib"
    if sys.platform == "win32":
        return "xy_cascade.dll"
    return "libxy_cascade.so"


def _find_library() -> Path:
    override = os.environ.get(_LIB_ENV)
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(f"{_LIB_ENV}={override} does not exist")
    name = _lib_filename()
    candidates = [
        Path(__file__).parents[1] / "_native_lib" / name,  # packaged beside the core lib
        Path(__file__).parents[3] / "target" / "release" / name,  # source checkout
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "the xy-cascade extension is not built. From a source checkout run "
        "`cargo build --release -p xy-cascade` (or set "
        f"{_LIB_ENV}=/path/to/{name}); published wheels ship it prebuilt."
    )


_CASCADE_ABI = 1
_lib: Optional[ctypes.CDLL] = None


def _load() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib
    lib = ctypes.CDLL(str(_find_library()))
    lib.xy_cascade_abi_version.restype = ctypes.c_uint32
    got = int(lib.xy_cascade_abi_version())
    if got != _CASCADE_ABI:
        raise RuntimeError(
            f"xy-cascade ABI {got} does not match this xy build (wants {_CASCADE_ABI}); "
            "rebuild the extension from the same checkout"
        )
    lib.xy_cascade_resolve.restype = ctypes.c_int32
    lib.xy_cascade_resolve.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8)),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.xy_cascade_free.restype = None
    lib.xy_cascade_free.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
    _lib = lib
    return lib


def _call(css: str, document: dict[str, Any]) -> dict[str, Any]:
    lib = _load()
    css_bytes = css.encode("utf-8")
    doc_bytes = json.dumps(document, separators=(",", ":")).encode("utf-8")
    out = ctypes.POINTER(ctypes.c_uint8)()
    out_len = ctypes.c_size_t()
    code = lib.xy_cascade_resolve(
        css_bytes,
        len(css_bytes),
        doc_bytes,
        len(doc_bytes),
        ctypes.byref(out),
        ctypes.byref(out_len),
    )
    try:
        payload = bytes(bytearray(out[i] for i in range(out_len.value)))
    finally:
        lib.xy_cascade_free(out, out_len)
    reply = json.loads(payload.decode("utf-8"))
    if code != 0:
        detail = reply.get("error") or repr(payload[:200])
        raise ValueError(f"native cascade failed: {detail}")
    return reply


def _expand_shorthands(declarations: dict[str, Any]) -> dict[str, Any]:
    """Split the box shorthands the schema carries as longhands.

    The cascade hands back `padding` as authored; schema v1 speaks
    `padding-top/right/bottom/left` so every consumer sees one spelling.
    Longhands present alongside the shorthand win (they cascaded later or
    more specifically — the resolver already decided that per property).
    """
    out: dict[str, Any] = {}
    for prop, value in declarations.items():
        if prop == "background-color":
            # Schema v1 speaks `background` (the browser capture makes the
            # same mapping); when both spellings cascade, the shorthand
            # already reset the longhand upstream, so last-in wins here too.
            out["background"] = value
            continue
        if prop == "padding" and isinstance(value, str):
            parts = value.split()
            if 1 <= len(parts) <= 4:
                top = parts[0]
                right = parts[1] if len(parts) > 1 else top
                bottom = parts[2] if len(parts) > 2 else top
                left = parts[3] if len(parts) > 3 else right
                for name, side in (
                    ("padding-top", top),
                    ("padding-right", right),
                    ("padding-bottom", bottom),
                    ("padding-left", left),
                ):
                    out.setdefault(name, side)
                continue
        out[prop] = value
    return out


def resolve_for_figure(
    figure: Any,
    *,
    custom_css: str = "",
    stylesheets: tuple[str, ...] = (),
    tailwind_profile: Optional[str] = None,
    color_scheme: str = "light",
    root_font_size: float = 16.0,
    width: Optional[float] = None,
    height: Optional[float] = None,
) -> tuple[ResolvedStyleSnapshot, tuple[str, ...]]:
    """Resolve the figure's classes against the supplied stylesheets.

    Returns the snapshot plus the `unsupported` report — every construct the
    profile could not honor, with its reason. Stylesheet order is cascade
    order: earlier sheets are wider (the Tailwind-core manifest, a project
    bundle), `custom_css` is the narrowest author sheet and comes last.
    """
    class_names = {str(k): str(v) for k, v in (figure.class_names or {}).items()}
    root_class = ""
    dom_class = getattr(figure, "class_name", None)
    if isinstance(dom_class, str):
        root_class = dom_class
    nodes = []
    index: dict[str, int] = {}
    for slot, parent in SYNTHETIC_TREE:
        classes = [c for c in class_names.get(slot, "").split() if c]
        if slot == "root" and root_class:
            classes = [c for c in root_class.split() if c] + classes
        index[slot] = len(nodes)
        nodes.append(
            {
                "slot": slot,
                "classes": classes,
                "parent": index[parent] if parent is not None else None,
            }
        )
    sheets = list(stylesheets)
    if tailwind_profile is not None:
        if tailwind_profile != "core-v1":
            raise ValueError(
                f"unknown tailwind_profile {tailwind_profile!r}; this build ships "
                '"core-v1" (a project\'s full Tailwind build rides stylesheets=)'
            )
        from ._tailwind_core import TAILWIND_CORE_CSS

        # The manifest is the widest sheet: project stylesheets and
        # custom_css cascade over it in that order.
        sheets.insert(0, TAILWIND_CORE_CSS)
    css = "\n".join((*sheets, custom_css)) if (sheets or custom_css) else ""
    reply = _call(
        css,
        {
            "env": {"color_scheme": color_scheme, "root_font_size": float(root_font_size)},
            "nodes": nodes,
        },
    )
    unsupported = [str(u) for u in reply.get("unsupported", ())]
    builder = SnapshotBuilder()
    for node in reply.get("nodes", ()):
        slot = node.get("slot")
        declarations = node.get("declarations") or {}
        if slot not in CHART_DOM_SLOTS or not declarations:
            continue
        legal: dict[str, Any] = {}
        for prop, value in _expand_shorthands(declarations).items():
            try:
                assert_resolved(prop, value)
            except ValueError as exc:
                unsupported.append(f"{slot}: {exc}")
            else:
                legal[prop] = value
        if legal:
            builder.add(slot, legal)

    def _dim(override: Optional[float], declared: Any, fallback: float) -> float:
        for candidate in (override, declared):
            numeric = isinstance(candidate, (int, float)) and not isinstance(candidate, bool)
            if numeric and float(candidate) > 0:
                return float(candidate)
        return fallback  # fluid ("100%") sizes fall back, as exports do

    environment = SnapshotEnvironment(
        width=_dim(width, getattr(figure, "width", None), 800.0),
        height=_dim(height, getattr(figure, "height", None), 500.0),
        color_scheme=color_scheme,
    )
    snapshot = builder.build(environment)
    return snapshot, tuple(unsupported)


__all__ = ["SYNTHETIC_TREE", "resolve_for_figure"]
