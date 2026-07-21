---
title: Animations and Data Transitions
description: Animate entrances, keyed replacements, reorders, exits, and streaming appends with reduced-motion and deterministic-export control.
---

# Animations and Data Transitions

Add `xy.animation()` as a chart child to give initial render and later live-data
refreshes one declarative motion policy. The browser owns the clock and GPU
interpolation; Python receives only optional start/end lifecycle events.

~~~python demo exec toggle preview-code id=animation-entrance-demo
months = [
    "Jan 23", "Feb 23", "Mar 23", "Apr 23", "May 23", "Jun 23",
    "Jul 23", "Aug 23", "Sep 23", "Oct 23", "Nov 23", "Dec 23",
]
solar_panels = [2890, 2756, 3322, 3470, 3475, 3129, 3490, 2903, 2643, 2837, 2954, 3239]
inverters = [2338, 2103, 2194, 2108, 1812, 1726, 1982, 2012, 2342, 2473, 3848, 3736]

# --- chart ---
import reflex as rx
import reflex_components_internal as ui
import reflex_xy
import xy

chart = xy.chart(
    xy.column(
        months,
        solar_panels,
        key=months,
        name="Solar panels",
        color="#2b7fff",
        corner_radius=0,
        stroke_width=0,
    ),
    xy.line(
        months,
        inverters,
        key=months,
        name="Inverters",
        color="#fe9a00",
        width=2,
        curve="linear",
    ),
    xy.animation(
        enabled="auto",
        duration=650,
        easing=xy.spring(stiffness=150, damping=22),
        match="key",
        enter="auto",
        update="interpolate",
    ),
    xy.legend(show=False),
    xy.tooltip(title="{x}", format={"y": ",.0f"}),
    xy.x_axis(
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.y_axis(
        domain=(0, 4200),
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.theme(
        plot_background="var(--recipe-surface, #ffffff)",
        grid_color="var(--recipe-grid, #e5e7eb)",
        text_color="var(--recipe-text, #4b5563)",
    ),
    class_name=(
        "bg-[#ffffff] [--recipe-surface:#ffffff] [--recipe-grid:#e5e7eb] "
        "[--recipe-text:#4b5563] dark:bg-[#000000] "
        "dark:[--recipe-surface:#000000] dark:[--recipe-grid:#27272a] "
        "dark:[--recipe-text:#d4d4d8]"
    ),
    class_names={
        "tooltip": "rounded-lg bg-zinc-950 px-3 py-2 text-white shadow-xl",
    },
    width="100%",
    height=280,
    padding=[16, 20, 20, 20],
)


class EntranceAnimationDemo(rx.State):
    alternate_mount: bool = False

    @rx.event
    def replay(self):
        self.alternate_mount = not self.alternate_mount


def initial_animation_demo():
    # Switching between keyed mounts restarts the entrance animation.
    return rx.el.div(
        rx.el.div(
            ui.button(
                ui.icon("PlayIcon", aria_hidden="true"),
                "Play animation",
                on_click=EntranceAnimationDemo.replay,
                variant="outline",
                size="sm",
                aria_label="Play entrance animation",
            ),
            class_name="flex w-full justify-end px-4 pt-4 sm:px-5 sm:pt-5",
        ),
        rx.cond(
            EntranceAnimationDemo.alternate_mount,
            reflex_xy.chart(chart, key="entrance-a", height="280px"),
            reflex_xy.chart(chart, key="entrance-b", height="280px"),
        ),
        class_name="w-full",
    )
~~~

`enabled="auto"` is the recommended default: it animates normally and renders
the final state immediately when the browser reports reduced motion. Use
`enabled=False` to suppress motion or `enabled=True` only when the application
intentionally overrides that preference.

## Initial render

`enter="auto"` chooses a mark-aware entrance:

- Line, area, and error bands reveal along their path.
- Bars and columns grow from their baseline.
- Scatter points scale from zero; error bars grow from their centers.

Set `enter` explicitly to `none`, `scale`, `grow`, or `reveal` when a shared
chart needs a different visual language.

~~~python demo exec toggle preview-code id=animation-area-reveal-demo
weeks = list(range(1, 13))
active_teams = [28, 32, 31, 38, 43, 41, 49, 55, 53, 61, 66, 72]

# --- chart ---
import reflex as rx
import reflex_components_internal as ui
import reflex_xy
import xy

chart = xy.area_chart(
    xy.area(
        weeks,
        active_teams,
        base=0,
        name="This period",
        color="#8e51ff",
        fill="linear-gradient(#8e51ff4d 5%, #8e51ff00 95%)",
        opacity=1,
        curve="smooth",
        line_width=2,
    ),
    xy.animation(
        delay=80,
        duration=900,
        enter="reveal",
        easing=xy.spring(stiffness=120, damping=24),
    ),
    xy.tooltip(title="Week {x}", format={"y": ",.0f"}),
    xy.legend(show=False),
    xy.x_axis(
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.y_axis(
        domain=(0, 80),
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    width="100%",
    height=410,
    padding=(16, 20, 20, 20),
)


class AreaRevealDemo(rx.State):
    alternate_mount: bool = False

    @rx.event
    def replay(self):
        self.alternate_mount = not self.alternate_mount


def area_reveal_demo():
    return rx.el.div(
        rx.el.div(
            ui.button(
                ui.icon("PlayIcon", aria_hidden="true"),
                "Play animation",
                on_click=AreaRevealDemo.replay,
                variant="outline",
                size="sm",
                aria_label="Play area reveal animation",
            ),
            class_name="flex w-full justify-end px-4 pt-4 sm:px-5 sm:pt-5",
        ),
        rx.cond(
            AreaRevealDemo.alternate_mount,
            reflex_xy.chart(chart, key="area-reveal-a", height="410px"),
            reflex_xy.chart(chart, key="area-reveal-b", height="410px"),
        ),
        class_name="w-full",
    )
~~~

Named easings are `linear`, `ease`, `ease-in`, `ease-out`, and `ease-in-out`.
A four-number tuple supplies a cubic Bézier; `xy.spring(stiffness=...,
damping=..., mass=...)` supplies a bounded spring policy.

## Replacement, reorder, insert, and delete

Live Reflex state rebuilds and notebook append refreshes update the mounted
chart in place. Use the button in this example to reorder retained accounts,
insert two accounts, remove two, and sharply change their values. Stable keys
let XY distinguish each case:

~~~python demo exec toggle preview-code id=animation-keyed-update-demo
import reflex as rx
import reflex_components_internal as ui
import reflex_xy
import xy


class KeyedAnimationDemo(rx.State):
    updated: bool = False

    @reflex_xy.figure
    def sales(self) -> xy.Chart:
        before = {
            "account_id": ["atlas", "boreal", "cinder", "dune", "ember"],
            "region": ["North", "South", "West", "East", "Central"],
            "sales": [18, 42, 27, 50, 33],
        }
        after = {
            "account_id": ["cinder", "foxtrot", "atlas", "ember", "gale"],
            "region": ["West", "Coastal", "North", "Central", "International"],
            "sales": [54, 16, 46, 22, 60],
        }
        rows = after if self.updated else before
        return xy.column_chart(
            xy.column(
                x="region",
                y="sales",
                key="account_id",
                data=rows,
                color="#2b7fff",
                corner_radius=0,
                stroke_width=0,
            ),
            xy.animation(
                match="key",
                duration=750,
                easing=xy.spring(stiffness=150, damping=22),
                enter="auto",
                update="interpolate",
            ),
            xy.legend(show=False),
            xy.tooltip(title="{x}", format={"y": ",.0f"}),
            xy.x_axis(
                style={
                    "axis_width": 0,
                    "axis_color": "#00000000",
                    "grid_opacity": 0,
                    "tick_width": 0,
                    "tick_color": "#00000000",
                    "tick_label_color": "#00000000",
                    "label_color": "#00000000",
                },
            ),
            xy.y_axis(
                domain=(0, 65),
                style={
                    "axis_width": 0,
                    "axis_color": "#00000000",
                    "tick_width": 0,
                    "tick_color": "#00000000",
                    "tick_label_color": "#00000000",
                    "label_color": "#00000000",
                },
            ),
            xy.theme(
                plot_background="var(--keyed-surface, #ffffff)",
                grid_color="var(--keyed-grid, #e5e7eb)",
                text_color="var(--keyed-text, #4b5563)",
            ),
            class_name=(
                "bg-[#ffffff] [--keyed-surface:#ffffff] [--keyed-grid:#e5e7eb] "
                "[--keyed-text:#4b5563] dark:bg-[#000000] "
                "dark:[--keyed-surface:#000000] dark:[--keyed-grid:#27272a] "
                "dark:[--keyed-text:#d4d4d8]"
            ),
            class_names={
                "tooltip": "rounded-lg bg-zinc-950 px-3 py-2 text-white shadow-xl",
            },
            width="100%",
            height=320,
            padding=[16, 20, 20, 20],
        )

    @rx.event
    def toggle_dataset(self):
        self.updated = not self.updated


def keyed_replacement_demo():
    return rx.el.div(
        rx.el.div(
            rx.text(
                rx.cond(
                    KeyedAnimationDemo.updated,
                    "2 exits · 2 enters · 3 retained",
                    "Five keyed accounts",
                ),
                color_scheme="gray",
                size="2",
            ),
            ui.button(
                ui.icon("PlayIcon", aria_hidden="true"),
                "Play animation",
                on_click=KeyedAnimationDemo.toggle_dataset,
                variant="outline",
                size="sm",
                aria_label="Play keyed replacement animation",
            ),
            class_name=(
                "flex w-full flex-wrap items-center justify-between gap-3 "
                "px-4 pt-4 sm:px-5 sm:pt-5"
            ),
        ),
        reflex_xy.chart(KeyedAnimationDemo.sales, height="320px"),
        class_name="w-full",
    )
~~~

`key=` accepts an array or a `data=` column name on line, area, scatter, bar,
column, error-band, and errorbar marks. Values must be present, supported,
unique, and the same length as the logical rows. XY validates these conditions
before rendering. For a replacement without stable identity, choose
`match="index"` explicitly.

| Mode | Use when |
| --- | --- |
| `key` | Rows can reorder, appear, or disappear and have a stable business ID |
| `append` | An ordered time series retains old x values and adds a tail |
| `index` | Row order itself is the identity |

Each mark may override the chart policy or opt out:

~~~python demo exec toggle preview-code id=animation-mark-override-demo
rows = {
    "x": [0, 1, 2, 3, 4, 5],
    "low": [8, 10, 9, 13, 12, 15],
    "high": [16, 18, 17, 21, 20, 24],
    "mean": [12, 14, 13, 17, 16, 20],
}

# --- chart ---
import reflex as rx
import reflex_components_internal as ui
import reflex_xy
import xy

chart = xy.chart(
    xy.area(
        "x",
        "high",
        base="low",
        data=rows,
        color="#2b7fff",
        fill="linear-gradient(#2b7fff4d 5%, #2b7fff00 95%)",
        opacity=1,
        curve="smooth",
        animation=False,
    ),
    xy.line(
        "x",
        "mean",
        data=rows,
        color="#2b7fff",
        width=2,
        curve="smooth",
        animation=xy.animation(duration=850, enter="reveal"),
    ),
    xy.animation(duration=500, enter="auto"),
    xy.legend(show=False),
    xy.tooltip(title="Sample {x}", format={"y": ",.0f"}),
    xy.x_axis(
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    xy.y_axis(
        domain=(0, 26),
        style={
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        },
    ),
    width="100%",
    height=320,
    padding=[16, 20, 20, 20],
)


class MarkOverrideDemo(rx.State):
    alternate_mount: bool = False

    @rx.event
    def replay(self):
        self.alternate_mount = not self.alternate_mount


def per_mark_animation_demo():
    return rx.el.div(
        rx.el.div(
            ui.button(
                ui.icon("PlayIcon", aria_hidden="true"),
                "Play animation",
                on_click=MarkOverrideDemo.replay,
                variant="outline",
                size="sm",
                aria_label="Play mark override animation",
            ),
            class_name="flex w-full justify-end px-4 pt-4 sm:px-5 sm:pt-5",
        ),
        rx.cond(
            MarkOverrideDemo.alternate_mount,
            reflex_xy.chart(chart, key="mark-override-a", height="320px"),
            reflex_xy.chart(chart, key="mark-override-b", height="320px"),
        ),
        class_name="w-full",
    )
~~~

## Streaming append

Use append matching for a live ordered series. Existing x values retain their
identity while the new tail enters, and append's normal viewport policy still
applies: home follows the domain, a live-edge view slides, and a user looking
at history stays put. Choose a one-, five-, or twelve-point batch below; every
new sample includes bounded random jitter so repeated appends produce different
tails.

~~~python demo exec toggle preview-code id=animation-streaming-demo
import math
import random

import reflex as rx
import reflex_components_internal as ui
import reflex_xy
import xy


class StreamingAnimationDemo(rx.State):
    next_x: int = 2

    @reflex_xy.figure
    def sensor(self) -> xy.Chart:
        return xy.line_chart(
            xy.line(
                [0.0, 1.0],
                [10.0, 12.0],
                name="Sensor",
                color="#8e51ff",
                width=2,
                curve="smooth",
            ),
            xy.animation(match="append", duration=350, easing="linear"),
            xy.legend(show=False),
            xy.tooltip(title="Sample {x}", format={"y": ".2f"}),
            xy.x_axis(
                style={
                    "axis_width": 0,
                    "axis_color": "#00000000",
                    "grid_opacity": 0,
                    "tick_width": 0,
                    "tick_color": "#00000000",
                    "tick_label_color": "#00000000",
                    "label_color": "#00000000",
                },
            ),
            xy.y_axis(
                domain=(7, 15),
                style={
                    "axis_width": 0,
                    "axis_color": "#00000000",
                    "tick_width": 0,
                    "tick_color": "#00000000",
                    "tick_label_color": "#00000000",
                    "label_color": "#00000000",
                },
            ),
            xy.theme(
                plot_background="var(--stream-surface, #ffffff)",
                grid_color="var(--stream-grid, #e5e7eb)",
                text_color="var(--stream-text, #4b5563)",
            ),
            class_name=(
                "bg-[#ffffff] [--stream-surface:#ffffff] [--stream-grid:#e5e7eb] "
                "[--stream-text:#4b5563] dark:bg-[#000000] "
                "dark:[--stream-surface:#000000] dark:[--stream-grid:#27272a] "
                "dark:[--stream-text:#d4d4d8]"
            ),
            class_names={
                "tooltip": "rounded-lg bg-zinc-950 px-3 py-2 text-white shadow-xl",
            },
            width="100%",
            height=320,
            padding=[16, 20, 20, 20],
        )

    @rx.event
    def append_points(self, count: int):
        count = max(1, min(int(count), 12))
        x = [float(self.next_x + offset) for offset in range(count)]
        y = [
            11.0 + 2.2 * math.sin(value * 0.8) + random.uniform(-0.75, 0.75)
            for value in x
        ]
        reflex_xy.append(self.sensor, x=x, y=y)
        self.next_x += count


def streaming_append_demo():
    return rx.el.div(
        rx.el.div(
            rx.text("Randomized stream", color_scheme="gray", size="2"),
            rx.el.div(
                ui.button(
                    "+1 point",
                    on_click=StreamingAnimationDemo.append_points(1),
                    variant="outline",
                    size="sm",
                ),
                ui.button(
                    "+5 points",
                    on_click=StreamingAnimationDemo.append_points(5),
                    variant="outline",
                    size="sm",
                ),
                ui.button(
                    "+12 points",
                    on_click=StreamingAnimationDemo.append_points(12),
                    variant="outline",
                    size="sm",
                ),
                class_name="flex flex-wrap items-center justify-end gap-2",
            ),
            class_name=(
                "flex w-full flex-wrap items-center justify-between gap-3 "
                "px-4 pt-4 sm:px-5 sm:pt-5"
            ),
        ),
        reflex_xy.chart(StreamingAnimationDemo.sensor, height="320px"),
        class_name="w-full",
    )
~~~

In Reflex, use `reflex_xy.append(token, ...)`; a state-driven full dataset
replacement uses keyed or index matching through the same browser controller.
Rapid updates are latest-wins: a new refresh begins at the currently displayed
position, closes the interrupted lifecycle as cancelled, and never queues an
unbounded chain of old scenes.

## Lifecycle callbacks

Live notebook and Reflex hosts expose start/end events. Python callbacks are
configuration, not serialized chart data:

~~~python demo exec toggle preview-code id=animation-lifecycle-demo
import reflex as rx
import reflex_components_internal as ui
import reflex_xy
import xy


class AnimationLifecycleDemo(rx.State):
    shifted: bool = False
    status: str = "Ready"

    @reflex_xy.figure
    def points(self) -> xy.Chart:
        x = [1, 2, 3, 4, 5, 6, 7, 8, 9]
        y = (
            [4, 8, 5, 10, 7, 3, 9, 6, 11]
            if self.shifted
            else [3, 5, 9, 6, 11, 8, 4, 10, 7]
        )
        return xy.scatter_chart(
            xy.scatter(
                x,
                y,
                key=["a", "b", "c", "d", "e", "f", "g", "h", "i"],
                color="#8e51ff",
                size=14,
            ),
            xy.animation(match="key", duration=700, enter="scale"),
            xy.legend(show=False),
            xy.tooltip(title="Point {x}", format={"y": ",.0f"}),
            xy.x_axis(
                style={
                    "axis_width": 0,
                    "axis_color": "#00000000",
                    "grid_opacity": 0,
                    "tick_width": 0,
                    "tick_color": "#00000000",
                    "tick_label_color": "#00000000",
                    "label_color": "#00000000",
                },
            ),
            xy.y_axis(
                domain=(0, 12),
                style={
                    "axis_width": 0,
                    "axis_color": "#00000000",
                    "tick_width": 0,
                    "tick_color": "#00000000",
                    "tick_label_color": "#00000000",
                    "label_color": "#00000000",
                },
            ),
            width="100%",
            height=320,
            padding=[16, 20, 20, 20],
        )

    @rx.event
    def move_points(self):
        self.shifted = not self.shifted

    @rx.event
    def animation_started(self, event: dict):
        self.status = f"Animating {event.get('phase', 'update')}…"

    @rx.event
    def animation_ended(self, event: dict):
        suffix = " (cancelled)" if event.get("cancelled") else ""
        self.status = f"Animation complete{suffix}"


def lifecycle_events_demo():
    return rx.el.div(
        rx.el.div(
            rx.text(AnimationLifecycleDemo.status, color_scheme="gray", size="2"),
            ui.button(
                ui.icon("PlayIcon", aria_hidden="true"),
                "Play animation",
                on_click=AnimationLifecycleDemo.move_points,
                variant="outline",
                size="sm",
                aria_label="Play lifecycle animation",
            ),
            class_name=(
                "flex w-full flex-wrap items-center justify-between gap-3 "
                "px-4 pt-4 sm:px-5 sm:pt-5"
            ),
        ),
        reflex_xy.chart(
            AnimationLifecycleDemo.points,
            on_animation_start=AnimationLifecycleDemo.animation_started,
            on_animation_end=AnimationLifecycleDemo.animation_ended,
            height="320px",
        ),
        class_name="w-full",
    )
~~~

Standalone HTML dispatches local `xy:animation_start` and
`xy:animation_end` DOM events. It has no Python process to invoke.

## Large data stays bounded

Key matching is intentionally limited to direct representations. Above the
matching limit, and for decimated lines or density grids, XY snaps to the new
screen-bounded representation instead of constructing a browser map for every
canonical row. Density and level-of-detail (LOD) tier handoffs retain their separate
stale-while-refine blending and never flash blank.

Direct keyed payloads add two binary 32-bit key words per mark. Position
interpolation adds temporary start buffers only while the animation is active;
the previous scene and scratch buffers are freed at completion.
