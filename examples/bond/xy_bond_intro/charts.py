"""The chart plan for the gun-barrel intro — framework-neutral ``xy`` only.

Six scatter marks, **one fixed plan**. Nothing about the structure depends on
the clock: every mark binds column *names*, and the animation is entirely a
matter of which numbers arrive under those names. That is what lets the Reflex
app publish frames through a single ``@reflex_xy.data`` var without recompiling
a plan or remounting the canvas (the adapter's data-bound tier), and it is what
keeps the engine on its ``updatePayload`` path — where ``match="index"``
position interpolation lives.

:func:`gun_barrel_marks` is the single source of that plan. ``reflex_xy.chart``
consumes the nodes directly for the data-bound tier, and
:func:`gun_barrel_chart` wraps the same nodes into a standalone ``xy.Chart`` for
one-frame ``to_png`` / ``to_html`` rendering — so the previewed, pixel-tested
plan and the served plan cannot drift apart.

Draw order is mark order, so the scene stacks back to front: the lit interior,
the rifling, the barrel walls, the silhouette, the muzzle flash, and finally the
blood over everything.

Every mark is a scatter. A closed circle is not a function of x, so a line mark
would span each pixel column's min/max and paint a filled disc instead of a
ring; point rings are also the form the position interpolator understands
(``scatter`` and ``line`` are the interpolating kinds, and only one of them can
draw a circle).
"""

from __future__ import annotations

from typing import Any

import xy

from .scene import WORLD_ASPECT, WORLD_X, WORLD_Y

__all__ = [
    "BLOOD",
    "FIGURE",
    "FLASH",
    "FRAME_MS",
    "STEEL",
    "gun_barrel_chart",
    "gun_barrel_marks",
]

# The server publishes a keyframe every FRAME_MS; the engine interpolates the
# 60 fps in between. Keeping the animation duration equal to the publish period
# makes each tween land exactly as the next keyframe arrives — continuous motion
# with no stall and no overlap.
FRAME_MS = 83  # the default 12 Hz ceiling's period

# Gunmetal: near-black in the shadow, blown to white at the lit inner lip.
STEEL = ["#05060a", "#23262f", "#5c616e", "#b9bec9", "#ffffff"]
# The silhouette stays black except for the instant the muzzle lights it.
FIGURE = ["#000000", "#0a0b0e", "#6e7480"]
# Muzzle flash: black at zero energy — the parked sparks sit on the muzzle for
# the whole sequence and any non-black floor would leave a visible dot on the
# frame — through cordite orange to a blown-out white core.
FLASH = ["#000000", "#ff8c1a", "#ffe9a8", "#ffffff"]
# Blood: black at zero so the end-of-cycle fade lands on the background rather
# than on a dark-red floor, then dried edges through to arterial red.
BLOOD = ["#000000", "#6d040d", "#b00d19", "#d81926"]


def _cloud(prefix: str, colormap: list[str], size: float, opacity: float = 1.0) -> Any:
    """One layer of the scene: positions and a 0→1 shade under one ramp."""
    return xy.scatter(
        f"{prefix}_x",
        f"{prefix}_y",
        color=f"{prefix}_c",
        colormap=colormap,
        # Pinned, so a layer's own per-frame shade range can never re-stretch
        # its ramp — an auto domain would make the interior pulse as the
        # brightest point in the frame moved.
        color_domain=(0.0, 1.0),
        size=size,
        opacity=opacity,
        # This is artwork, not a density plot: binning would dissolve the
        # silhouette into a heatmap.
        density=False,
        zoom_size_factor=1.0,
    )


def gun_barrel_marks(*, frame_ms: int = FRAME_MS, interpolate: bool = True) -> tuple[Any, ...]:
    """The mark and chrome nodes that make up the plan.

    Args:
        frame_ms: Keyframe publish period in milliseconds, used as the animation
            duration so consecutive tweens abut exactly.
        interpolate: When ``False``, payload updates snap instead of tweening.
            The animation policy is part of the plan, so the two settings are
            two plans; the app mounts one or the other behind an ``rx.cond`` to
            make the interpolation claim falsifiable side by side.
    """
    return (
        # The lit tube interior the silhouette stands in.
        _cloud("wash", STEEL, 3.6),
        # The rifling cut into the barrel wall, then both walls as point rings.
        _cloud("rifle", STEEL, 3.0),
        _cloud("ring", STEEL, 2.2),
        # 007.
        _cloud("fig", FIGURE, 3.8),
        _cloud("flash", FLASH, 4.0, opacity=0.95),
        _cloud("blood", BLOOD, 4.6),
        # A fixed stage: the domains are pinned so no frame can rescale the
        # scene, and rows parked outside them (the waiting blood) are clipped.
        xy.x_axis(domain=WORLD_X, show=False),
        xy.y_axis(domain=WORLD_Y, show=False),
        xy.theme(background="#000000", plot_background="#000000"),
        # The whole trick, in one node: interpolate positions and colors between
        # published keyframes, matching rows by index. `scene.py` guarantees the
        # row counts never change and that row `i` keeps its meaning, so the
        # straight-line tween is the geometrically correct in-between.
        xy.animation(
            enabled=True,
            duration=frame_ms,
            easing="linear",
            match="index",
            update="interpolate" if interpolate else "none",
            interpolate=("position", "color"),
        ),
        # It is a title sequence, not an exploratory chart.
        xy.legend(show=False),
        xy.modebar(show=False),
        xy.tooltip(show=False),
        xy.interaction_config(
            hover=False,
            click=False,
            select=False,
            navigation=False,
            crosshair=False,
        ),
    )


def gun_barrel_chart(
    *,
    height: int = 620,
    frame_ms: int = FRAME_MS,
    interpolate: bool = True,
    data: Any = None,
) -> xy.Chart:
    """The same plan as a standalone ``xy.Chart``, for one-frame rendering.

    The width follows from ``height`` and :data:`~.scene.WORLD_ASPECT`, so a
    still is shaped like the stage and the barrel comes out round.

    Args:
        height: Chart height in pixels.
        frame_ms: Keyframe publish period, in milliseconds.
        interpolate: Whether payload updates tween or snap.
        data: Concrete columns for one frame — pass
            :func:`~.scene.frame_columns` output to render a still with
            ``to_png`` / ``to_html``. The Reflex app leaves this ``None`` and
            binds a ``@reflex_xy.data`` var instead.
    """
    return xy.chart(
        *gun_barrel_marks(frame_ms=frame_ms, interpolate=interpolate),
        width=int(round(height * WORLD_ASPECT)),
        height=height,
        # Edge-to-edge: the axes are hidden, so any plot margin would just
        # shrink the stage away from the aspect the container promises.
        padding=0,
        data=data,
    )
