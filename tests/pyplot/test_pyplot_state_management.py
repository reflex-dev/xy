import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import xy.pyplot as plt


def teardown_function():
    plt.close("all")


def test_pyplot_figure_registry_and_labels():
    plt.figure(3)
    plt.figure("named")

    assert plt.fignum_exists(3)
    assert plt.fignum_exists("named")
    assert "named" in plt.get_figlabels()
    assert 3 in plt.get_fignums()


def test_pyplot_cla_and_clf_clear_current_scope():
    fig, ax = plt.subplots()
    ax.plot([0, 1], [1, 2])
    plt.cla()
    assert ax._entries == []

    ax.plot([0, 1], [2, 3])
    plt.clf()
    assert fig.axes == []
    assert plt.gca().figure is fig


def test_pyplot_axes_delaxes_figtext_and_figlegend():
    fig = plt.figure()
    ax1 = plt.axes([0.1, 0.1, 0.3, 0.3])
    ax2 = plt.axes([0.5, 0.5, 0.3, 0.3])
    assert fig.axes[-1] is ax2

    text = plt.figtext(0.2, 0.8, "figure note")
    assert text._entry["kwargs"]["style"]["coordinate_space"] == "figure_fraction"

    ax1.plot([0, 1], [0, 1], label="line")
    plt.figlegend()
    assert ax1._legend

    plt.delaxes(ax2)
    assert ax2 not in fig.axes


def test_subplot_reuses_match_but_no_arg_axes_is_fresh():
    fig = plt.figure()

    subplot = plt.subplot(111)
    assert plt.subplot(111) is subplot
    first_axes = plt.axes()
    second_axes = plt.axes()

    assert first_axes is not subplot
    assert second_axes is not first_axes
    assert plt.subplot(111) is subplot
    assert fig.axes == [subplot, first_axes, second_axes]
    assert plt.gca() is subplot


def test_reused_subplot_handles_axis_sharing_before_normal_properties():
    fig = plt.figure()
    subplot = fig.add_subplot(111)
    shared = fig.add_axes([0.1, 0.1, 0.2, 0.2])

    reused = plt.subplot(111, sharex=shared, sharey=shared, title="shared")

    assert reused is subplot
    assert reused.get_shared_x_axes().joined(reused, shared)
    assert reused.get_shared_y_axes().joined(reused, shared)
    assert reused.get_title() == "shared"


def test_subplot_mosaic_claims_returned_axes_before_later_add_subplot():
    fig, axes = plt.subplot_mosaic([["left", "right"]])

    assert all(ax._subplot_claimed for ax in axes.values())
    overlay = fig.add_subplot(1, 2, 1)

    assert overlay is not axes["left"]
    assert axes["left"] in fig.axes
    assert overlay in fig.axes


def test_pyplot_twiny_creates_current_axes_on_same_figure():
    fig, ax = plt.subplots()
    twin = plt.twiny()
    assert twin.figure is fig
    assert plt.gca() is twin
    assert twin in fig.axes
    assert twin is not ax


def test_pyplot_installs_one_ipython_end_of_cell_display_hook(monkeypatch):
    callbacks = []
    events = SimpleNamespace(register=lambda event, callback: callbacks.append((event, callback)))
    shell = SimpleNamespace(events=events)
    ipython = ModuleType("IPython")
    ipython.get_ipython = lambda: shell
    monkeypatch.setitem(sys.modules, "IPython", ipython)

    plt._install_ipython_display_hook()
    plt._install_ipython_display_hook()

    assert callbacks == [("post_execute", plt._flush_inline_figures)]
    plt.figure()
    show = Mock()
    monkeypatch.setattr(plt, "show", show)
    callbacks[0][1]()
    show.assert_called_once_with()


def test_pyplot_show_displays_isolated_notebook_repr(monkeypatch):
    shell = object()
    ipython = ModuleType("IPython")
    ipython.get_ipython = lambda: shell
    display_module = ModuleType("IPython.display")
    displayed = []
    display_module.HTML = lambda value: value
    display_module.display = displayed.append
    monkeypatch.setitem(sys.modules, "IPython", ipython)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)

    plt.plot([0, 1], [1, 2])
    plt.show()

    assert len(displayed) == 1
    html = displayed[0]._repr_html_()
    assert html.startswith('<iframe class="xy-notebook-frame"')
    assert "<style>" not in html
    assert "&lt;style&gt;" in html
