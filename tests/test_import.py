from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_fresh(code: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def test_package_import_is_lazy_and_light() -> None:
    out = _run_fresh(
        """
        import sys
        import time

        t0 = time.perf_counter()
        import fastcharts
        elapsed_ms = (time.perf_counter() - t0) * 1000

        eager = [
            name
            for name in (
                "numpy",
                "fastcharts.columns",
                "fastcharts.figure",
                "fastcharts.kernels",
                "fastcharts._native",
            )
            if name in sys.modules
        ]
        assert eager == [], eager
        assert elapsed_ms < 200, elapsed_ms
        assert fastcharts.__version__
        print(f"{elapsed_ms:.3f}")
        """
    )
    assert float(out.strip()) < 200


def test_lazy_public_exports_still_work() -> None:
    _run_fresh(
        """
        import sys

        import fastcharts
        assert "numpy" not in sys.modules

        from fastcharts import Column, Figure, scatter, scatter_chart

        assert Column is fastcharts.Column
        assert Figure is fastcharts.Figure
        assert callable(scatter)
        assert callable(scatter_chart)
        assert callable(fastcharts.column)
        assert fastcharts.column(x=["a"], y=[1]).kind == "column"
        assert "fastcharts.figure" in sys.modules
        assert "numpy" in sys.modules
        """
    )


def test_column_factory_does_not_shadow_columns_submodule() -> None:
    _run_fresh(
        """
        import importlib

        import fastcharts

        columns = importlib.import_module("fastcharts.columns")
        assert columns.Column is fastcharts.Column
        assert fastcharts.column(x=["a"], y=[1]).kind == "column"

        try:
            importlib.import_module("fastcharts.column")
        except ModuleNotFoundError:
            pass
        else:
            raise AssertionError("fastcharts.column must stay the public factory, not a submodule")
        """
    )
