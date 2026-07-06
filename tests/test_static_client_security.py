from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_FILES = (
    ROOT / "js/src/50_chartview.js",
    ROOT / "python/fastcharts/static/index.js",
    ROOT / "python/fastcharts/static/standalone.js",
)


def test_client_user_text_surfaces_use_text_nodes_not_html() -> None:
    """User labels may be hostile strings; the client must never parse them."""
    required_text_sinks = (
        "t.textContent = s.title;",
        "row.appendChild(document.createTextNode(it.name));",
        "d.textContent = text;",
        "this.tooltip.appendChild(document.createTextNode(ln));",
    )
    required_style_sinks = ("sw.style.background = safeCssPaint(this.root, bg);",)
    banned_html_sinks = (
        "insertAdjacentHTML",
        "outerHTML",
        "document.write",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for sink in required_text_sinks:
            assert sink in text, f"{path} no longer protects {sink!r}"
        for sink in required_style_sinks:
            assert sink in text, f"{path} no longer sanitizes {sink!r}"
        for sink in banned_html_sinks:
            assert sink not in text, f"{path} must not use HTML sink {sink}"

        inner_html_lines = [line.strip() for line in text.splitlines() if ".innerHTML" in line]
        assert inner_html_lines == ["b.innerHTML = this._icon(name);"]
