"""Static payload assets: the zero-backend chart tier.

`reflex_xy.chart(fc.scatter_chart(...))` — passing a chart object instead of
a token — lands here: the figure compiles once to its first-paint payload,
which is written into the app's ``assets/`` tree as one binary XYBF frame
(``xy.channel`` §3.2 framing) and served as an ordinary static file.
The wrapper fetches it and runs the render client in standalone mode: no
registry entry, no socket subscription, no state — the same interactivity
tier as ``Figure.to_html()`` exports (client-side hover from retained
columns, pan/zoom, worker-based density re-bin), with kernel round-trips
(deep drilldown, server picks, streaming) deliberately out of scope. Reach
for `reflex_xy.inline` or `@reflex_xy.figure` when those matter.

Why this works from any context (docs/design/reflex-integration.md):

- **Page bodies** run in the process that compiles the frontend, *before*
  the compiler copies ``assets/`` into ``.web/public`` — so a file written
  here ships with that compile, including `reflex export` static builds.
- **Module scope** runs everywhere, including prod backend workers; writes
  are content-addressed and idempotent, and skipped entirely under
  ``REFLEX_BACKEND_ONLY`` (mirroring ``rx.asset``) where only the frontend
  build's copy matters.
- Prod backend workers also re-evaluate stateful pages at boot (reflex
  skips only the *saving* of compiled pages) — same guard applies.

The filename is a digest of the frame bytes: unchanged data means an
unchanged URL across recompiles, workers, and machines (and free browser
caching); changed data means a new file, never a stale chart. Orphaned
digests from old data are left in ``assets/xy/`` — they are inert bytes;
delete the directory any time.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from xy.channel import encode_frame

from .registry import _figure_of

__all__ = ["payload_asset"]

# Subdirectory of the app's assets/ tree owned by this module.
ASSET_SUBDIR = "xy"
_DIGEST_CHARS = 20  # 80 bits of sha256 — collision-safe at chart-count scale
_SUFFIX = ".xyf"


def _should_write() -> bool:
    """Only processes that feed a frontend build write asset files."""
    from reflex.assets import EnvironmentVariables

    return not EnvironmentVariables.REFLEX_BACKEND_ONLY.get()


def payload_asset(chart_or_figure: Any) -> str:
    """Compile a chart to a static payload asset; return its URL.

    Returns a reflex ``AssetPathStr`` (frontend-path aware), pointing at
    ``assets/xy/<digest>.xyf`` in the compiling app.
    """
    from reflex.assets import AssetPathStr

    figure = _figure_of(chart_or_figure)
    spec, blob = figure.build_payload()
    frame = encode_frame(spec, [blob])
    digest = hashlib.sha256(frame).hexdigest()[:_DIGEST_CHARS]
    name = f"{digest}{_SUFFIX}"

    if _should_write():
        asset_dir = Path.cwd() / "assets" / ASSET_SUBDIR
        asset_dir.mkdir(parents=True, exist_ok=True)
        dest = asset_dir / name
        if not dest.exists():
            # Content-addressed, so concurrent writers (multiple workers
            # importing the app module) produce identical bytes; the rename
            # keeps a racing reader from ever seeing a partial file.
            tmp = asset_dir / f".{name}.tmp"
            tmp.write_bytes(frame)
            tmp.replace(dest)

    return AssetPathStr(f"/{ASSET_SUBDIR}/{name}")
