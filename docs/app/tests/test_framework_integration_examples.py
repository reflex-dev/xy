"""Executable coverage for the Reflex integration documentation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FRAMEWORK_INTEGRATION_DOC = Path(__file__).resolve().parents[2] / "integrations" / "reflex.md"


def _python_examples() -> dict[str, str]:
    """Extract Python examples keyed by their nearest Markdown heading.

    Returns:
        The Python source under each section heading.
    """
    examples: dict[str, str] = {}
    heading = "Introduction"
    fence: str | None = None
    source: list[str] = []

    for line in FRAMEWORK_INTEGRATION_DOC.read_text(encoding="utf-8").splitlines():
        if fence is not None:
            if line == fence:
                if heading in examples:
                    msg = f"Multiple Python examples under {heading!r}"
                    raise AssertionError(msg)
                examples[heading] = "\n".join(source)
                fence = None
            else:
                source.append(line)
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif line in {"```python", "~~~python"}:
            fence = line[:3]
            source = []

    if fence is not None:
        msg = f"Unclosed Python fence in {FRAMEWORK_INTEGRATION_DOC}"
        raise AssertionError(msg)
    return examples


def test_framework_integration_examples_run_in_isolation(tmp_path: Path) -> None:
    """Run documented adapter examples without polluting app state or assets."""
    examples = _python_examples()
    assert set(examples) == {
        "Install and Configure",
        "Fixed Charts",
        "State-Backed Charts",
        "Events and Streaming",
        "Custom Chrome Slots",
    }

    runner = f"""
from pathlib import Path

import reflex as rx
import reflex_xy

examples = {examples!r}
doc_path = {str(FRAMEWORK_INTEGRATION_DOC)!r}

for heading, source in examples.items():
    namespace = {{"__name__": f"xy_framework_docs_{{heading.lower().replace(' ', '_')}}"}}
    if heading == "Events and Streaming":
        calls = []
        namespace.update(token="chart-token", next_x=3, next_y=5)
        reflex_xy.append = lambda *args, **kwargs: calls.append((args, kwargs))
        namespace["reflex_xy"] = reflex_xy

    exec(compile(source, f"{{doc_path}}#{{heading}}", "exec"), namespace)

    if heading in {{"Fixed Charts", "State-Backed Charts"}}:
        component = namespace["index"]()
        assert isinstance(component, rx.Component)
        assert "XYChart" in str(component)
    elif heading == "Install and Configure":
        assert any(
            isinstance(plugin, reflex_xy.XYPlugin)
            for plugin in namespace["config"].plugins
        )
    elif heading == "Events and Streaming":
        assert calls == [(('chart-token',), {{'x': [3], 'y': [5]}})]

assets = list(Path("assets/xy").glob("*.xyf"))
assert assets, "The fixed chart example should compile a real static XY payload"
"""
    result = subprocess.run(
        [sys.executable, "-c", runner],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
