from __future__ import annotations

import inspect
import os
import subprocess
import sys
import textwrap
import typing

import xy.pyplot as plt
from xy.pyplot.typing import (
    AxesProtocol,
    AxesResult,
    CompatAxes,
    CompatAxesProtocol,
    CompatFigure,
    CompatFigureProtocol,
    FigureProtocol,
    FigureResult,
    NativeAxes,
    NativeFigure,
)


def test_typing_surface_does_not_import_optional_matplotlib() -> None:
    environment = os.environ.copy()
    environment.pop("XY_PYPLOT_MODE", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys
                from xy.pyplot.typing import AxesResult, FigureResult

                assert AxesResult is not None
                assert FigureResult is not None
                assert not any(
                    name == "matplotlib" or name.startswith("matplotlib.")
                    for name in sys.modules
                )
                """
            ),
        ],
        capture_output=True,
        env=environment,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_native_results_satisfy_common_and_mode_specific_types() -> None:
    plt.close("all")
    plt.set_mode("native")
    fig, ax = plt.subplots()

    assert isinstance(fig, FigureProtocol)
    assert isinstance(ax, AxesProtocol)
    assert isinstance(fig, NativeFigure)
    assert isinstance(ax, NativeAxes)
    assert not isinstance(fig, CompatFigureProtocol)
    plt.close("all")


def test_matplotlib_results_satisfy_structural_compat_types() -> None:
    matplotlib_figure = __import__("matplotlib.figure", fromlist=["Figure"])
    fig = matplotlib_figure.Figure()
    ax = fig.subplots()

    assert isinstance(fig, FigureProtocol)
    assert isinstance(ax, AxesProtocol)
    assert isinstance(fig, CompatFigureProtocol)
    assert isinstance(ax, CompatAxesProtocol)
    assert isinstance(fig, CompatFigure)
    assert isinstance(ax, CompatAxes)


def test_result_aliases_name_both_possible_implementations() -> None:
    assert set(typing.get_args(FigureResult)) == {NativeFigure, CompatFigure}
    assert set(typing.get_args(AxesResult)) == {NativeAxes, CompatAxes}


def test_mode_routed_factory_annotations_are_honest_unions() -> None:
    assert typing.get_type_hints(plt.figure)["return"] == FigureResult
    assert typing.get_type_hints(plt.gcf)["return"] == FigureResult
    assert typing.get_type_hints(plt.gca)["return"] == AxesResult

    native_subplots = inspect.unwrap(plt.subplots)
    assert typing.get_type_hints(native_subplots)["return"] == tuple[FigureResult, typing.Any]
    overloads = typing.get_overloads(native_subplots)
    assert typing.get_type_hints(overloads[0])["return"] == tuple[FigureResult, AxesResult]
