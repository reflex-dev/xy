"""The §5.2 out-of-band view-state API (spec/design/view-state.md).

`reflex_xy.set_view` / `reset_view` / `select` / `clear_selection` mirror
`append`: token in, one wire message out, pushed room-wide through the
registry's on_push seam, with validation raising in the caller's thread and
the unwired (headless/test) path validating without a push target.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from reflex_xy.registry import FigureRegistry

import xy


def make_figure(n: int = 16):
    xs = np.linspace(0.0, 1.0, n)
    return xy.scatter_chart(xy.scatter(xs, xs * 2.0), width=400, height=300).figure()


def _wired(registry: FigureRegistry):
    """Attach a recording push seam on a fresh loop; returns (run, pushed)."""
    pushed: list[tuple[str, dict, list[bytes]]] = []

    async def on_push(token, message, buffers):
        pushed.append((token, message, buffers))

    def run(call) -> None:
        async def main():
            registry.attach_loop(asyncio.get_running_loop())
            registry.on_push(on_push)
            call()
            await asyncio.sleep(0.05)

        asyncio.run(main())

    return run, pushed


def test_set_view_pushes_state_patch(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    run, pushed = _wired(registry)
    run(lambda: registry.set_view(token, {"x": (0.2, 0.8)}, animate=False))
    ((pushed_token, message, buffers),) = pushed
    assert pushed_token == token
    assert message["type"] == "state_patch"
    assert message["state"] == {"v": 1, "ranges": {"x": [0.2, 0.8]}}
    assert message["animate"] is False
    assert buffers == []
    # The token stays the only chart state: no payload rebuild, no version bump.
    assert registry.get(token).version == 1


def test_reset_view_and_clear_selection_push(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    run, pushed = _wired(registry)
    run(lambda: registry.reset_view(token, ("x",)))
    run(lambda: registry.clear_selection(token))
    kinds = [message["type"] for _tok, message, _buf in pushed]
    assert kinds == ["view_nav", "state_patch"]
    assert pushed[0][1] == {"type": "view_nav", "op": "reset", "axes": ["x"]}
    assert pushed[1][1]["state"]["selection"] is None


def test_select_geometric_and_rows(_fresh_registry):
    registry = _fresh_registry
    fig = make_figure()
    token = registry.register(fig)
    run, pushed = _wired(registry)
    run(lambda: registry.select(token, range=(0.0, 0.5, 0.0, 1.0)))
    run(lambda: registry.select(token, rows={0: [1, 2, 3]}))
    geometric, rows = pushed[0][1], pushed[1][1]
    assert geometric["type"] == "state_patch"
    assert geometric["state"]["selection"]["range"] == {
        "x0": 0.0,
        "x1": 0.5,
        "y0": 0.0,
        "y1": 1.0,
    }
    assert rows["type"] == "selection_rows"
    assert rows["total"] == 3
    assert pushed[1][2]  # mask buffers ride as binary attachments


def test_validation_raises_in_caller_thread(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    run, pushed = _wired(registry)
    with pytest.raises(ValueError, match="unknown axis"):
        run(lambda: registry.set_view(token, {"zz": (0, 1)}))
    with pytest.raises(ValueError):
        run(lambda: registry.select(token))
    with pytest.raises(ValueError):
        run(lambda: registry.select(token, rows=[0], range=(0, 1, 0, 1)))
    assert pushed == []


def test_unwired_path_validates_without_push(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    # No loop attached (tests, headless): validated, nobody to push to.
    registry.set_view(token, {"x": (0.0, 1.0)})
    with pytest.raises(ValueError):
        registry.set_view(token, {"nope": (0.0, 1.0)})
    with pytest.raises(KeyError):
        registry.set_view("missing", {"x": (0.0, 1.0)})


def test_module_level_wrappers(_fresh_registry):
    import reflex_xy

    registry = _fresh_registry
    token = registry.register(make_figure())
    # The public functions are thin aliases over the process registry.
    reflex_xy.set_view(token, {"x": (0.1, 0.9)})
    reflex_xy.reset_view(token)
    reflex_xy.clear_selection(token)
    with pytest.raises(KeyError):
        reflex_xy.select("missing", range=(0, 1, 0, 1))
