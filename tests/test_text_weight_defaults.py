"""Chrome text weight defaults must match Matplotlib, in every renderer.

Matplotlib 3.11's `axes.titleweight`, `axes.labelweight` and `font.weight` all
default to `normal`, and its legend titles and colorbar labels are normal too.
So every xy chrome text default is 400, and the three renderers — the browser
render client (`js/src/`), the SVG exporter (`python/xy/_svg.py`) and the native
raster exporter (`python/xy/_raster.py`) — must agree on it. A renderer that
quietly drifts heavier is the bug these tests exist to catch.

The TypeScript source guard is a source-level assertion on purpose: the render
client's bundles are a generated, git-ignored artifact, so a test that can only
read the bundle cannot run from a fresh checkout.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

import xy
from xy import _raster

_ROOT = Path(__file__).resolve().parents[1]
_JS = _ROOT / "js" / "src"

# Native text-record header sizes, from `_Cmd.text` in python/xy/_raster.py.
# Both records end with `u32 byte_length` + UTF-8 payload, so a unique payload
# is an unambiguous anchor to walk back from.
#   _TEXT_OP     : op(1) x(4) y(4) anchor(1) size(4) rgba(4) len(4)      = 22
#   _STYLED_TEXT : op(1) x(4) y(4) anchor(1) size(4) angle(4) flags(1)
#                  range_count(4) [range(8) * n] rgba(4) len(4)          = 31 + 8n
_TEXT_OP_HEADER = 22
_STYLED_HEADER = 31


def _title_axis_legend_figure(**axis_style):
    """A chart exercising title, both axis labels, legend title and annotation."""
    fig = xy.chart(
        xy.line(x=[0.0, 1.0, 2.0], y=[1.0, 2.0, 1.5], name="series-a"),
        xy.x_axis(label="XLABEL", style=axis_style or None),
        xy.y_axis(label="YLABEL", style=axis_style or None),
        title="TITLE",
    ).figure()
    fig.legend_options = {"title": "LEGENDTITLE"}
    fig.text(1.0, 2.0, "ANNOTATION")
    return fig


def _svg_text_weights(svg: str) -> dict[str, str]:
    """Map each `<text>` body to the `font-weight` the SVG exporter emitted."""
    weights: dict[str, str] = {}
    for attrs, body in re.findall(r"<text([^>]*)>(?:<tspan[^>]*>)?([^<]*)", svg):
        match = re.search(r'font-weight="([^"]+)"', attrs)
        weights[body.strip()] = match.group(1) if match else "unset"
    return weights


def _raster_stream(fig) -> bytes:
    """The native command stream `to_png` hands to the Rust rasterizer."""
    captured: dict[str, object] = {}
    original = _raster._Cmd.__init__

    def spy(self, *args, **kwargs):
        original(self, *args, **kwargs)
        captured.setdefault("cmd", self)

    _raster._Cmd.__init__ = spy
    try:
        fig.to_png(scale=1)
    finally:
        _raster._Cmd.__init__ = original
    return bytes(captured["cmd"].buf)  # type: ignore[union-attr]


def _raster_text_bold(stream: bytes, text: str) -> bool:
    """Whether the native record carrying `text` sets the bold emphasis flag."""
    payload = text.encode("utf-8")
    at = stream.find(struct.pack("<I", len(payload)) + payload)
    assert at >= 0, f"no native text record carries {text!r}"
    body = at + 4
    if body >= _STYLED_HEADER:
        max_ranges = (body - _STYLED_HEADER) // 8
        for range_count in range(max_ranges + 1):
            styled = body - _STYLED_HEADER - 8 * range_count
            if stream[styled] != _raster._STYLED_TEXT:
                continue
            count_at = body - 12 - 8 * range_count
            (declared_count,) = struct.unpack("<I", stream[count_at : count_at + 4])
            if declared_count == range_count:
                flags_at = body - 13 - 8 * range_count
                return bool(stream[flags_at] & _raster._TEXT_BOLD)
    plain = body - _TEXT_OP_HEADER
    assert plain >= 0 and stream[plain] == _raster._TEXT_OP, (
        f"record for {text!r} is neither a plain nor a styled text record"
    )
    return False  # the plain opcode carries no emphasis byte at all


# --- SVG exporter ----------------------------------------------------------


def test_svg_chrome_text_defaults_to_normal_weight() -> None:
    weights = _svg_text_weights(_title_axis_legend_figure().to_svg())

    assert weights["TITLE"] == "400"
    assert weights["XLABEL"] == "400"
    assert weights["YLABEL"] == "400"
    assert weights["LEGENDTITLE"] == "400"
    # The annotation and legend-entry paths emit no weight at all, so they
    # inherit the document's 400. Asserted so a later default cannot sneak in.
    assert weights["ANNOTATION"] == "unset"
    assert weights["series-a"] == "unset"


def test_svg_honors_an_explicit_heavier_axis_label_weight() -> None:
    fig = _title_axis_legend_figure(label_font_weight="bold")
    assert _svg_text_weights(fig.to_svg())["XLABEL"] == "bold"


def test_svg_honors_an_explicit_heavier_title_weight() -> None:
    fig = _title_axis_legend_figure()
    fig.chrome_styles["title"] = {"font-weight": "700"}
    assert _svg_text_weights(fig.to_svg())["TITLE"] == "700"


# --- native raster exporter ------------------------------------------------


@pytest.mark.parametrize("bold", [False, True])
def test_raster_text_bold_decodes_styled_math_ranges(bold: bool) -> None:
    cmd = _raster._Cmd(scale=1)
    text = "a+b+c+d+e+f+g+h+i"
    ranges = [(start, start + 1) for start in range(0, len(text), 2)]
    cmd.text(
        0,
        0,
        0,
        10,
        (0, 0, 0, 255),
        text,
        bold=bold,
        italic_ranges=ranges,
    )

    # Nine ranges also guard against replacing the old zero-range assumption
    # with another arbitrary small-count cap.
    assert len(ranges) == 9
    assert _raster_text_bold(bytes(cmd.buf), text) is bold


def test_native_raster_chrome_text_carries_no_bold_by_default() -> None:
    stream = _raster_stream(_title_axis_legend_figure())

    for label in ("TITLE", "XLABEL", "YLABEL", "LEGENDTITLE", "ANNOTATION"):
        assert not _raster_text_bold(stream, label), f"{label} is bold in the raster stream"


@pytest.mark.parametrize("weight", ["bold", "700", 800])
def test_native_raster_emits_bold_only_when_asked(weight) -> None:
    fig = _title_axis_legend_figure()
    fig.chrome_styles["title"] = {"font-weight": weight}
    stream = _raster_stream(fig)

    assert _raster_text_bold(stream, "TITLE")
    # Opting the title in must not drag the axis labels along with it.
    assert not _raster_text_bold(stream, "XLABEL")


def test_native_raster_and_svg_agree_on_the_axis_label_default() -> None:
    fig = _title_axis_legend_figure()
    svg_weight = _svg_text_weights(fig.to_svg())["XLABEL"]
    raster_bold = _raster_text_bold(_raster_stream(fig), "XLABEL")

    assert svg_weight == "400"
    assert raster_bold is False


# --- browser render client (source-level guard) -----------------------------

# Slot rules in js/src/20_theme.ts that carry chrome *text*. Each must declare
# 400, or declare nothing and inherit it.
_TEXT_SLOTS = (
    "title",
    "axis_title",
    "tick_label",
    "legend",
    "colorbar",
    "colorbar_title",
    "annotation_label",
)


def test_theme_css_chrome_text_slots_declare_normal_weight() -> None:
    css = (_JS / "20_theme.ts").read_text(encoding="utf-8")
    rules = dict(re.findall(r'data-xy-slot="(\w+)"\]\)\{([^}]*)\}', css))

    for slot in _TEXT_SLOTS:
        assert slot in rules, f"no `{slot}` slot rule in 20_theme.ts"
        weight = re.search(r"font-weight:\s*([^;}]+)", rules[slot])
        assert weight is None or weight.group(1).strip() in {"400", "normal"}, (
            f'slot "{slot}" declares font-weight:{weight.group(1).strip()}; '
            "Matplotlib renders every chrome text element at normal weight"
        )


def test_chartview_does_not_pin_default_text_weights_inline() -> None:
    """Default weights stay in the base layer so Tailwind utilities can win.

    Explicit axis or slot weights are still applied inline through their style
    mappings, but constructor defaults must not compete with author utilities.
    """
    source = (_JS / "50_chartview.ts").read_text(encoding="utf-8")

    inline = set(re.findall(r"font-weight:\s*(\d+|normal|bold)", source))
    assert not inline, (
        f"50_chartview.ts pins default chrome weights inline: {sorted(inline)}; "
        "normal/400 belongs in the zero-specificity base stylesheet"
    )

    assigned = set(re.findall(r"\.style\.fontWeight\s*=\s*\"(\d+|normal|bold)\"", source))
    assert not assigned, (
        f"50_chartview.ts assigns default chrome fontWeight inline: {sorted(assigned)}; "
        "author utilities must remain able to override the default"
    )
    assert '"font-weight": this._axisStyleValue(axis, "label_font_weight")' in source
