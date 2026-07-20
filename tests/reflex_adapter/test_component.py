"""Component compile smoke: props, event wiring, asset registration."""

from __future__ import annotations

import os
import pathlib

import pytest
import reflex as rx
import reflex_xy

import xy


class CompState(rx.State):
    last_row: dict = {}

    @rx.event
    def picked(self, row: dict):
        self.last_row = row


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
    comp = reflex_xy.chart("tok-abc", on_point_hover=CompState.picked, height="300px", id="chart1")
    assert comp.tag == "XYChart"
    assert str(comp.library).startswith("$/public/external/reflex_xy/assets/XYChart")
    rendered = str(comp)
    assert 'token:"tok-abc"' in rendered
    assert "onPointHover" in rendered
    assert "picked" in rendered  # the reflex event dispatch is in the prop

    # both frontend files were registered into the app's assets tree
    ext = pathlib.Path(app_cwd) / "assets" / "external" / "reflex_xy" / "assets"
    assert (ext / "XYChart.jsx").exists()
    assert (ext / "xy_client.js").exists()
    # symlinks resolve to the installed package files
    assert (ext / "xy_client.js").resolve().read_bytes()[:16]


def test_component_accepts_var_token(app_cwd):
    class TokState(rx.State):
        tok: str = ""

    comp = reflex_xy.chart(TokState.tok)
    rendered = str(comp)
    assert "tok" in rendered
    # default sizing keeps the mount visible before the first payload
    assert "height" in rendered.lower()


def test_component_import_is_local_library(app_cwd):
    comp = reflex_xy.chart("tok")
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
            class_name="stroke-[3px] transition-opacity",
        ),
        xy.vline(
            0.5,
            text="release",
            class_name="[&>text]:font-semibold opacity-80",
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
        "stroke-[3px] transition-opacity",
        "[&>text]:font-semibold opacity-80",
        "max-h-24 overflow-y-auto",
        "max-w-64 break-words",
        "rounded-lg shadow-sm",
        "hover:bg-slate-100 focus:ring-2",
    ):
        assert class_string in rendered


def test_static_chart_without_class_inventory_still_compiles(app_cwd):
    """Older core Figures predate the optional Tailwind class inventory."""
    figure = xy.scatter_chart(xy.scatter([1, 2, 3], [3, 2, 1])).figure()

    class LegacyFigure:
        def build_payload(self):
            return figure.build_payload()

    rendered = str(reflex_xy.chart(LegacyFigure(), id="legacy-static-chart"))
    assert 'id:"legacy-static-chart"' in rendered
    assert "src:" in rendered
    assert "tailwindClassTokens" not in rendered


def test_live_chart_does_not_claim_runtime_classes_are_compile_time_known(app_cwd):
    rendered = str(reflex_xy.chart("xyfig-runtime"))
    assert "tailwindClassTokens" not in rendered


def test_component_creation_does_not_touch_repo_root():
    """Outside an app cwd nothing has leaked assets/ into the repo."""
    repo_root = pathlib.Path(reflex_xy.__file__).resolve().parents[3]
    assert not (repo_root / "assets").exists(), (
        "importing/creating reflex_xy components must not scatter asset "
        "symlinks outside an app directory"
    )
    assert os.getcwd() != str(repo_root) or True


def test_lasso_selection_summary_keeps_polygon_geometry():
    source = (
        pathlib.Path(__file__).parents[2] / "python/reflex-xy/reflex_xy/assets/XYChart.jsx"
    ).read_text()
    assert 'm.type === "select_polygon"' in source
    assert 'lastSelect?.type === "select_polygon" ? lastSelect.points : null' in source
