"""Component compile smoke: props, event wiring, asset registration."""

from __future__ import annotations

import pathlib

import pytest
import reflex as rx

import reflex_xy
import xy
from xy.channel import decode_frame


class CompState(rx.State):
    last_row: dict = {}

    @rx.event
    def picked(self, row: dict):
        self.last_row = row


TAILWIND_SCAN_EDGE_CLASSES = (
    'before:content-["hello_world"]',
    r"before:content-['hello\_world']",
    "before:content-['✓']",
)


@pytest.fixture
def app_cwd(tmp_path, monkeypatch):
    """rx.asset symlinks into Path.cwd()/assets — emulate an app directory."""
    monkeypatch.chdir(tmp_path)
    # component class is cached per process; asset symlinks are per-cwd, so
    # force a rebuild to exercise registration in this cwd.
    import reflex_xy.component as component_mod

    monkeypatch.setattr(component_mod, "_component_cls", None)
    return tmp_path


def test_component_compiles_with_events(app_cwd):
    comp = reflex_xy.chart(
        figure=reflex_xy.FigureHandle("tok-abc"),
        on_point_hover=CompState.picked,
        height="300px",
        id="chart1",
    )
    assert comp.tag == "XYChart"
    assert str(comp.library).startswith("$/public/external/reflex_xy/assets/XYChart")
    rendered = str(comp)
    # the handle's token reaches the *figure* prop, not just any prop
    assert 'figure:({ ["token"] : "tok-abc" })' in rendered
    assert "onPointHover" in rendered
    assert "picked" in rendered  # the reflex event dispatch is in the prop

    # both frontend files were registered into the app's assets tree
    ext = pathlib.Path(app_cwd) / "assets" / "external" / "reflex_xy" / "assets"
    assert (ext / "XYChart.jsx").exists()
    assert (ext / "xy_client.js").exists()
    # symlinks resolve to the installed package files
    assert (ext / "xy_client.js").resolve().read_bytes()[:16]


def test_component_accepts_figure_var(app_cwd):
    class FigState(rx.State):
        @reflex_xy.figure
        def fig(self):
            return None

    comp = reflex_xy.chart(figure=FigState.fig, height="300px")
    rendered = str(comp)
    assert "figure" in rendered
    assert "fig" in rendered
    # default sizing keeps the mount visible before the first payload
    assert "height" in rendered.lower()


def test_component_rejects_wrong_var_and_raw_string_at_compile(app_cwd):
    """The Phase-0 R1 contract, through the real component: the typed
    ``figure`` prop fails the compile for a non-handle var or a string."""

    class WrongVarState(rx.State):
        points: int = 5

    with pytest.raises(TypeError, match="figure"):
        reflex_xy.chart(figure=WrongVarState.points)
    with pytest.raises(TypeError, match="figure"):
        reflex_xy.chart(figure="xyv1|raw|token|string")


def test_positional_var_source_warns_and_routes_to_figure(app_cwd):
    class ShimState(rx.State):
        @reflex_xy.figure
        def fig(self):
            return None

    with pytest.warns(DeprecationWarning, match="figure="):
        comp = reflex_xy.chart(ShimState.fig)
    assert "figure" in str(comp)


def test_positional_token_string_warns_but_keeps_the_token_prop(app_cwd):
    with pytest.warns(DeprecationWarning, match="figure="):
        comp = reflex_xy.chart("tok-abc")
    assert 'token:"tok-abc"' in str(comp)


def test_kernel_events_on_static_source_fail_at_compile(app_cwd):
    static_chart = xy.line_chart(xy.line([0, 1], [1, 2]))
    with pytest.raises(ValueError, match=r"on_select_end.*static"):
        reflex_xy.chart(static_chart, on_select_end=CompState.picked)
    # client-side events stay valid on the static tier
    comp = reflex_xy.chart(static_chart, on_view_change=CompState.picked, on_hover=CompState.picked)
    assert "onViewChange" in str(comp)


def test_explicitly_disabled_kernel_events_pass_on_static_source(app_cwd):
    """``on_point_hover=None`` means "no handler" — a disabled handler must
    not fail the static-source compile (value check, not key presence)."""
    static_chart = xy.line_chart(xy.line([0, 1], [1, 2]))
    comp = reflex_xy.chart(static_chart, on_point_hover=None, on_select_end=None)
    assert "src" in str(comp)


def test_component_import_is_local_library(app_cwd):
    comp = reflex_xy.chart(figure=reflex_xy.FigureHandle("tok"))
    imports = comp._get_all_imports()
    lib = [k for k in imports if "XYChart" in k]
    assert lib, f"wrapper import missing from {list(imports)}"
    assert lib[0].startswith("$/public/external/"), "must never be an npm specifier"


def test_static_chart_classes_are_visible_to_tailwind_source_scan(app_cwd):
    """XYBF is opaque to Tailwind, so static chart classes need a JSX literal."""
    static_chart = xy.chart(
        xy.line(
            [0, 1],
            [1, 2],
            class_name="adapter-only-mark-metadata",
        ),
        xy.vline(
            0.5,
            text="release",
            class_name="[text-wrap:balance] opacity-80",
        ),
        xy.legend(class_name="max-h-24 overflow-y-auto"),
        xy.tooltip(class_name="max-w-64 break-words"),
        xy.modebar(
            class_name="rounded-lg shadow-sm",
            button_class_name="hover:bg-slate-100 focus:ring-2",
        ),
        class_name="rounded-xl border border-slate-200",
        class_names={
            "title": "text-base font-semibold text-slate-900",
            "selection": "fill-blue-500/10 stroke-blue-500",
        },
    )

    rendered = str(reflex_xy.chart(static_chart, id="tailwind-chart"))
    assert "tailwindClassTokens" in rendered
    for class_string in (
        "rounded-xl border border-slate-200",
        "text-base font-semibold text-slate-900",
        "fill-blue-500/10 stroke-blue-500",
        "[text-wrap:balance] opacity-80",
        "max-h-24 overflow-y-auto",
        "max-w-64 break-words",
        "rounded-lg shadow-sm",
        "hover:bg-slate-100 focus:ring-2",
    ):
        assert class_string in rendered
    assert "adapter-only-mark-metadata" not in rendered


def test_static_facet_chart_compiles_as_grid_of_panel_payloads(app_cwd):
    data = {
        "x": [0, 1, 2, 0, 1, 2],
        "y": [1, 2, 3, 3, 2, 1],
        "region": ["West", "West", "West", "East", "East", "East"],
    }
    facets = xy.facet_chart(
        xy.scatter(x="x", y="y", color="#6e56cf"),
        by="region",
        data=data,
        cols=2,
        share_x=True,
        share_y=True,
    )

    rendered = str(
        reflex_xy.chart(
            facets,
            id="regional-grid",
            tailwind_classes="rounded-lg dark:bg-slate-950",
        )
    )

    assert "regional-grid" in rendered
    assert "repeat(2, minmax(0, 1fr))" in rendered
    assert rendered.count("XYChart") == 2
    assert rendered.count("/xy/") == 2
    assert rendered.count("rounded-lg dark:bg-slate-950") == 2
    asset_files = list((pathlib.Path(app_cwd) / "assets" / "xy").glob("*.xyf"))
    assert len(asset_files) == 2
    # Facet identity is not in the JSX: each panel payload carries its facet
    # label as the figure title (facets.py builds panels that way), which the
    # render client draws as the panel heading.
    titles = {decode_frame(path.read_bytes()).message["title"] for path in asset_files}
    assert titles == {"West", "East"}


def test_live_chart_does_not_claim_runtime_classes_are_compile_time_known(app_cwd):
    rendered = str(reflex_xy.chart(figure=reflex_xy.FigureHandle("xyfig-runtime")))
    assert "tailwindClassTokens" not in rendered


def test_live_chart_accepts_explicit_tailwind_scan_inventory(app_cwd):
    """Token payloads are runtime-only; callers can expose complete utilities."""
    rendered = str(
        reflex_xy.chart(
            figure=reflex_xy.FigureHandle("xyfig-runtime"),
            tailwind_classes=[
                "rounded-[28px] border-fuchsia-500",
                "dark:bg-slate-950 hover:bg-fuchsia-100",
                "rounded-[28px]",
            ],
        )
    )

    assert "tailwindClassTokens" in rendered
    assert ("rounded-[28px] border-fuchsia-500 dark:bg-slate-950 hover:bg-fuchsia-100") in rendered


def test_tailwind_scan_inventory_is_verbatim_for_live_and_static_charts(app_cwd):
    """Tailwind scans source text, so JSON-escaped candidates are different classes."""
    manifest = " ".join(TAILWIND_SCAN_EDGE_CLASSES)
    live_rendered = str(
        reflex_xy.chart(
            figure=reflex_xy.FigureHandle("xyfig-runtime"),
            tailwind_classes=TAILWIND_SCAN_EDGE_CLASSES,
        )
    )
    static_rendered = str(
        reflex_xy.chart(
            xy.line_chart(
                xy.line([0, 1], [1, 2]),
                class_name=manifest,
            )
        )
    )

    scan_literal = f'("" // {manifest}\n)'
    for rendered in (live_rendered, static_rendered):
        assert scan_literal in rendered
        assert r"before:content-[\"hello_world\"]" not in rendered
        assert r"before:content-['hello\\_world']" not in rendered
        assert r"before:content-['\u2713']" not in rendered


def test_tailwind_scan_inventory_is_verbatim_for_every_facet_panel(app_cwd):
    facets = xy.facet_chart(
        xy.scatter(x="x", y="y"),
        by="region",
        data={
            "x": [0, 1],
            "y": [1, 2],
            "region": ["West", "East"],
        },
        cols=2,
    )

    rendered = str(
        reflex_xy.chart(
            facets,
            tailwind_classes=TAILWIND_SCAN_EDGE_CLASSES,
        )
    )

    manifest = " ".join(TAILWIND_SCAN_EDGE_CLASSES)
    assert rendered.count(f'("" // {manifest}\n)') == 2


def test_explicit_tailwind_inventory_merges_with_static_discovery(app_cwd):
    static_chart = xy.line_chart(
        xy.line([0, 1], [1, 2]),
        class_name="rounded-xl bg-white",
    )

    rendered = str(
        reflex_xy.chart(
            static_chart,
            tailwind_classes="motion-safe:transition-shadow hover:shadow-xl",
        )
    )

    assert "rounded-xl bg-white motion-safe:transition-shadow hover:shadow-xl" in rendered


@pytest.mark.parametrize(
    "value",
    [
        42,
        ["rounded-xl", 2],
        {"root": "rounded-xl"},
        {"rounded-xl", "bg-white"},
        frozenset({"rounded-xl", "bg-white"}),
    ],
)
def test_tailwind_inventory_requires_literal_strings(app_cwd, value):
    with pytest.raises(
        TypeError,
        match=r"tailwind_classes must be a string or ordered iterable of strings|"
        "tailwind_classes must contain only strings",
    ):
        reflex_xy.chart(figure=reflex_xy.FigureHandle("xyfig-runtime"), tailwind_classes=value)
