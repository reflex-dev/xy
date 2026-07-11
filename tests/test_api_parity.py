"""Guards that the public composition API and the internal engine stay one.

`marks.py` is the single mark implementation — the declarative core. The
internal `Figure` scene binds those functions as its per-kind methods
(`Figure.scatter is marks.scatter`), and the public composition factories
build specs that `_MARK_APPLIERS` replay through those same bound methods.
The recurring failure mode is a keyword or default threaded through one
layer but not the other. These tests turn that drift into a CI failure:

1. every factory prop must map to a real engine parameter (or be one of
   the explicit composition-only props),
2. every engine keyword must be reachable from the factory,
3. every applier must forward every engine keyword to the engine call,
4. the engine's per-kind methods must BE the marks implementations
   (identity), and
5. factory keyword defaults must equal the engine defaults by value.
"""

from __future__ import annotations

import inspect

import pytest

import xy as fc
from xy._figure import Figure
from xy.components import _MARK_APPLIERS

# Props the composition layer owns that intentionally never reach the engine:
# `data` is resolved into arrays before the engine call, and the class/axis
# hooks configure the Chart container rather than the trace.
COMPOSITION_ONLY = {"data", "class_name", "x_axis", "y_axis"}

# factory name -> Figure method name (same-named today; the pairing is
# explicit so a future rename must update the guard deliberately).
MARK_PAIRS = [
    ("scatter", "scatter"),
    ("line", "line"),
    ("area", "area"),
    ("histogram", "histogram"),
    ("hist", "hist"),
    ("bar", "bar"),
    ("column", "column"),
    ("heatmap", "heatmap"),
    ("error_band", "error_band"),
    ("errorbar", "errorbar"),
    ("box", "box"),
    ("violin", "violin"),
    ("ecdf", "ecdf"),
    ("hexbin", "hexbin"),
    ("contour", "contour"),
    ("step", "step"),
    ("stairs", "stairs"),
    ("stem", "stem"),
]

# One inline-data Mark per applier kind, used to exercise real forwarding.
SAMPLE_MARKS = {
    "scatter": lambda: fc.scatter(x=[1.0, 2.0], y=[3.0, 4.0]),
    "line": lambda: fc.line(x=[1.0, 2.0], y=[3.0, 4.0]),
    "area": lambda: fc.area(x=[1.0, 2.0], y=[3.0, 4.0]),
    "histogram": lambda: fc.histogram(values=[1.0, 2.0, 3.0]),
    "bar": lambda: fc.bar(x=["a", "b"], y=[1.0, 2.0]),
    "column": lambda: fc.column(x=["a", "b"], y=[1.0, 2.0]),
    "heatmap": lambda: fc.heatmap(z=[[1.0, 2.0], [3.0, 4.0]]),
    "error_band": lambda: fc.error_band(x=[1.0, 2.0], lower=[2.0, 3.0], upper=[3.0, 4.0]),
    "errorbar": lambda: fc.errorbar(x=[1.0, 2.0], y=[3.0, 4.0], yerr=[0.1, 0.2]),
    "box": lambda: fc.box(values=[[1.0, 2.0], [2.0, 3.0]]),
    "violin": lambda: fc.violin(values=[[1.0, 2.0], [2.0, 3.0]]),
    "ecdf": lambda: fc.ecdf(values=[1.0, 2.0, 3.0]),
    "hexbin": lambda: fc.hexbin(x=[1.0, 2.0], y=[3.0, 4.0]),
    "contour": lambda: fc.contour(z=[[1.0, 2.0], [2.0, 3.0]]),
    "step": lambda: fc.step(x=[1.0, 2.0], y=[3.0, 4.0]),
    "stairs": lambda: fc.stairs(values=[1.0, 2.0], edges=[0.0, 1.0, 2.0]),
    "stem": lambda: fc.stem(x=[1.0, 2.0], y=[3.0, 4.0]),
}


def _param_names(fn) -> set[str]:
    return {name for name in inspect.signature(fn).parameters if name != "self"}


def _keyword_only_names(fn) -> set[str]:
    return {
        name
        for name, p in inspect.signature(fn).parameters.items()
        if p.kind is inspect.Parameter.KEYWORD_ONLY
    }


@pytest.mark.parametrize(("factory_name", "method_name"), MARK_PAIRS)
def test_factory_props_map_to_engine_parameters(factory_name, method_name):
    factory = getattr(fc, factory_name)
    method = getattr(Figure, method_name)
    unmapped = _param_names(factory) - _param_names(method) - COMPOSITION_ONLY
    assert not unmapped, (
        f"fc.{factory_name} accepts {sorted(unmapped)} which map to no "
        f"Figure.{method_name} parameter; either add the engine parameter or "
        "list the prop in COMPOSITION_ONLY"
    )


@pytest.mark.parametrize(("factory_name", "method_name"), MARK_PAIRS)
def test_engine_keywords_all_reachable_from_factory(factory_name, method_name):
    factory = getattr(fc, factory_name)
    method = getattr(Figure, method_name)
    missing = _param_names(method) - _param_names(factory)
    assert not missing, (
        f"Figure.{method_name} gained {sorted(missing)} but fc.{factory_name} "
        "does not expose them; thread the keyword through the factory and its "
        "_apply_* dispatcher"
    )


def test_every_sampled_kind_has_an_applier():
    assert set(SAMPLE_MARKS) == set(_MARK_APPLIERS), (
        "SAMPLE_MARKS and _MARK_APPLIERS must cover the same mark kinds so "
        "the forwarding guard cannot silently skip a chart family"
    )


@pytest.mark.parametrize("kind", sorted(SAMPLE_MARKS))
def test_applier_forwards_every_engine_keyword(kind, monkeypatch):
    mark = SAMPLE_MARKS[kind]()
    method_name = mark.kind  # applier calls the same-named Figure method
    engine_keywords = _keyword_only_names(getattr(Figure, method_name))

    fig = Figure()
    forwarded: dict[str, object] = {}

    def recorder(*args, **kwargs):
        forwarded.update(kwargs)
        return fig

    monkeypatch.setattr(fig, method_name, recorder)
    _MARK_APPLIERS[mark.kind](fig, mark, None)

    dropped = engine_keywords - set(forwarded)
    assert not dropped, (
        f"_apply_{mark.kind} never forwards {sorted(dropped)} to "
        f"Figure.{method_name}; the composition API silently ignores those props"
    )


def test_fluent_methods_are_the_declarative_implementations():
    """The inversion guard: Figure's per-kind methods ARE the marks.py
    functions, so fluent output == declarative output by construction (one
    body, one signature, one set of defaults), not by sampling."""
    from xy import marks

    for _factory_name, method_name in MARK_PAIRS:
        assert getattr(Figure, method_name) is getattr(marks, method_name)


@pytest.mark.parametrize(("factory_name", "method_name"), MARK_PAIRS)
def test_factory_defaults_match_engine_defaults(factory_name, method_name):
    """Factories restate keyword defaults (they add composition-only props and
    make the data positionals optional for the data-key idiom); a default that
    drifts from the engine's silently changes what the declarative dialect
    renders. Compare values, not just names."""
    factory_params = inspect.signature(getattr(fc, factory_name)).parameters
    engine_params = inspect.signature(getattr(Figure, method_name)).parameters
    for name, engine_param in engine_params.items():
        if name in COMPOSITION_ONLY or name not in factory_params:
            continue
        if engine_param.default is inspect.Parameter.empty:
            continue  # engine positional; factory defaults it to None for data keys
        factory_default = factory_params[name].default
        assert factory_default == engine_param.default, (
            f"{factory_name}.{name} default {factory_default!r} != "
            f"Figure.{method_name} default {engine_param.default!r}"
        )
