"""The compatibility corpus, executed.

Every file in tests/pyplot/corpus/ is a small, self-contained script written
in plain matplotlib idiom (only the import line names xy). Each must
run unmodified against the shim. The corpus *defines* the supported surface:
a shim change that breaks a snippet is a compatibility regression, and a new
supported idiom lands as a new snippet.

Beyond "raises nothing", the runner asserts structural sanity: any figure a
snippet leaves open must render real HTML, and any file a snippet saved (a
`pathlib.Path` left in its namespace) must carry the right magic bytes.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pytest

import xy.pyplot as plt
from xy.pyplot._state import all_figures

CORPUS_DIR = pathlib.Path(__file__).resolve().parent / "corpus"
CORPUS = sorted(CORPUS_DIR.glob("[0-9][0-9]_*.py"))

# Snippets that expose real shim bugs: kept in the corpus, expected to fail.
# filename -> reason
XFAILS: dict[str, str] = {}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HTML_MAGIC = "<!doctype html>"


def _assert_open_figures_render() -> None:
    """Every figure the snippet left open must materialize real HTML."""
    for fig in all_figures():
        html = fig._repr_html_()
        assert html.startswith(HTML_MAGIC), (
            f"figure {fig.number} produced non-HTML output: {html[:60]!r}"
        )


def _assert_saved_files_sane(namespace: dict[str, Any]) -> None:
    """Any Path a snippet bound (its savefig targets) must hold real output."""
    for value in namespace.values():
        if not isinstance(value, pathlib.Path) or not value.is_file():
            continue
        if value.suffix == ".png":
            head = value.read_bytes()[: len(PNG_MAGIC)]
            assert head == PNG_MAGIC, f"{value.name}: not a PNG ({head!r})"
        elif value.suffix == ".html":
            text = value.read_text()
            assert text.startswith(HTML_MAGIC), (
                f"{value.name}: not an HTML document ({text[:60]!r})"
            )


def _corpus_params() -> list[Any]:
    params = []
    for path in CORPUS:
        marks = []
        if path.name in XFAILS:
            marks.append(pytest.mark.xfail(reason=XFAILS[path.name], strict=True))
        params.append(pytest.param(path, id=path.name, marks=marks))
    return params


def test_corpus_is_populated() -> None:
    assert len(CORPUS) >= 35, f"corpus shrank to {len(CORPUS)} snippets"
    unknown = set(XFAILS) - {p.name for p in CORPUS}
    assert not unknown, f"XFAILS names missing snippets: {sorted(unknown)}"


@pytest.mark.parametrize("path", _corpus_params())
def test_corpus_snippet(path: pathlib.Path) -> None:
    plt.close("all")
    namespace: dict[str, Any] = {"__name__": "__main__", "__file__": str(path)}
    try:
        exec(compile(path.read_text(), str(path), "exec"), namespace)  # noqa: S102
        _assert_open_figures_render()
        _assert_saved_files_sane(namespace)
    finally:
        plt.close("all")
