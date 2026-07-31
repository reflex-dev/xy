"""Regression coverage for public documentation element IDs."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

DOCS_APP_ROOT = Path(__file__).resolve().parent.parent
CHECK_DUPLICATE_IDS_PATH = DOCS_APP_ROOT / "scripts" / "check_duplicate_ids.py"
SPEC = importlib.util.spec_from_file_location(
    "xy_docs_check_duplicate_ids",
    CHECK_DUPLICATE_IDS_PATH,
)
if SPEC is None or SPEC.loader is None:
    msg = f"Unable to load duplicate-ID validator: {CHECK_DUPLICATE_IDS_PATH}"
    raise RuntimeError(msg)
check_duplicate_ids = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_duplicate_ids)


def test_markdown_page_bodies_have_unique_literal_ids() -> None:
    """Keep Markdown-rendered page content free of duplicate literal IDs."""
    result = subprocess.run(
        [sys.executable, str(CHECK_DUPLICATE_IDS_PATH)],
        cwd=DOCS_APP_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_duplicate_id_validator_rejects_repeated_literal_ids() -> None:
    """Reject two rendered components with the same literal ID."""
    duplicate = SimpleNamespace(_var_value="duplicate")
    first = SimpleNamespace(id=duplicate)
    second = SimpleNamespace(id=duplicate)

    assert check_duplicate_ids.duplicate_ids((first, second)) == ("duplicate",)
