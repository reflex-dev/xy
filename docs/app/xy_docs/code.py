"""Accessible code blocks for the XY documentation site."""

from __future__ import annotations

import textwrap

import reflex as rx
import ruff_format
from reflex_components_code.shiki_code_block import code_block as shiki_code_block

EXPAND_THRESHOLD_LINES = 20
_LANGUAGE_ALIASES = {
    "dockerfile": "docker",
    "md": "markdown",
    "text": "plain",
}

CODE_COPY_STYLE = """
.code-block button[data-xy-code-copy="true"]::after {
    content: none !important;
}

.code-block button[data-xy-code-copy="true"] {
    gap: 0 !important;
    padding: 0 !important;
}

.code-block button[data-xy-code-copy="true"] > svg {
    flex-shrink: 0;
}
"""


def code_copy_feedback_script() -> str:
    """Install accessible, settle-aware clipboard feedback for code blocks."""
    return r"""
(() => {
  if (
    typeof document === "undefined" ||
    window.__xyCodeCopyFeedbackInstalled
  ) {
    return;
  }
  window.__xyCodeCopyFeedbackInstalled = true;

  const resetTimers = new WeakMap();
  const copyAttempts = new WeakMap();

  const renderCopyStatus = (button, state, label, announcement) => {
    button.dataset.xyCodeCopyState = state;
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);
    const control = button.closest("[data-xy-code-copy-control]");
    const liveRegion = control?.querySelector("[data-xy-code-copy-status]");
    if (liveRegion) {
      liveRegion.textContent = announcement;
    }
  };

  const settleCopy = (button, attempt, state, label) => {
    if (copyAttempts.get(button) !== attempt) {
      return;
    }
    const previousTimer = resetTimers.get(button);
    if (previousTimer !== undefined) {
      window.clearTimeout(previousTimer);
    }
    renderCopyStatus(button, state, label, label);
    const resetTimer = window.setTimeout(() => {
      if (copyAttempts.get(button) !== attempt) {
        return;
      }
      renderCopyStatus(button, "idle", "Copy code", "");
      resetTimers.delete(button);
    }, 1500);
    resetTimers.set(button, resetTimer);
  };

  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const button = target.closest("[data-xy-code-copy]");
    if (!(button instanceof HTMLButtonElement)) {
      return;
    }

    const attempt = (copyAttempts.get(button) ?? 0) + 1;
    copyAttempts.set(button, attempt);
    const previousTimer = resetTimers.get(button);
    if (previousTimer !== undefined) {
      window.clearTimeout(previousTimer);
      resetTimers.delete(button);
    }
    renderCopyStatus(button, "idle", "Copy code", "");

    let write;
    try {
      write = navigator.clipboard?.writeText?.(
        button.dataset.xyCodeCopyText ?? "",
      );
    } catch {
      settleCopy(button, attempt, "failed", "Copy failed");
      return;
    }
    if (!write) {
      settleCopy(button, attempt, "failed", "Copy failed");
      return;
    }
    Promise.resolve(write).then(
      () => settleCopy(button, attempt, "copied", "Copied"),
      () => settleCopy(button, attempt, "failed", "Copy failed"),
    );
  });
})();
""".strip()


def _copy_button(code: str) -> rx.Component:
    """Render a named native button with client-only copied feedback."""
    return rx.el.span(
        rx.el.button(
            rx.icon(
                "copy",
                size=16,
                aria_hidden="true",
                custom_attrs={"data-xy-code-copy-icon": "copy"},
            ),
            rx.icon(
                "check",
                size=16,
                aria_hidden="true",
                class_name="hidden",
                custom_attrs={"data-xy-code-copy-icon": "copied"},
            ),
            type="button",
            title="Copy code",
            aria_label="Copy code",
            custom_attrs={
                "data-xy-code-copy": "true",
                "data-xy-code-copy-implementation": "delegated",
                "data-xy-code-copy-state": "idle",
                "data-xy-code-copy-text": code,
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
                "inline-flex size-7 items-center justify-center "
                "rounded-md border border-secondary-5 bg-secondary-3 text-secondary-11 "
                "transition hover:bg-secondary-4 hover:text-secondary-12 "
                "active:bg-secondary-5 focus:outline-none "
                "focus-visible:ring-2 focus-visible:ring-primary-7"
            ),
        ),
        rx.el.span(
            "",
            aria_live="polite",
            aria_atomic="true",
            class_name="sr-only",
            custom_attrs={"data-xy-code-copy-status": "true"},
        ),
        class_name="absolute right-1 top-1",
        custom_attrs={"data-xy-code-copy-control": "true"},
    )


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
