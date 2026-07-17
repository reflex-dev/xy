from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from typing import Optional

HEAVY_MODULES = {
    "anywidget",
    "numpy",
    "reflex",
    "reflex_base",
    "reflex_core",
    "traitlets",
    "xy.channels",
    "xy.channel",
    "xy.columns",
    "xy.components",
    "xy._figure",
    "xy.interaction",
    "xy.marks",
    "xy.kernels",
    "xy.lod",
    "xy._native",
    "xy.widget",
}


def _run_fresh(code: str, *, env: Optional[dict[str, str]] = None) -> str:
    subprocess_env = os.environ.copy()
    if env:
        subprocess_env.update(env)
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=True,
        capture_output=True,
        env=subprocess_env,
        text=True,
    )
    return proc.stdout


def test_package_import_is_lazy_and_light() -> None:
    out = _run_fresh(
        f"""
        import sys
        import time

        t0 = time.perf_counter()
        import xy
        elapsed_ms = (time.perf_counter() - t0) * 1000

        heavy = {sorted(HEAVY_MODULES)!r}
        eager = [
            name
            for name in sys.modules
            if name in heavy or name.startswith("xy.")
        ]
        assert eager == [], eager
        assert elapsed_ms < 200, elapsed_ms
        assert xy.__version__
        print(f"{{elapsed_ms:.3f}}")
        """
    )
    assert float(out.strip()) < 200


def test_public_metadata_and_dir_are_lazy() -> None:
    _run_fresh(
        f"""
        import sys

        import xy

        names = dir(xy)
        assert "__version__" in xy.__all__
        assert "Figure" not in names
        assert "Figure" not in xy.__all__
        assert "scatter_chart" in names
        assert xy.__version__

        heavy = {sorted(HEAVY_MODULES)!r}
        eager = [
            name
            for name in sys.modules
            if name in heavy or name.startswith("xy.")
        ]
        assert eager == [], eager
        """
    )


def test_export_helpers_do_not_load_widget_numpy_or_kernels() -> None:
    _run_fresh(
        f"""
        import sys

        from xy.export import _json_for_inline_script

        assert _json_for_inline_script({{"x": "</script>&"}}) == '{{"x":"\\\\u003c/script\\\\u003e\\\\u0026"}}'
        heavy = {sorted(HEAVY_MODULES)!r}
        eager = [
            name
            for name in sys.modules
            if name in heavy or (
                name.startswith("xy.")
                and name not in {{"xy.export"}}
            )
        ]
        assert eager == [], eager
        assert "xy.export" in sys.modules
        """,
    )


def test_star_import_matches_public_all() -> None:
    _run_fresh(
        """
        import xy

        ns = {}
        exec("from xy import *", ns)

        exported = sorted(name for name in ns if name in xy.__all__)
        extras = sorted(
            name for name in ns if not name.startswith("__") and name not in xy.__all__
        )
        assert exported == sorted(xy.__all__)
        assert extras == []
        assert "Figure" not in ns
        assert ns["scatter_chart"] is xy.scatter_chart
        """
    )


def test_lazy_public_exports_still_work() -> None:
    _run_fresh(
        f"""
        import sys

        import xy
        assert "numpy" not in sys.modules

        from xy import Column, scatter, scatter_chart

        assert Column is xy.Column
        assert callable(scatter)
        assert callable(scatter_chart)
        assert callable(xy.column)
        assert xy.column(x=["a"], y=[1]).kind == "column"
        assert "xy._figure" in sys.modules
        assert "numpy" in sys.modules

        heavy = {sorted(HEAVY_MODULES)!r}
        loaded = sorted(name for name in sys.modules if name in heavy)
        assert "xy._native" in loaded
        """
    )


def test_figure_is_not_public_and_denial_stays_light() -> None:
    """`Figure` is internal now: the public attribute must raise, and the
    failed lookup must not drag in the compute stack as a side effect."""
    _run_fresh(
        """
        import sys

        import xy
        assert "numpy" not in sys.modules

        try:
            xy.Figure
        except AttributeError:
            pass
        else:
            raise AssertionError("xy.Figure must not be public")

        assert "Figure" not in xy.__all__
        assert "numpy" not in sys.modules
        assert "xy._figure" not in sys.modules
        assert "xy.kernels" not in sys.modules
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        """
    )


def test_composition_api_loads_compute_without_widget_stack() -> None:
    _run_fresh(
        """
        import sys

        import xy
        assert "numpy" not in sys.modules

        scatter = xy.scatter

        assert callable(scatter)
        assert "xy.components" in sys.modules
        assert "xy._figure" in sys.modules
        assert "xy.kernels" in sys.modules
        assert "numpy" in sys.modules
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        assert not any(
            name == "reflex" or name.startswith("reflex.") or name.startswith("reflex_")
            for name in sys.modules
        )
        """
    )


def test_dom_slot_contract_loads_without_compute_or_widget_stack() -> None:
    _run_fresh(
        """
        import sys

        import xy

        slots = xy.CHART_DOM_SLOTS

        assert slots[0] == "root"
        assert "tooltip" in slots
        assert "xy.dom" in sys.modules
        assert "xy.components" not in sys.modules
        assert "xy._figure" not in sys.modules
        assert "xy.kernels" not in sys.modules
        assert "xy.widget" not in sys.modules
        assert "numpy" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        """
    )


def test_html_export_does_not_load_widget_stack() -> None:
    _run_fresh(
        """
        import sys

        import xy

        chart = xy.line_chart(xy.line(x=[0, 1], y=[1, 2]), title="lazy boundary")
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules

        html = chart.to_html()

        assert "lazy boundary" in html
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        """
    )


def test_declarative_html_exports_do_not_load_widget_stack() -> None:
    _run_fresh(
        """
        import sys

        import xy

        chart = xy.chart(
            xy.scatter(x=[0, 1, 2], y=[1, 3, 2], name="points"),
            xy.line(x=[0, 1, 2], y=[1, 2, 2.5], name="trend"),
            xy.x_axis(label="x"),
            xy.y_axis(label="y"),
            xy.legend(),
            xy.tooltip(fields=["x", "y"]),
            title="declarative lazy boundary",
        )
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        assert not any(
            name == "reflex" or name.startswith("reflex.") or name.startswith("reflex_")
            for name in sys.modules
        )

        html = chart.to_html()
        alias = chart.html()
        repr_html = chart._repr_html_()

        assert "declarative lazy boundary" in html
        assert "declarative lazy boundary" in alias
        assert "declarative lazy boundary" in repr_html
        assert html.startswith("<!doctype html>")
        assert alias.startswith("<!doctype html>")
        assert repr_html.startswith('<iframe class="xy-notebook-frame"')
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        assert not any(
            name == "reflex" or name.startswith("reflex.") or name.startswith("reflex_")
            for name in sys.modules
        )
        """
    )


def test_widget_method_is_the_widget_import_boundary() -> None:
    _run_fresh(
        """
        import sys

        import xy

        chart = xy.line_chart(xy.line(x=[0, 1], y=[1, 2]), title="widget boundary")
        chart.to_html()
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules

        widget = chart.widget()

        assert widget is chart.widget()
        assert "xy.widget" in sys.modules
        assert "anywidget" in sys.modules
        assert "traitlets" in sys.modules
        """
    )


def test_column_factory_does_not_shadow_columns_submodule() -> None:
    _run_fresh(
        """
        import importlib

        import xy

        columns = importlib.import_module("xy.columns")
        assert columns.Column is xy.Column
        assert xy.column(x=["a"], y=[1]).kind == "column"

        try:
            importlib.import_module("xy.column")
        except ModuleNotFoundError:
            pass
        else:
            raise AssertionError("xy.column must stay the public factory, not a submodule")
        """
    )


def test_channel_dispatcher_loads_without_widget_stack() -> None:
    """The Reflex-forward guarantee: a server transport can drive
    channel.handle_message with no anywidget/traitlets installed."""
    _run_fresh(
        """
        import sys

        from xy.channel import ChannelCallbacks, handle_message

        assert callable(handle_message)
        assert ChannelCallbacks() == ChannelCallbacks()
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        """
    )


def test_chart_headless_append_does_not_load_widget_stack() -> None:
    """chart.append on a never-shown chart must mutate the figure directly,
    not instantiate the anywidget stack as a side effect."""
    _run_fresh(
        """
        import sys

        import xy

        chart = xy.scatter_chart(xy.scatter(x=[0.0, 1.0], y=[0.0, 1.0]))
        chart.append(0, [2.0], [3.0])

        assert len(chart.figure().traces[0].x.values) == 3
        assert "xy.widget" not in sys.modules
        assert "anywidget" not in sys.modules
        assert "traitlets" not in sys.modules
        """
    )
