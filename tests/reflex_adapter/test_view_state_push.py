"""The §5.2 out-of-band view-state API (spec/design/view-state.md).

`reflex_xy.set_view` / `reset_view` / `select` / `clear_selection` mirror
`append`: token in, one wire message out, pushed room-wide through the
registry's on_push seam, with validation raising in the caller's thread and
the unwired (headless/test) path validating without a push target.
"""

from __future__ import annotations

import asyncio
import threading

import numpy as np
import pytest

import xy
from reflex_xy.registry import FigureRegistry


def make_figure(n: int = 16):
    xs = np.linspace(0.0, 1.0, n)
    return xy.scatter_chart(xy.scatter(xs, xs * 2.0), width=400, height=300).figure()


def _wired(registry: FigureRegistry):
    """Attach a recording push seam on a fresh loop; returns (run, pushed)."""
    pushed: list[tuple[str, dict, list[bytes], int | None]] = []

    async def on_push(token, message, buffers, version=None):
        pushed.append((token, message, buffers, version))

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
    ((pushed_token, message, buffers, generation),) = pushed
    assert pushed_token == token
    assert message["type"] == "state_patch"
    assert message["state"] == {"v": 1, "ranges": {"x": [0.2, 0.8]}}
    assert message["animate"] is False
    assert buffers == []
    assert generation == 1
    # The token stays the only chart state: no payload rebuild, no version bump.
    assert registry.get(token).version == 1


def test_reset_view_and_clear_selection_push(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    run, pushed = _wired(registry)
    run(lambda: registry.reset_view(token, ("x",)))
    run(lambda: registry.clear_selection(token))
    kinds = [message["type"] for _tok, message, _buf, _version in pushed]
    assert kinds == ["view_nav", "state_patch"]
    assert [version for _tok, _message, _buf, version in pushed] == [1, 1]
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
    assert [version for _tok, _message, _buf, version in pushed] == [1, 1]


def test_rows_selection_push_keeps_the_generation_it_was_built_against(_fresh_registry):
    registry = _fresh_registry
    token = registry.register(make_figure())
    run, pushed = _wired(registry)

    def select_then_replace() -> None:
        registry.select(token, rows={0: [1, 2, 3]})
        registry.publish(token, make_figure(32), broadcast=False)

    # The async fan-out runs after the synchronous replacement. Its captured
    # version must still identify the old FigureEntry whose row mask it carries.
    run(select_then_replace)

    ((_, message, buffers, generation),) = pushed
    assert message["type"] == "selection_rows"
    assert buffers
    assert generation == 1
    assert registry.get(token).version == 2


def test_view_build_and_version_are_atomic_with_wired_append(_fresh_registry):
    """A selection mask and its generation cannot straddle append mutation."""
    registry = _fresh_registry
    build_started = threading.Event()
    release_build = threading.Event()
    append_entered = threading.Event()
    second_lock_attempted = threading.Event()

    class Figure:
        points = 0

        def append(self, *_args, **_kwargs):
            append_entered.set()
            self.points += 1
            return {"type": "append", "points": self.points}, []

    class ObservedLock:
        """Expose the second acquisition attempt without weakening the lock."""

        def __init__(self):
            self._lock = threading.Lock()
            self._attempts_lock = threading.Lock()
            self._attempts = 0

        def __enter__(self):
            with self._attempts_lock:
                self._attempts += 1
                if self._attempts == 2:
                    second_lock_attempted.set()
            self._lock.acquire()
            return self

        def __exit__(self, *_exc):
            self._lock.release()

    figure = Figure()
    entry = registry.publish("primary", figure, broadcast=False)
    entry.sync_lock = ObservedLock()
    other = registry.publish("other", Figure(), broadcast=False)
    pushed: list[tuple[str, dict, int | None]] = []

    async def on_push(token, message, _buffers, version=None):
        pushed.append((token, message, version))

    def build(fig):
        build_started.set()
        assert release_build.wait(2.0)
        return {"type": "selection_rows", "points": fig.points}, []

    async def main():
        registry.attach_loop(asyncio.get_running_loop())
        registry.on_push(on_push)
        view_task = asyncio.create_task(
            asyncio.to_thread(registry.push_view_message, "primary", build)
        )
        assert await asyncio.to_thread(build_started.wait, 1.0)
        tasks_before = asyncio.all_tasks()
        registry.append("primary", [1.0], [2.0])
        append_tasks = asyncio.all_tasks() - tasks_before
        assert len(append_tasks) == 1
        append_task = append_tasks.pop()
        assert await asyncio.to_thread(second_lock_attempted.wait, 1.0)
        assert not append_entered.is_set()
        assert figure.points == 0
        assert entry.version == 1

        # The busy primary entry must not serialize message construction for
        # another figure. Use a worker plus timeout so this remains a bounded
        # behavioral assertion even if the implementation regresses.
        other_task = asyncio.create_task(
            asyncio.to_thread(
                registry.push_view_message,
                "other",
                lambda fig: ({"type": "state_patch", "points": fig.points}, []),
            )
        )
        try:
            await asyncio.wait_for(asyncio.shield(other_task), 1.0)
        finally:
            release_build.set()
        await view_task
        await append_task

        for _ in range(20):
            if len(pushed) == 3:
                break
            await asyncio.sleep(0)

    asyncio.run(main())

    assert append_entered.is_set()
    assert figure.points == 1
    assert entry.version == 2
    assert other.version == 1
    assert ("primary", {"type": "selection_rows", "points": 0}, 1) in pushed
    assert ("primary", {"type": "append", "points": 1}, 2) in pushed
    assert ("other", {"type": "state_patch", "points": 0}, 1) in pushed
    assert entry.active_operations == 0
    assert other.active_operations == 0


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
    assert registry.get(token).active_operations == 0


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
