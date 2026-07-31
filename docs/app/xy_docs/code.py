"""Accessible code blocks for the XY documentation site."""

from __future__ import annotations

import json
import textwrap

import reflex as rx
import ruff_format
from reflex_base.vars import get_unique_variable_name
from reflex_base.vars.base import Var
from reflex_components_code.shiki_code_block import code_block as shiki_code_block

EXPAND_THRESHOLD_LINES = 20
_LANGUAGE_ALIASES = {
    "dockerfile": "docker",
    "md": "markdown",
    "text": "plain",
}


def _copy_hook_lines(identifier: str, code: str) -> tuple[str, ...]:
    """Return the local React hooks for one independently stateful copy button."""
    status = f"copyStatus_{identifier}"
    set_status = f"setCopyStatus_{identifier}"
    timer = f"copyTimer_{identifier}"
    handler = f"copyCode_{identifier}"
    return (
        f'const [{status}, {set_status}] = useState("idle");',
        f"const {timer} = useRef(null);",
        f"""
const {handler} = () => {{
  {set_status}("copied");
  window.clearTimeout({timer}.current);
  {timer}.current = window.setTimeout(() => {set_status}("idle"), 1500);
  const write = navigator.clipboard?.writeText?.({json.dumps(code)});
  if (!write) {{
    {set_status}("failed");
    return;
  }}
  write.catch(() => {set_status}("failed"));
}};
""".strip(),
    )


def code_copy_feedback_script(code: str = "print('hello')") -> str:
    """Return representative client-side copy behavior for tests and review."""
    return "\n".join(_copy_hook_lines("test", code))


class _CopyButton(rx.el.Button):
    """A native button with component-local clipboard feedback state."""

    @classmethod
    def create(cls, code: str) -> rx.Component:
        """Create one independently stateful copy control."""
        identifier = get_unique_variable_name()
        status = Var(_js_expr=f"copyStatus_{identifier}", _var_type=str)
        copied = status == "copied"
        failed = status == "failed"
        label = rx.cond(copied, "Copied", rx.cond(failed, "Copy failed", "Copy code"))

        component = super().create(
            rx.icon(
                "copy",
                size=16,
                aria_hidden="true",
                class_name="group-data-[copy-state=copied]:hidden",
                custom_attrs={"data-xy-code-copy-icon": "copy"},
            ),
            rx.icon(
                "check",
                size=16,
                aria_hidden="true",
                class_name="hidden group-data-[copy-state=copied]:block",
                custom_attrs={"data-xy-code-copy-icon": "copied"},
            ),
            type="button",
            title=label,
            aria_label=label,
            aria_live="polite",
            aria_atomic="true",
            on_click=rx.run_script(Var(_js_expr=f"copyCode_{identifier}()")),
            custom_attrs={
                "data-xy-code-copy": "true",
                "data-xy-code-copy-implementation": "stateful",
                "data-xy-code-copy-state": status,
            },
            style={
                '&[data-xy-code-copy-state="copied"] [data-xy-code-copy-icon="copy"]': {
                    "display": "none",
                },
                '&[data-xy-code-copy-state="copied"] [data-xy-code-copy-icon="copied"]': {
                    "display": "block",
                },
            },
            class_name=(
                "group absolute right-1 top-1 inline-flex size-7 items-center justify-center "
                "rounded-md border border-secondary-5 bg-secondary-3 text-secondary-11 "
                "transition hover:bg-secondary-4 hover:text-secondary-12 "
                "active:bg-secondary-5 focus:outline-none "
                "focus-visible:ring-2 focus-visible:ring-primary-7"
            ),
        )
        component._copy_identifier = identifier
        component._copy_code = code
        return component

    def add_imports(self) -> dict[str, list[str]]:
        """Import the React hooks used by the local copied state."""
        return {"react": ["useRef", "useState"]}

    def add_hooks(self) -> list[str]:
        """Render the local status, timer, and clipboard handler hooks."""
        return list(_copy_hook_lines(self._copy_identifier, self._copy_code))


def _copy_button(code: str) -> rx.Component:
    """Render a named native button with client-only copied feedback."""
    return _CopyButton.create(code)


def _plain_code_block(code: str, language: str) -> rx.Component:
    """Render one syntax-highlighted block with the local copy control."""
    shiki_language = _LANGUAGE_ALIASES.get(language, language)
    return rx.box(
        shiki_code_block(
            code,
            language=shiki_language,
            class_name="code-block",
            can_copy=True,
            copy_button=_copy_button(code),
        ),
        class_name="relative mb-4",
    )


def code_block(code: str, language: str) -> rx.Component:
    """Render copyable code, preserving the shared long-block disclosure UX."""
    if code.count("\n") + 1 <= EXPAND_THRESHOLD_LINES:
        return _plain_code_block(code, language)
    return rx.el.div(
        _plain_code_block(code, language),
        rx.el.details(
            rx.el.summary(
                rx.el.span(
                    "Expand",
                    rx.icon(
                        "chevron-down",
                        size=14,
                        class_name="ml-1 inline-block align-[-2px]",
                    ),
                    class_name="group-open/details:hidden",
                ),
                rx.el.span(
                    "Collapse",
                    rx.icon(
                        "chevron-up",
                        size=14,
                        class_name="ml-1 inline-block align-[-2px]",
                    ),
                    class_name="hidden group-open/details:inline",
                ),
                class_name=(
                    "list-none cursor-pointer rounded-b-xl bg-gradient-to-t "
                    "from-[var(--secondary-2)] from-55% to-transparent pb-3 pt-12 "
                    "text-center text-sm font-medium text-[var(--secondary-11)] "
                    "hover:text-[var(--secondary-12)] group-open/details:bg-none "
                    "group-open/details:pt-3 [&::-webkit-details-marker]:hidden "
                    "[&::marker]:hidden"
                ),
            ),
            class_name="group/details absolute bottom-0 left-0 right-0",
        ),
        class_name=(
            "relative mb-4 mt-4 max-h-[400px] overflow-hidden rounded-xl border "
            "border-[var(--secondary-4)] bg-[var(--secondary-2)] "
            "has-[details[open]]:max-h-none [&_.code-block]:!border-0"
        ),
    )


def doccode(
    code: str,
    language: str = "python",
    lines: tuple[int, int] | None = None,
) -> rx.Component:
    """Format and render source used by a Preview/Code/Data documentation card."""
    if language == "python":
        code = ruff_format.format_string(textwrap.dedent(code)).strip()
    if lines is not None:
        code = textwrap.dedent("\n".join(code.strip().splitlines()[lines[0] : lines[1]])).strip()
    return code_block(code, language)


__all__ = ["code_block", "code_copy_feedback_script", "doccode"]
