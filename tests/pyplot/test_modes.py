from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import xy.pyplot as plt
from xy.pyplot import _mode, _state


def _run_fresh(
    code: str,
    *,
    mode: str | None = None,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if mode is None:
        environment.pop("XY_PYPLOT_MODE", None)
    else:
        environment["XY_PYPLOT_MODE"] = mode
    if extra_environment:
        environment.update(extra_environment)
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        env=environment,
        text=True,
    )


@pytest.fixture(autouse=True)
def _reset_mode() -> Any:
    _state.close("all")
    _mode._deactivate_compat_backend_hint()
    _mode._requested_mode = "native"
    _mode._auto_compat_unavailable = False
    _mode._compat_pyplot = None
    yield
    _state.close("all")
    matplotlib_pyplot = sys.modules.get("matplotlib.pyplot")
    if matplotlib_pyplot is not None:
        matplotlib_pyplot.close("all")
    _mode._deactivate_compat_backend_hint()
    _mode._requested_mode = "native"
    _mode._auto_compat_unavailable = False
    _mode._compat_pyplot = None


def test_default_auto_selection_stays_matplotlib_free_until_first_routed_call() -> None:
    default = _run_fresh(
        """
        import os
        import sys
        import xy.pyplot as plt

        assert plt.get_mode() == "auto"
        assert os.environ["MPLBACKEND"] == "module://xy.backends.backend_xy"
        assert not any(
            name == "matplotlib" or name.startswith("matplotlib.")
            for name in sys.modules
        )
        """
    )
    assert default.returncode == 0, default.stderr

    native = _run_fresh(
        """
        import sys
        import xy.pyplot as plt

        assert plt.get_mode() == "native"
        assert "Normalize" not in dir(plt)
        try:
            plt.Normalize
        except AttributeError:
            pass
        else:
            raise AssertionError("native mode must not expose Matplotlib-only names")
        assert not any(
            name == "matplotlib" or name.startswith("matplotlib.")
            for name in sys.modules
        )
        """,
        mode="native",
    )
    assert native.returncode == 0, native.stderr

    for configured in ("auto", "compat"):
        selected = _run_fresh(
            f"""
            import os
            import sys
            import xy.pyplot as plt

            assert plt.get_mode() == {configured!r}
            if {configured!r} == "compat":
                assert os.environ["MPLBACKEND"] == "module://xy.backends.backend_xy"
            assert not any(
                name == "matplotlib" or name.startswith("matplotlib.")
                for name in sys.modules
            )
            """,
            mode=configured,
        )
        assert selected.returncode == 0, selected.stderr


def test_invalid_environment_mode_fails_with_the_variable_name() -> None:
    result = _run_fresh("import xy.pyplot", mode="automatic")

    assert result.returncode != 0
    assert "XY_PYPLOT_MODE must be one of" in result.stderr


def test_set_mode_validates_values_without_importing_matplotlib(monkeypatch: Any) -> None:
    monkeypatch.setattr(_mode, "_validate_installed_matplotlib", lambda: "3.11.0")
    existing = {
        name for name in sys.modules if name == "matplotlib" or name.startswith("matplotlib.")
    }

    plt.set_mode("compat")

    assert plt.get_mode() == "compat"
    assert {
        name for name in sys.modules if name == "matplotlib" or name.startswith("matplotlib.")
    } == existing
    with pytest.raises(ValueError, match="mode must be one of"):
        plt.set_mode("automatic")


def test_auto_routes_compat_when_supported_matplotlib_is_installed() -> None:
    plt.set_mode("auto")
    fig, ax = plt.subplots()

    assert plt.get_mode() == "auto"
    assert isinstance(fig, plt.Figure)
    assert isinstance(ax, plt.Axes)
    assert type(fig).__module__.startswith("matplotlib.")
    assert type(fig.canvas).__module__ == "xy.backends.backend_xy"
    with pytest.raises(RuntimeError, match="figures are open"):
        plt.set_mode("native")


def test_auto_falls_back_to_native_without_supported_matplotlib(monkeypatch: Any) -> None:
    def missing(_name: str) -> str:
        raise _mode.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(_mode.importlib.metadata, "version", missing)

    plt.set_mode("auto")
    fig, ax = plt.subplots()

    assert plt.get_mode() == "auto"
    assert type(fig).__module__ == "xy.pyplot._mplfig"
    assert type(ax).__module__ == "xy.pyplot._axes"


def test_auto_falls_back_to_native_when_supported_matplotlib_cannot_import() -> None:
    result = _run_fresh(
        """
        import builtins
        import os

        real_import = builtins.__import__
        def blocked_import(name, *args, **kwargs):
            if name == "matplotlib" or name.startswith("matplotlib."):
                raise ImportError("matplotlib intentionally unavailable")
            return real_import(name, *args, **kwargs)
        builtins.__import__ = blocked_import

        import xy.pyplot as plt
        figure, axes = plt.subplots()

        assert plt.get_mode() == "auto"
        assert type(figure).__module__ == "xy.pyplot._mplfig"
        assert type(axes).__module__ == "xy.pyplot._axes"
        assert os.environ.get("MPLBACKEND") != "module://xy.backends.backend_xy"
        """,
    )

    assert result.returncode == 0, result.stderr


def test_switching_effective_mode_requires_empty_figure_registries(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(_mode, "_validate_installed_matplotlib", lambda: "3.11.0")
    plt.figure()

    with pytest.raises(RuntimeError, match=r'close\("all"\)'):
        plt.set_mode("compat")

    plt.close("all")
    plt.set_mode("compat")
    assert plt.get_mode() == "compat"
    plt.set_mode("native")


def test_compat_routes_functions_axes_helpers_and_mutable_namespaces(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def subplots(*args: Any, **kwargs: Any) -> tuple[str, str]:
        calls.append(("subplots", args, kwargs))
        return "mpl-figure", "mpl-axes"

    def relim(*args: Any, **kwargs: Any) -> str:
        calls.append(("relim", args, kwargs))
        return "relined"

    def matshow(*args: Any, **kwargs: Any) -> str:
        calls.append(("matshow", args, kwargs))
        return "mpl-image"

    compat_rc = {"figure.dpi": 144}
    fake_pyplot = SimpleNamespace(
        matshow=matshow,
        subplots=subplots,
        gca=lambda: SimpleNamespace(relim=relim),
        rcParams=compat_rc,
        style=SimpleNamespace(available=("default",)),
        cm=SimpleNamespace(viridis="mpl-viridis"),
    )
    fake_matplotlib = SimpleNamespace(colormaps=("viridis", "plasma"))
    monkeypatch.setitem(sys.modules, "matplotlib", fake_matplotlib)
    monkeypatch.setattr(_mode, "_compat_pyplot", fake_pyplot)
    monkeypatch.setattr(_mode, "_validate_installed_matplotlib", lambda: "3.11.0")

    plt.set_mode("compat")
    assert plt.subplots(2, 3, layout="tight") == ("mpl-figure", "mpl-axes")
    assert plt.relim() == "relined"
    assert plt.matshow([[1, 2], [3, 4]], fignum=7) == "mpl-image"
    assert plt.rcParams["figure.dpi"] == 144
    plt.rcParams["figure.dpi"] = 96
    assert compat_rc["figure.dpi"] == 96
    assert plt.style.available == ("default",)
    assert plt.cm.viridis == "mpl-viridis"
    assert tuple(plt.colormaps) == ("viridis", "plasma")
    assert calls == [
        ("subplots", (2, 3), {"layout": "tight"}),
        ("relim", (), {}),
        ("matshow", ([[1, 2], [3, 4]],), {"fignum": 7}),
    ]


@pytest.mark.parametrize("version", ["3.10.8", "3.12.0", "4.0.0"])
def test_compat_rejects_unsupported_matplotlib_series(monkeypatch: Any, version: str) -> None:
    monkeypatch.setattr(_mode.importlib.metadata, "version", lambda _name: version)

    with pytest.raises(RuntimeError, match=r"Matplotlib >=3\.11,<3\.12"):
        plt.set_mode("compat")


def test_compat_missing_extra_has_actionable_install_command(monkeypatch: Any) -> None:
    def missing(_name: str) -> str:
        raise _mode.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(_mode.importlib.metadata, "version", missing)

    with pytest.raises(RuntimeError, match=r'pip install "xy\[matplotlib\]"'):
        plt.set_mode("compat")


def test_real_compat_backend_routing_when_extra_is_installed(tmp_path: Path) -> None:
    try:
        version = metadata.version("matplotlib")
    except metadata.PackageNotFoundError:
        pytest.skip("xy[matplotlib] is not installed")
    if tuple(map(int, version.split(".")[:2])) != (3, 11):
        pytest.skip(f"compat test requires Matplotlib 3.11.x, found {version}")

    output = tmp_path / "compat.svg"
    result = _run_fresh(
        f"""
        import sys
        import xy.pyplot as plt

        assert "matplotlib" not in sys.modules
        plt.set_mode("compat")
        assert "matplotlib" not in sys.modules

        image = plt.matshow([[0, 1], [2, 3]], fignum=7)
        figure = image.figure
        assert figure.number == 7
        assert type(figure).__module__.startswith("matplotlib.")
        assert type(image.axes).__module__.startswith("matplotlib.")
        assert type(figure.canvas).__module__ == "xy.backends.backend_xy"
        assert isinstance(figure, plt.Figure)
        assert isinstance(image.axes, plt.Axes)

        from matplotlib.axes import Axes as MatplotlibAxes
        from matplotlib.colors import (
            LinearSegmentedColormap as MatplotlibLinearSegmentedColormap,
            ListedColormap as MatplotlibListedColormap,
            Normalize as MatplotlibNormalize,
        )
        from matplotlib.figure import Figure as MatplotlibFigure
        from matplotlib.gridspec import GridSpec as MatplotlibGridSpec
        from matplotlib.patches import Polygon as MatplotlibPolygon
        from matplotlib.ticker import (
            AutoMinorLocator as MatplotlibAutoMinorLocator,
            StrMethodFormatter as MatplotlibStrMethodFormatter,
        )

        direct_figure = plt.Figure(figsize=(2, 2))
        direct_axes = plt.Axes(direct_figure, [0.1, 0.1, 0.8, 0.8])
        direct_grid = plt.GridSpec(2, 3)
        assert type(direct_figure) is MatplotlibFigure
        assert type(direct_axes) is MatplotlibAxes
        assert type(direct_grid) is MatplotlibGridSpec
        assert isinstance(direct_figure, plt.Figure)
        assert isinstance(direct_axes, plt.Axes)
        assert isinstance(direct_grid, plt.GridSpec)

        class RoutedFigure(plt.Figure):
            pass

        assert issubclass(RoutedFigure, MatplotlibFigure)
        assert isinstance(RoutedFigure(), plt.Figure)

        minor = plt.AutoMinorLocator(4)
        formatter = plt.StrMethodFormatter("{{x:.1f}}")
        listed = plt.ListedColormap(["red", "blue"], name="pair")
        segmented = plt.LinearSegmentedColormap.from_list("gradient", ["red", "blue"])
        assert type(minor) is MatplotlibAutoMinorLocator
        assert type(formatter) is MatplotlibStrMethodFormatter
        assert type(listed) is MatplotlibListedColormap
        assert type(segmented) is MatplotlibLinearSegmentedColormap
        assert isinstance(minor, plt.AutoMinorLocator)
        assert isinstance(formatter, plt.StrMethodFormatter)
        assert isinstance(listed, plt.ListedColormap)
        assert isinstance(segmented, plt.LinearSegmentedColormap)

        from xy.pyplot import Normalize as RoutedNormalize
        from xy.pyplot import Polygon as RoutedPolygon
        from xy.pyplot import ion as routed_ion

        assert plt.Normalize is MatplotlibNormalize
        assert plt.Polygon is MatplotlibPolygon
        assert RoutedNormalize is MatplotlibNormalize
        assert RoutedPolygon is MatplotlibPolygon
        assert routed_ion is plt.ion
        assert routed_ion is not __import__("matplotlib.pyplot", fromlist=["ion"]).ion
        routed_ion()
        assert __import__("matplotlib.pyplot", fromlist=["isinteractive"]).isinteractive()
        assert {{"Normalize", "Polygon", "ion"}} <= set(dir(plt))

        plt.savefig({str(output)!r})
        assert "<svg" in open({str(output)!r}, encoding="utf-8").read(256)
        assert figure.canvas.fallback_used is False

        try:
            plt.set_mode("native")
        except RuntimeError as exc:
            assert "figures are open" in str(exc)
        else:
            raise AssertionError("mode switch with a live figure must fail")

        plt.close("all")
        plt.set_mode("native")
        assert plt.get_mode() == "native"
        """,
        extra_environment={"MPLCONFIGDIR": str(tmp_path / "mplconfig")},
    )
    assert result.returncode == 0, result.stderr


def test_compat_public_switch_backend_and_rcparams_cannot_escape_xy(tmp_path: Path) -> None:
    result = _run_fresh(
        """
        import matplotlib
        import xy.pyplot as plt

        plt.set_mode("compat")
        for mutate in (
            lambda: plt.switch_backend("Agg"),
            lambda: plt.rcParams.__setitem__("backend", "Agg"),
            lambda: plt.rcParams.update({"backend": "Agg"}),
        ):
            try:
                mutate()
            except RuntimeError as exc:
                assert "pins Matplotlib" in str(exc)
            else:
                raise AssertionError("compat backend escape unexpectedly succeeded")

        plt.switch_backend("module://xy.backends.backend_xy")
        plt.rcParams["backend"] = "module://xy.backends.backend_xy"
        figure = plt.figure()
        assert matplotlib.get_backend() == "module://xy.backends.backend_xy"
        assert type(figure.canvas).__module__ == "xy.backends.backend_xy"

        try:
            plt.switch_backend("Agg")
        except RuntimeError as exc:
            assert "bypass RendererXY" in str(exc)
        else:
            raise AssertionError("open figures must not weaken backend pinning")
        assert plt.get_fignums() == [1]
        assert type(figure.canvas).__module__ == "xy.backends.backend_xy"
        """,
        extra_environment={"MPLCONFIGDIR": str(tmp_path / "mplconfig")},
    )
    assert result.returncode == 0, result.stderr


def test_complete_pyplot_inventory_star_import_and_dynamic_calls_stay_on_xy(
    tmp_path: Path,
) -> None:
    result = _run_fresh(
        """
        import matplotlib
        import xy.pyplot as plt
        from xy.pyplot._compat_inventory import COMPAT_PYPLOT_PUBLIC_NAMES

        plt.set_mode("compat")
        expected = set(COMPAT_PYPLOT_PUBLIC_NAMES)
        assert len(expected) == 247
        assert expected <= set(plt.__all__)
        assert expected <= set(dir(plt))

        namespace = {}
        exec("from xy.pyplot import *", namespace)
        assert expected <= set(namespace)
        make_manager = namespace["new_figure_manager"]
        assert make_manager is plt.new_figure_manager
        assert make_manager is not __import__(
            "matplotlib.pyplot", fromlist=["new_figure_manager"]
        ).new_figure_manager

        __import__("matplotlib.pyplot", fromlist=["switch_backend"]).switch_backend("Agg")
        assert matplotlib.get_backend().lower() == "agg"
        manager = make_manager(17)
        assert type(manager.canvas).__module__ == "xy.backends.backend_xy"
        assert matplotlib.get_backend() == "module://xy.backends.backend_xy"
        assert manager.canvas.fallback_used is False
        """,
        extra_environment={"MPLCONFIGDIR": str(tmp_path / "mplconfig")},
    )

    assert result.returncode == 0, result.stderr


def test_native_star_import_remains_dependency_free_and_bounded() -> None:
    result = _run_fresh(
        """
        import sys
        import xy.pyplot as plt

        namespace = {}
        exec("from xy.pyplot import *", namespace)
        assert set(plt.__all__) <= set(namespace)
        assert "new_figure_manager" not in namespace
        assert "Button" not in namespace
        assert not any(
            name == "matplotlib" or name.startswith("matplotlib.")
            for name in sys.modules
        )
        """,
        mode="native",
    )

    assert result.returncode == 0, result.stderr


def test_cached_compat_pyplot_repairs_external_backend_and_rc_drift(tmp_path: Path) -> None:
    result = _run_fresh(
        """
        import xy.pyplot as plt

        plt.set_mode("compat")
        first = plt.figure(1)
        second_open = plt.figure(2)
        assert second_open is not first
        plt.figure(1)
        # Cache validation must inspect managers without changing the active
        # figure as a side effect.
        assert plt.gcf() is first
        assert type(first.canvas).__module__ == "xy.backends.backend_xy"
        plt.close("all")

        import matplotlib
        import matplotlib.pyplot as raw_pyplot
        from xy.pyplot import _mode

        cached = _mode._compat_pyplot
        raw_pyplot.switch_backend("Agg")
        assert matplotlib.get_backend().lower() == "agg"
        second = plt.figure()
        assert _mode._compat_pyplot is cached
        assert matplotlib.get_backend() == "module://xy.backends.backend_xy"
        assert type(second.canvas).__module__ == "xy.backends.backend_xy"
        plt.close("all")

        matplotlib.rcParams["backend"] = "Agg"
        assert matplotlib.get_backend().lower() == "agg"
        third = plt.figure()
        assert matplotlib.get_backend() == "module://xy.backends.backend_xy"
        assert type(third.canvas).__module__ == "xy.backends.backend_xy"
        """,
        extra_environment={"MPLCONFIGDIR": str(tmp_path / "mplconfig")},
    )
    assert result.returncode == 0, result.stderr


def test_cached_compat_backend_rejects_open_non_xy_figures(tmp_path: Path) -> None:
    result = _run_fresh(
        """
        import xy.pyplot as plt

        plt.set_mode("compat")
        xy_figure = plt.figure()
        import matplotlib.pyplot as raw_pyplot

        raw_pyplot.switch_backend("Agg")
        # Existing XY figures are safe: cache validation restores the backend
        # without replacing or closing their canvases.
        assert plt.gcf() is xy_figure
        assert type(xy_figure.canvas).__module__ == "xy.backends.backend_xy"

        raw_pyplot.switch_backend("Agg")
        agg_figure = raw_pyplot.figure(99)
        assert type(agg_figure.canvas).__module__ == "matplotlib.backends.backend_agg"
        try:
            plt.figure()
        except RuntimeError as exc:
            assert "open Matplotlib figures on non-XY canvases" in str(exc)
            assert 'close("all")' in str(exc)
        else:
            raise AssertionError("mixed live canvases must fail closed")

        raw_pyplot.close("all")
        repaired = plt.figure()
        assert type(repaired.canvas).__module__ == "xy.backends.backend_xy"
        """,
        extra_environment={"MPLCONFIGDIR": str(tmp_path / "mplconfig")},
    )
    assert result.returncode == 0, result.stderr


def test_compat_ipython_flush_uses_the_matplotlib_figure_registry(monkeypatch: Any) -> None:
    try:
        version = metadata.version("matplotlib")
    except metadata.PackageNotFoundError:
        pytest.skip("xy[matplotlib] is not installed")
    if tuple(map(int, version.split(".")[:2])) != (3, 11):
        pytest.skip(f"compat test requires Matplotlib 3.11.x, found {version}")

    plt.set_mode("compat")
    plt.figure()
    calls: list[str] = []
    monkeypatch.setattr(plt, "show", lambda: calls.append("show"))

    plt._flush_inline_figures()

    assert calls == ["show"]


def test_compat_toolkit_can_create_the_first_figure_before_a_routed_call(
    tmp_path: Path,
) -> None:
    result = _run_fresh(
        """
        import xy.pyplot as plt
        from mpl_toolkits.axes_grid1 import host_subplot

        host = host_subplot(111)
        plt.subplots_adjust(right=0.75)
        assert type(host.figure.canvas).__module__ == "xy.backends.backend_xy"
        assert host.figure.canvas.fallback_used is False
        """,
        mode="compat",
        extra_environment={
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(tmp_path / "mplconfig"),
        },
    )
    assert result.returncode == 0, result.stderr
