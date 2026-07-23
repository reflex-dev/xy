"""Shared page furniture for the showcase pages: the section card, the
key/value readout row, and the "Code" accordion that shows a section's own
source via ``inspect.getsource``."""

from __future__ import annotations

import inspect
from typing import Any

import reflex as rx
from reflex_xy.tokens import BUILDER_ATTR


def _source(obj: Any) -> str:
    """Source of a plain function, an ``@reflex_xy.figure`` var, or an
    ``@rx.event`` handler."""
    fget = getattr(obj, "_fget", None)
    if fget is not None:  # a @reflex_xy.figure / computed var
        builder = getattr(fget, BUILDER_ATTR, None)
        return inspect.getsource(builder if builder is not None else fget)
    handler = getattr(obj, "fn", None)
    if handler is not None:  # an @rx.event handler
        return inspect.getsource(handler)
    return inspect.getsource(obj)


def code_accordion(*objs: Any) -> rx.Component:
    source = "\n\n".join(inspect.cleandoc("\n" + _source(obj)) for obj in objs)
    return rx.el.details(
        rx.el.summary(
            "Code",
            cursor="pointer",
            padding="0.75rem 1rem",
            font_weight="700",
            font_size="0.85rem",
            list_style="none",
        ),
        rx.el.pre(
            rx.el.code(source),
            margin="0",
            padding="1rem 1.15rem",
            background="#0b1120",
            color="#e5e7eb",
            font_size="0.78rem",
            line_height="1.55",
            overflow_x="auto",
            white_space="pre",
            border_top="1px solid rgba(148,163,184,0.2)",
        ),
        border_top="1px solid var(--gray-5)",
        width="100%",
    )


def section(title: str, blurb: str, body: rx.Component, code: rx.Component) -> rx.Component:
    return rx.box(
        rx.box(
            rx.heading(title, size="5"),
            rx.text(blurb, color_scheme="gray", size="2", margin_top="0.25rem"),
            padding="1rem 1.15rem",
        ),
        rx.box(body, padding="0 1.15rem 1.15rem"),
        code,
        border="1px solid var(--gray-5)",
        border_radius="12px",
        background="var(--gray-1)",
        overflow="hidden",
        width="100%",
    )


def kv(label: str, value: Any) -> rx.Component:
    return rx.hstack(
        rx.badge(label),
        rx.text(value, font_family="monospace", font_size="13px"),
        spacing="3",
        align="center",
    )


def nav(current: str) -> rx.Component:
    """Small page switcher shown under each page heading."""
    links = [("concepts", "/"), ("flights", "/flights")]
    return rx.hstack(
        *[
            rx.badge(name, variant="solid")
            if name == current
            else rx.link(rx.badge(name, variant="soft"), href=href)
            for name, href in links
        ],
        spacing="2",
    )
