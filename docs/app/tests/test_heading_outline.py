"""Regression coverage for public documentation heading outlines."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

DOCS_APP_ROOT = Path(__file__).resolve().parent.parent
CHECK_HEADING_OUTLINE_PATH = DOCS_APP_ROOT / "scripts" / "check_heading_outline.py"
SPEC = importlib.util.spec_from_file_location(
    "xy_docs_check_heading_outline",
    CHECK_HEADING_OUTLINE_PATH,
)
if SPEC is None or SPEC.loader is None:
    msg = f"Unable to load heading-outline validator: {CHECK_HEADING_OUTLINE_PATH}"
    raise RuntimeError(msg)
check_heading_outline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_heading_outline)


def _heading(level: int) -> SimpleNamespace:
    """Return one minimal rendered heading for validator unit tests."""
    return SimpleNamespace(
        tag="Heading",
        as_=SimpleNamespace(_var_value=f"h{level}"),
    )


def test_public_docs_have_ordered_heading_levels() -> None:
    """Keep every rendered public route free of heading-level jumps."""
    result = subprocess.run(
        [sys.executable, str(CHECK_HEADING_OUTLINE_PATH)],
        cwd=DOCS_APP_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_heading_outline_validator_rejects_no_headings() -> None:
    """Reject a page with no semantic headings."""
    assert check_heading_outline.heading_outline_errors(()) == (
        "missing H1 (page has no headings)",
    )


def test_heading_outline_validator_rejects_first_h2() -> None:
    """Reject a page whose first semantic heading is not H1."""
    assert check_heading_outline.heading_outline_errors((_heading(2),)) == (
        "first heading is H2, expected H1",
    )


def test_heading_outline_validator_rejects_adjacent_jump() -> None:
    """Reject adjacent headings that skip an outline level."""
    assert check_heading_outline.heading_outline_errors((_heading(1), _heading(3))) == (
        "heading level jumps from H1 to H3",
    )
