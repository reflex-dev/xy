"""Interactive palette controls for the styling examples."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import reflex as rx
import reflex_xy

import xy

BERRY_PALETTE = ("#8e51ff", "#2b7fff", "#00b8db")
INDIGO_PALETTE = ("#2b7fff", "#8e51ff", "#6a7282")
OCEAN_PALETTE = ("#2b7fff", "#00b8db", "#00bc7d")
TWILIGHT_PALETTE = ("#8e51ff", "#fe9a00", "#2b7fff")
GLACIER_PALETTE = ("#00b8db", "#00bc7d", "#6a7282")
PLAYGROUND_PALETTES = (
    ("Berry", BERRY_PALETTE),
    ("Indigo", INDIGO_PALETTE),
    ("Ocean", OCEAN_PALETTE),
    ("Twilight", TWILIGHT_PALETTE),
    ("Glacier", GLACIER_PALETTE),
)

_PLAYGROUND_LAYOUT_CSS = """
main:has(#xy-palette-playground) > div:has(#toc-navigation) {
  display: none;
}
main:has(#xy-palette-playground) > div:has(article #xy-palette-playground) {
  max-width: 88rem;
}
"""

_HIDDEN_AXIS_STYLE = {
    "axis_width": 0,
    "axis_color": "#00000000",
    "tick_width": 0,
    "tick_color": "#00000000",
    "tick_label_color": "#00000000",
    "label_color": "#00000000",
}
_HIDDEN_X_AXIS_STYLE = {**_HIDDEN_AXIS_STYLE, "grid_opacity": 0}


class ChartPlaygroundState(rx.State):
    """Palette values shared by every live chart in the playground."""

    preset: str = "Berry"
    copied_chart: str = ""
    copy_sequence: int = 0
    primary: str = BERRY_PALETTE[0]
    secondary: str = BERRY_PALETTE[1]
    accent: str = BERRY_PALETTE[2]

    @rx.event
    def apply_palette(
        self,
        preset: str,
        primary: str,
        secondary: str,
        accent: str,
    ) -> None:
        """Replace all three colors in one state update."""
        self.preset = preset
        self.primary = primary
        self.secondary = secondary
        self.accent = accent

    @rx.event(background=True)
    async def mark_copied(self, chart: str) -> None:
        """Briefly show which chart most recently copied its code."""
        async with self:
            self.copy_sequence += 1
            copy_sequence = self.copy_sequence
            self.copied_chart = chart

        await asyncio.sleep(1.5)

        async with self:
            if self.copy_sequence == copy_sequence:
                self.copied_chart = ""

    @reflex_xy.figure
    def momentum(self) -> xy.Chart:
        """Build the state-backed area preview."""
        weeks = list(range(1, 13))
        active = [28, 32, 31, 38, 43, 41, 49, 55, 53, 61, 66, 72]
        return xy.area_chart(
            xy.area(
                weeks,
                active,
                name="Current",
                color=self.primary,
                fill=(f"linear-gradient({self.primary}4d 5%, {self.primary}00 95%)"),
                opacity=1,
                curve="smooth",
                line_width=2,
                line_opacity=1,
            ),
            xy.tooltip(title="Week {x}", format={"y": ",.0f"}),
            xy.x_axis(
                tick_count=6,
                tick_label_strategy="none",
                style=_HIDDEN_X_AXIS_STYLE,
            ),
            xy.y_axis(
                domain=(0, 80),
                tick_label_strategy="none",
                style=_HIDDEN_AXIS_STYLE,
            ),
            width="100%",
            height=300,
            padding=(26, 24, 42, 46),
        )

    @reflex_xy.figure
    def comparison(self) -> xy.Chart:
        """Build the state-backed line comparison preview."""
        months = list(range(1, 13))
        signups = [18, 24, 22, 31, 36, 40, 45, 43, 52, 58, 63, 69]
        activated = [12, 16, 17, 21, 25, 29, 32, 35, 39, 44, 49, 54]
        return xy.line_chart(
            xy.line(
                months,
                signups,
                name="Signups",
                color=self.primary,
                width=2.6,
                curve="smooth",
            ),
            xy.line(
                months,
                activated,
                name="Activated",
                color=self.secondary,
                width=2.6,
                curve="smooth",
            ),
            xy.tooltip(title="Month {x}", format={"y": ",.0f"}),
            xy.legend(loc="upper left"),
            xy.x_axis(
                tick_count=6,
                tick_label_strategy="none",
                style={"grid_opacity": 0},
            ),
            xy.y_axis(
                domain=(0, 80),
                tick_label_strategy="none",
                style=_HIDDEN_AXIS_STYLE,
            ),
            width="100%",
            height=300,
            padding=(28, 24, 42, 46),
        )

    @reflex_xy.figure
    def product_mix(self) -> xy.Chart:
        """Build the state-backed stack with only its outside edge rounded."""
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        core = [28, 31, 35, 38, 42, 46]
        growth = [16, 18, 19, 23, 25, 29]
        enterprise = [7, 8, 10, 12, 14, 17]
        enterprise_base = [
            core_value + growth_value for core_value, growth_value in zip(core, growth, strict=True)
        ]
        return xy.column_chart(
            xy.column(months, core, name="Core", color=self.primary),
            xy.column(months, growth, base=core, name="Growth", color=self.secondary),
            xy.column(
                months,
                enterprise,
                base=enterprise_base,
                name="Enterprise",
                color=self.accent,
                corner_radius=(6, 0),
            ),
            xy.tooltip(title="{x}", format={"y": "$,.0fK"}),
            xy.legend(loc="upper left"),
            xy.x_axis(tick_label_strategy="none", style={"grid_opacity": 0}),
            xy.y_axis(
                domain=(0, 100),
                tick_label_strategy="none",
                style=_HIDDEN_AXIS_STYLE,
            ),
            width="100%",
            height=300,
            padding=(28, 24, 42, 48),
        )

    @reflex_xy.figure
    def funnel(self) -> xy.Chart:
        """Build the state-backed horizontal bar preview."""
        stages = ["Visit", "Signup", "Activate", "Invite", "Retain"]
        completion = [94, 82, 71, 58, 47]
        return xy.bar_chart(
            xy.bar(
                stages,
                completion,
                orientation="horizontal",
                color=self.primary,
                fill={
                    "gradient": (f"linear-gradient(to right, {self.secondary}, {self.primary})"),
                    "space": "plot",
                },
                corner_radius=(6, 0),
            ),
            xy.tooltip(title="{x}", format={"y": ".0f%"}),
            xy.x_axis(
                domain=(0, 100),
                tick_label_strategy="none",
                style={"grid_opacity": 0},
            ),
            xy.y_axis(tick_label_strategy="none", style=_HIDDEN_AXIS_STYLE),
            width="100%",
            height=300,
            padding=(24, 24, 42, 82),
        )

    @reflex_xy.figure
    def traffic_share(self) -> xy.Chart:
        """Build the state-backed overlapping area preview."""
        months = list(range(1, 9))
        month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
        desktop = [0.68, 0.65, 0.63, 0.59, 0.61, 0.57, 0.54, 0.52]
        mobile = [0.42, 0.45, 0.43, 0.48, 0.51, 0.56, 0.61, 0.67]
        return xy.area_chart(
            xy.area(
                months,
                desktop,
                name="Desktop",
                color=self.primary,
                fill=(f"linear-gradient({self.primary}4d 5%, {self.primary}00 95%)"),
                opacity=1,
                curve="smooth",
                line_width=2,
                line_opacity=1,
            ),
            xy.area(
                months,
                mobile,
                name="Mobile",
                color=self.secondary,
                fill=(f"linear-gradient({self.secondary}4d 5%, {self.secondary}00 95%)"),
                opacity=1,
                curve="smooth",
                line_width=2,
                line_opacity=1,
            ),
            xy.tooltip(title="{x}", format={"y": ".0f%"}),
            xy.legend(loc="upper left"),
            xy.x_axis(
                tick_values=months,
                tick_labels=month_labels,
                tick_label_strategy="none",
                style=_HIDDEN_X_AXIS_STYLE,
            ),
            xy.y_axis(
                domain=(0, 0.8),
                tick_label_strategy="none",
                style=_HIDDEN_AXIS_STYLE,
            ),
            width="100%",
            height=300,
            padding=(28, 24, 42, 46),
        )

    @reflex_xy.figure
    def channel_mix(self) -> xy.Chart:
        """Build the state-backed grouped-column preview."""
        channels = ["Search", "Social", "Email", "Direct", "Partner", "Referral"]
        channel_centers = list(range(len(channels)))
        organic = [72, 58, 64, 49, 43, 36]
        paid = [54, 46, 38, 42, 35, 29]
        return xy.column_chart(
            xy.column(
                [center - 0.14 for center in channel_centers],
                organic,
                name="Organic",
                color=self.primary,
                width=0.22,
                opacity=1,
                corner_radius=0,
                stroke_width=0,
            ),
            xy.column(
                [center + 0.14 for center in channel_centers],
                paid,
                name="Paid",
                color=self.secondary,
                width=0.22,
                opacity=1,
                corner_radius=0,
                stroke_width=0,
            ),
            xy.tooltip(title="Channel mix", format={"y": ",.0fK"}),
            xy.legend(show=False),
            xy.x_axis(
                domain=(-0.5, 5.5),
                tick_values=channel_centers,
                tick_labels=channels,
                tick_label_strategy="none",
                style=_HIDDEN_X_AXIS_STYLE,
            ),
            xy.y_axis(
                domain=(0, 80),
                tick_label_strategy="none",
                style=_HIDDEN_AXIS_STYLE,
            ),
            width="100%",
            height=300,
            padding=(28, 24, 42, 46),
        )

    @rx.var
    def momentum_code(self) -> str:
        """Return a copyable area-chart snippet using the selected palette."""
        return f'''chart = xy.area_chart(
    xy.area(
        list(range(1, 13)),
        [28, 32, 31, 38, 43, 41, 49, 55, 53, 61, 66, 72],
        name="Current",
        color="{self.primary}",
        fill="linear-gradient({self.primary}4d 5%, {self.primary}00 95%)",
        opacity=1,
        curve="smooth",
        line_width=2,
        line_opacity=1,
    ),
    xy.tooltip(title="Week {{x}}", format={{"y": ",.0f"}}),
    xy.x_axis(
        tick_count=6,
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        }},
    ),
    xy.y_axis(
        domain=(0, 80),
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        }},
    ),
)'''

    @rx.var
    def comparison_code(self) -> str:
        """Return a copyable line-chart snippet using the selected palette."""
        return f'''months = list(range(1, 13))
chart = xy.line_chart(
    xy.line(
        months,
        [18, 24, 22, 31, 36, 40, 45, 43, 52, 58, 63, 69],
        name="Signups",
        color="{self.primary}",
        width=2.6,
        curve="smooth",
    ),
    xy.line(
        months,
        [12, 16, 17, 21, 25, 29, 32, 35, 39, 44, 49, 54],
        name="Activated",
        color="{self.secondary}",
        width=2.6,
        curve="smooth",
    ),
    xy.tooltip(title="Month {{x}}", format={{"y": ",.0f"}}),
    xy.legend(loc="upper left"),
    xy.x_axis(tick_label_strategy="none", style={{"grid_opacity": 0}}),
    xy.y_axis(
        domain=(0, 80),
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        }},
    ),
)'''

    @rx.var
    def product_mix_code(self) -> str:
        """Return a copyable stacked-column snippet using the selected palette."""
        return f'''months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
core = [28, 31, 35, 38, 42, 46]
growth = [16, 18, 19, 23, 25, 29]
enterprise = [7, 8, 10, 12, 14, 17]
enterprise_base = [a + b for a, b in zip(core, growth, strict=True)]

chart = xy.column_chart(
    xy.column(months, core, name="Core", color="{self.primary}"),
    xy.column(months, growth, base=core, name="Growth", color="{self.secondary}"),
    xy.column(
        months,
        enterprise,
        base=enterprise_base,
        name="Enterprise",
        color="{self.accent}",
        corner_radius=(6, 0),
    ),
    xy.tooltip(title="{{x}}", format={{"y": "$,.0fK"}}),
    xy.legend(loc="upper left"),
    xy.x_axis(tick_label_strategy="none", style={{"grid_opacity": 0}}),
    xy.y_axis(
        domain=(0, 100),
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        }},
    ),
)'''

    @rx.var
    def funnel_code(self) -> str:
        """Return a copyable horizontal-bar snippet using the selected palette."""
        return f'''chart = xy.bar_chart(
    xy.bar(
        ["Visit", "Signup", "Activate", "Invite", "Retain"],
        [94, 82, 71, 58, 47],
        orientation="horizontal",
        color="{self.primary}",
        fill={{
            "gradient": "linear-gradient(to right, {self.secondary}, {self.primary})",
            "space": "plot",
        }},
        corner_radius=(6, 0),
    ),
    xy.tooltip(title="{{x}}", format={{"y": ".0f%"}}),
    xy.x_axis(
        domain=(0, 100),
        tick_label_strategy="none",
        style={{"grid_opacity": 0}},
    ),
    xy.y_axis(
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
        }},
    ),
)'''

    @rx.var
    def traffic_share_code(self) -> str:
        """Return a copyable overlapping-area snippet using the selected palette."""
        return f'''months = list(range(1, 9))
month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
desktop = [0.68, 0.65, 0.63, 0.59, 0.61, 0.57, 0.54, 0.52]
mobile = [0.42, 0.45, 0.43, 0.48, 0.51, 0.56, 0.61, 0.67]

chart = xy.area_chart(
    xy.area(
        months,
        desktop,
        name="Desktop",
        color="{self.primary}",
        fill="linear-gradient({self.primary}4d 5%, {self.primary}00 95%)",
        opacity=1,
        curve="smooth",
        line_width=2,
        line_opacity=1,
    ),
    xy.area(
        months,
        mobile,
        name="Mobile",
        color="{self.secondary}",
        fill="linear-gradient({self.secondary}4d 5%, {self.secondary}00 95%)",
        opacity=1,
        curve="smooth",
        line_width=2,
        line_opacity=1,
    ),
    xy.tooltip(title="{{x}}", format={{"y": ".0f%"}}),
    xy.legend(loc="upper left"),
    xy.x_axis(
        tick_values=months,
        tick_labels=month_labels,
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        }},
    ),
    xy.y_axis(
        domain=(0, 0.8),
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        }},
    ),
)'''

    @rx.var
    def channel_mix_code(self) -> str:
        """Return a copyable grouped-column snippet using the selected palette."""
        return f'''channels = ["Search", "Social", "Email", "Direct", "Partner", "Referral"]
channel_centers = list(range(len(channels)))
organic = [72, 58, 64, 49, 43, 36]
paid = [54, 46, 38, 42, 35, 29]

chart = xy.column_chart(
    xy.column(
        [center - 0.14 for center in channel_centers],
        organic,
        name="Organic",
        color="{self.primary}",
        width=0.22,
        opacity=1,
        corner_radius=0,
        stroke_width=0,
    ),
    xy.column(
        [center + 0.14 for center in channel_centers],
        paid,
        name="Paid",
        color="{self.secondary}",
        width=0.22,
        opacity=1,
        corner_radius=0,
        stroke_width=0,
    ),
    xy.tooltip(title="Channel mix", format={{"y": ",.0fK"}}),
    xy.legend(show=False),
    xy.x_axis(
        domain=(-0.5, 5.5),
        tick_values=channel_centers,
        tick_labels=channels,
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "grid_opacity": 0,
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        }},
    ),
    xy.y_axis(
        domain=(0, 80),
        tick_label_strategy="none",
        style={{
            "axis_width": 0,
            "axis_color": "#00000000",
            "tick_width": 0,
            "tick_color": "#00000000",
            "tick_label_color": "#00000000",
            "label_color": "#00000000",
        }},
    ),
)'''


def _swatch(color: rx.Var | str, *, size: str = "h-3 w-3") -> rx.Component:
    """Render a small state-aware palette swatch."""
    return rx.el.span(
        aria_hidden="true",
        class_name=f"{size} shrink-0 rounded-full border border-black/10",
        style={"background": color},
    )


def _preset_button(label: str, palette: Sequence[str]) -> rx.Component:
    """Render a compact palette preset button."""
    return rx.el.button(
        rx.el.span(*(_swatch(color) for color in palette), class_name="flex -space-x-1"),
        rx.el.span(label),
        type="button",
        aria_pressed=ChartPlaygroundState.preset == label,
        on_click=ChartPlaygroundState.apply_palette(label, *palette),
        class_name=rx.cond(
            ChartPlaygroundState.preset == label,
            (
                "inline-flex h-9 items-center gap-2 rounded-full border border-primary-7 "
                "bg-primary-3 px-3 font-small text-primary-11 transition focus:outline-none "
                "focus-visible:ring-2 focus-visible:ring-primary-7"
            ),
            (
                "inline-flex h-9 items-center gap-2 rounded-full border border-secondary-6 "
                "bg-secondary-1 px-3 font-small text-secondary-11 transition "
                "hover:border-primary-7 hover:bg-primary-3 hover:text-primary-11 "
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-7"
            ),
        ),
    )


def _chart_card(
    title: str,
    chart: rx.Component,
    code: rx.Var,
) -> rx.Component:
    """Render one playground chart card."""
    return rx.el.section(
        rx.el.div(
            rx.el.h3(title, class_name="font-base font-medium text-secondary-12"),
            rx.el.button(
                rx.cond(
                    ChartPlaygroundState.copied_chart == title,
                    rx.icon("check", size=15, aria_hidden="true"),
                    rx.icon("copy", size=15, aria_hidden="true"),
                ),
                type="button",
                title=rx.cond(
                    ChartPlaygroundState.copied_chart == title,
                    "Copied",
                    "Copy code",
                ),
                aria_label=f"Copy {title} code",
                on_click=[
                    rx.set_clipboard(code),
                    ChartPlaygroundState.mark_copied(title),
                ],
                class_name=(
                    "inline-flex size-8 items-center justify-center rounded-md border "
                    "border-secondary-6 bg-secondary-1 text-secondary-9 transition "
                    "hover:border-primary-7 hover:bg-primary-3 hover:text-primary-11 "
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-7"
                ),
            ),
            class_name="flex items-center justify-between gap-4 px-4 py-3.5",
        ),
        rx.el.div(
            chart,
            class_name=(
                "h-[300px] w-full overflow-hidden border-t border-secondary-5 "
                "bg-white p-2 dark:bg-black"
            ),
        ),
        class_name="min-w-0 overflow-hidden rounded-xl border border-secondary-5 bg-secondary-1",
    )


def chart_playground() -> rx.Component:
    """Render palette presets and a responsive grid of state-backed charts."""
    return rx.fragment(
        rx.el.style(_PLAYGROUND_LAYOUT_CSS),
        rx.el.div(
            rx.el.div(
                rx.el.span(
                    "Palette",
                    class_name="shrink-0 font-small font-medium text-secondary-11",
                ),
                rx.el.div(
                    *(_preset_button(label, palette) for label, palette in PLAYGROUND_PALETTES),
                    class_name="flex flex-wrap gap-2",
                ),
                class_name=(
                    "mb-5 flex flex-col gap-3 rounded-xl border border-secondary-5 "
                    "bg-secondary-2 p-3 sm:flex-row sm:items-center sm:justify-between"
                ),
            ),
            rx.el.div(
                _chart_card(
                    "Momentum",
                    reflex_xy.chart(
                        ChartPlaygroundState.momentum,
                        id="playground-momentum-chart",
                        height="300px",
                    ),
                    ChartPlaygroundState.momentum_code,
                ),
                _chart_card(
                    "Activation",
                    reflex_xy.chart(
                        ChartPlaygroundState.comparison,
                        id="playground-comparison-chart",
                        height="300px",
                    ),
                    ChartPlaygroundState.comparison_code,
                ),
                _chart_card(
                    "Product mix",
                    reflex_xy.chart(
                        ChartPlaygroundState.product_mix,
                        id="playground-product-mix-chart",
                        height="300px",
                    ),
                    ChartPlaygroundState.product_mix_code,
                ),
                _chart_card(
                    "Conversion",
                    reflex_xy.chart(
                        ChartPlaygroundState.funnel,
                        id="playground-funnel-chart",
                        height="300px",
                    ),
                    ChartPlaygroundState.funnel_code,
                ),
                _chart_card(
                    "Traffic share",
                    reflex_xy.chart(
                        ChartPlaygroundState.traffic_share,
                        id="playground-traffic-share-chart",
                        height="300px",
                    ),
                    ChartPlaygroundState.traffic_share_code,
                ),
                _chart_card(
                    "Channel mix",
                    reflex_xy.chart(
                        ChartPlaygroundState.channel_mix,
                        id="playground-channel-mix-chart",
                        height="300px",
                    ),
                    ChartPlaygroundState.channel_mix_code,
                ),
                class_name="grid grid-cols-1 gap-5 xl:grid-cols-2",
            ),
            id="xy-palette-playground",
            class_name="mb-14 w-full",
        ),
    )


__all__ = [
    "BERRY_PALETTE",
    "GLACIER_PALETTE",
    "INDIGO_PALETTE",
    "OCEAN_PALETTE",
    "PLAYGROUND_PALETTES",
    "TWILIGHT_PALETTE",
    "ChartPlaygroundState",
    "chart_playground",
]
