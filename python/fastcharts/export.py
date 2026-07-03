"""Standalone HTML export (§29 static-export row): JS client + spec + base64
buffers in one self-contained file — interactive with no kernel attached."""

from __future__ import annotations

import base64
import html as _html
import json
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .figure import Figure

# Warn above this payload size; base64 carries a stated ~33% tax (§29).
EMBED_WARN_BYTES = 64 * 2**20


def to_html(fig: "Figure", path: Optional[str] = None) -> str:
    """Render `fig` to a standalone interactive HTML string (optionally saved).

    User strings (title, names, labels) ride inside <script>/<title> blocks:
    "</" is escaped so "</script>"-shaped content can't break out of the script
    context (markup injection in exported files), and the <title> text is
    entity-escaped."""
    # Lazy: bundled_js lives in widget.py, which imports anywidget — keep that
    # out of `import fastcharts` (§33 import-time budget).
    from .widget import bundled_js

    spec, blob = fig.build_payload()
    if len(blob) > EMBED_WARN_BYTES:
        import warnings

        warnings.warn(
            f"embedding {len(blob) / 2**20:.0f} MB of data (+33% as base64) "
            "into HTML; consider the aggregated embed once Tier 2 lands.",
            RuntimeWarning,
            stacklevel=3,
        )
    spec_js = json.dumps(spec).replace("</", "<\\/")
    title_html = _html.escape(fig.title or "fastcharts")
    doc = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>{title_html}</title>
<style>body{{margin:24px;font-family:system-ui,sans-serif;background:#fff}}</style>
</head>
<body>
<div id="chart"></div>
<script>{bundled_js("standalone")}</script>
<script>
  const spec = {spec_js};
  const b64 = "{base64.b64encode(blob).decode("ascii")}";
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  fastcharts.renderStandalone(document.getElementById("chart"), spec, bytes.buffer);
</script>
</body>
</html>"""
    if path is not None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(doc)
    return doc
