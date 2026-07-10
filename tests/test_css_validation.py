"""CSS value validation: the native grammar gates every styling surface.

One parser (src/css.rs, over `kernels.css_check`) serves the Python argument
validators, the color-vs-column disambiguation, and the native raster — so a
malformed color/length/declaration errors loudly at build time (§28: no
silent decisions) instead of rendering a silently-wrong mark, and the raster
can never drift from the API contract.
"""

from __future__ import annotations

import numpy as np
import pytest

import xy as fc
from xy import kernels
from xy._figure import Figure
from xy._raster import _parse_color

X = np.arange(8.0)
Y = X * 0.5


# -- the kernel grammar itself ------------------------------------------------


def test_css_check_parses_closed_grammars_statically() -> None:
    status, rgba = kernels.css_check(kernels.CSS_COLOR, "#3b82f6")
    assert status == 1
    assert rgba is not None
    assert rgba[0] == pytest.approx(0x3B / 255)
    assert rgba[3] == 1.0
    assert kernels.css_check(kernels.CSS_COLOR, "rgb(255 0 0 / 0.5)")[1][3] == pytest.approx(0.5)
    assert kernels.css_check(kernels.CSS_COLOR, "rebeccapurple")[0] == 1
    assert kernels.css_check(kernels.CSS_COLOR, "transparent")[1][3] == 0.0


def test_css_check_passes_browser_resolved_forms_through() -> None:
    for value in ("var(--accent)", "oklch(0.7 0.1 250)", "color-mix(in oklab, red, blue)"):
        status, rgba = kernels.css_check(kernels.CSS_COLOR, value)
        assert status == 2, value
        assert rgba is None
    # currentColor parses (it is always valid) but has no static channels.
    assert kernels.css_check(kernels.CSS_COLOR, "currentColor") == (1, None)


def test_css_check_rejects_prefix_hex_exactly() -> None:
    # The regression this grammar exists for: '#3b82zz' must never be
    # "valid hex" anywhere in the pipeline.
    for bad in ("#3b82zz", "#3b82f", "#12", "#1234567", "#"):
        status, rgba = kernels.css_check(kernels.CSS_COLOR, bad)
        assert status == -4, bad
        assert rgba is None


def test_css_check_declaration_registry() -> None:
    def ok(prop: str, value: str) -> int:
        return kernels.css_check(kernels.CSS_DECLARATION, value, prop)[0]

    assert ok("font-size", "18px") == 1
    assert ok("padding", "4px 8px") == 1
    assert ok("color", "#3b82f6") == 1
    assert ok("width", "calc(100% - 8px)") == 2
    assert ok("backdrop-filter", "blur(4px)") == 2  # unknown prop: safe passthrough
    assert ok("--chart-bg", "linear-gradient(red, blue)") == 2
    assert ok("font-size", "big") == -7
    assert ok("font-size", "12parsecs") == -8
    assert ok("color", "#3b82zz") == -4
    assert ok("opacity", "0.5; position: fixed") == -2
    assert ok("", "x") == -10


# -- figure builders error loudly, with rollback --------------------------------


def test_trace_color_typos_raise_naming_the_argument() -> None:
    with pytest.raises(ValueError, match="line color '#3b82zz' is not a valid hex color"):
        Figure().line(X, Y, color="#3b82zz")
    with pytest.raises(ValueError, match="area color 'bluu' is not a recognized CSS color name"):
        Figure().area(X, Y, color="bluu")
    with pytest.raises(ValueError, match="colors\\[1\\]"):
        Figure().bar(["a", "b"], [[1, 2], [3, 4]], colors=["#111111", "notacolor"])
    with pytest.raises(ValueError, match="scatter stroke"):
        Figure().scatter(X, Y, stroke="#12345")


def test_gradient_stop_colors_validate() -> None:
    with pytest.raises(ValueError, match="area fill stop 2 color 'bluu'"):
        Figure().area(X, Y, fill="linear-gradient(#3b82f6, bluu)")
    # Browser-resolved stops stay allowed.
    Figure().area(X, Y, fill="linear-gradient(currentColor, transparent)")
    Figure().area(X, Y, fill="linear-gradient(var(--a), var(--b))")


def test_annotation_and_mark_style_colors_validate() -> None:
    with pytest.raises(ValueError, match="x rule color"):
        Figure().line(X, Y).vline(2.0, color="#nothex")
    with pytest.raises(ValueError, match="mark_style selected\\['color'\\]"):
        Figure().line(X, Y).set_mark_style(selected={"color": "#f9731"})


def test_style_dict_declarations_validate() -> None:
    with pytest.raises(ValueError, match="chart style\\['border-radius'\\]"):
        fc.scatter_chart(fc.scatter(x=X, y=Y), style={"border-radius": "12px; position:fixed"})
    with pytest.raises(ValueError, match="has an invalid number"):
        fc.x_axis(style={"font_size": "big"})
    # The px convention and custom properties stay untouched.
    fc.scatter_chart(
        fc.scatter(x=X, y=Y),
        style={"font_size": 18, "letter_spacing": "0.02em", "--chart-bg": "#0b1020"},
    )


def test_failed_color_validation_rolls_back_the_figure() -> None:
    fig = Figure().line(X, Y)
    traces = len(fig.traces)
    columns = fig.store.checkpoint()
    with pytest.raises(ValueError):
        fig.scatter(X, Y, color="#3b82zz")  # raises after x/y ingest
    assert len(fig.traces) == traces
    assert fig.store.checkpoint() == columns


# -- color vs column disambiguation is the same grammar -------------------------


def test_color_string_disambiguation_is_exact_both_ways() -> None:
    df = {"x": X, "y": Y, "grp": np.array(list("ab") * 4)}
    # Any named color works as a constant now (the old heuristic knew ~20).
    fc.scatter_chart(fc.scatter(x=X, y=Y, color="rebeccapurple")).figure()
    # Column names still resolve.
    fc.scatter_chart(fc.scatter(x="x", y="y", color="grp", data=df)).figure()
    # A color-shaped typo reports the CSS reason, not a column error.
    with pytest.raises(ValueError, match="is not a valid hex color"):
        fc.scatter_chart(fc.scatter(x=X, y=Y, color="#3b82zz")).figure()
    # A word that is neither stays a column error.
    with pytest.raises(ValueError, match="column 'grpp' not found"):
        fc.scatter_chart(fc.scatter(x="x", y="y", color="grpp", data=df)).figure()


# -- weird strings never escape a declaration context ---------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "red;} body { display:none }",
        "url(</style><script>alert(1)</script>)",
        "#fff'; background:url(evil)",
        "rgb(1, 2",
        "linear-gradient(red, blue\x07)",
    ],
)
def test_hostile_strings_are_rejected_at_build(hostile: str) -> None:
    with pytest.raises(ValueError):
        Figure().line(X, Y, color=hostile)
    with pytest.raises(ValueError):
        fc.scatter_chart(fc.scatter(x=X, y=Y), style={"background": hostile})


# -- the raster shares the grammar ----------------------------------------------


def test_raster_parse_color_uses_the_native_grammar() -> None:
    assert _parse_color("#3b82f6") == (0x3B, 0x82, 0xF6, 255)
    assert _parse_color("steelblue") == (70, 130, 180, 255)  # beyond the old 10-name set
    assert _parse_color("hsl(0, 100%, 50%)") == (255, 0, 0, 255)
    assert _parse_color("none") == (0, 0, 0, 0)
    assert _parse_color("transparent")[3] == 0
    assert _parse_color("#ff0000", opacity=0.5) == (255, 0, 0, 128)
    # Unparseable input keeps the documented never-invisible mid-gray fallback.
    assert _parse_color("oklch(0.7 0.1 250)") == (100, 100, 100, 255)
