"""Reflex Docs code-block rendering adapted for xy."""

import reflex as rx
from reflex_components_code.shiki_code_block import code_block as shiki_code_block


@rx.memo
def _plain_code_block(code: rx.Var[str], language: rx.Var[str]) -> rx.Component:
    """Render code with the same Shiki component used by Reflex Docs."""
    return rx.box(
        shiki_code_block(
            code,
            language=language,
            class_name="code-block",
            can_copy=True,
        ),
        class_name="reflex-code-block",
    )


def code_block_markdown(*children, **props) -> rx.Component:
    """Adapt Reflex Docs' Shiki block to the Markdown component map."""
    return _plain_code_block(
        code=children[0],
        language=props.get("language", "text"),
    )
