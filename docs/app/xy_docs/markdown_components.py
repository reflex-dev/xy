"""Reflex Docs Markdown component map, transplanted for XY."""

from __future__ import annotations

import reflex as rx

from .code import code_block_markdown


def text_comp(text) -> rx.Component:
    """Use the Reflex Docs paragraph component."""
    return rx.text(text, class_name="font-normal text-secondary-11 mb-4 leading-7")


def list_comp(text) -> rx.Component:
    """Use the Reflex Docs list-item component."""
    return rx.list_item(text, class_name="font-normal text-secondary-11 mb-4")


def code_comp(text) -> rx.Component:
    """Use the Reflex Docs inline-code component."""
    return rx.code(text, class_name="code-style")


def doclink(text, **props) -> rx.Component:
    """Use the Reflex Docs content-link component."""
    return rx.el.a(
        text,
        **props,
        class_name="text-secondary-12 decoration-secondary-12 underline",
    )


def image_comp(src) -> rx.Component:
    """Use the Reflex Docs documentation-image component."""
    return rx.image(
        src=src,
        alt="Documentation image",
        class_name="rounded-lg border border-secondary-a4 mb-2",
    )


def markdown_table(*children, **props) -> rx.Component:
    """Use the Reflex Docs responsive table wrapper."""
    return rx.box(
        rx.el.table(
            *children,
            class_name=(
                "w-full border-collapse text-sm border border-secondary-4 "
                "rounded-lg overflow-hidden bg-white-1"
            ),
            **props,
        ),
        class_name=("w-full rounded-xl border border-secondary-a4 my-6 max-w-full overflow-hidden"),
    )


def markdown_thead(*children, **props) -> rx.Component:
    return rx.el.thead(
        *children,
        class_name="bg-secondary-1 border-b border-secondary-4",
        **props,
    )


def markdown_tbody(*children, **props) -> rx.Component:
    return rx.el.tbody(
        *children,
        class_name="[&_tr:nth-child(even)]:bg-secondary-1",
        **props,
    )


def markdown_tr(*children, **props) -> rx.Component:
    return rx.el.tr(
        *children,
        class_name="border-b border-secondary-4 last:border-b-0",
        **props,
    )


def markdown_th(*children, **props) -> rx.Component:
    return rx.el.th(
        *children,
        class_name=("px-3 py-2.5 text-left text-xs font-[575] text-secondary-12 align-top"),
        **props,
    )


def markdown_td(*children, **props) -> rx.Component:
    return rx.el.td(
        *children,
        class_name=("px-3 py-2.5 text-xs font-medium first:font-[575] text-secondary-11 align-top"),
        **props,
    )


COMPONENT_MAP = {
    "p": lambda text: text_comp(text=text),
    "li": lambda text: list_comp(text=text),
    "a": doclink,
    "code": lambda text: code_comp(text=text),
    "pre": code_block_markdown,
    "img": lambda src: image_comp(src=src),
    "table": markdown_table,
    "thead": markdown_thead,
    "tbody": markdown_tbody,
    "tr": markdown_tr,
    "th": markdown_th,
    "td": markdown_td,
}
