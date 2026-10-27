#!/usr/bin/env python3
"""Browser-oracle smoke for the style capture (wire-protocol §8).

Renders a styled chart's standalone HTML in headless Chromium, runs the
public `window.xy.captureStyleSnapshot` against the live document, and
validates the captured payload through the Python schema — the same
`snapshot_from_payload` gate a widget reply passes. The assertion that
matters: a value only the browser can resolve (a `custom_css` class rule)
comes back as a concrete computed value, lands in the snapshot, and a
native export fed that snapshot reproduces it. That is the browser-as-
oracle loop with no notebook in it.

    uv run python scripts/style_capture_smoke.py [chromium-path]
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from xy._chromium import ChromiumSession  # noqa: E402
from xy.styling.resolved import snapshot_from_payload  # noqa: E402

CHROMIUM_CANDIDATES = [
    "chrome-headless-shell",
    "chromium",
    "chromium-browser",
    "chrome",
    "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

#: The class rule only a real CSS engine resolves; the capture must return
#: its computed form. Solid and exact on purpose: rgb(7, 89, 133) either
#: round-trips or the smoke fails.
CUSTOM_CSS = ".smoke-tick { color: rgb(7, 89, 133) !important; }"

CAPTURE = """
(async () => {
  // The standalone client mounts after load (decode + first paint), so the
  // capture waits for the root the same way a user's eye does.
  const until = Date.now() + 60000;
  let root = null;
  while (!(root = document.querySelector('[data-xy-slot="root"]'))) {
    if (Date.now() > until) return JSON.stringify({error: "no chart root"});
    await new Promise((r) => setTimeout(r, 50));
  }
  await window.xy.styleCaptureSettled(document);
  const snapshot = window.xy.captureStyleSnapshot(root, {styleEpoch: 7});
  return JSON.stringify({snapshot});
})()
"""


def find_chromium() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


def main() -> None:
    import xy

    chart = xy.scatter_chart(
        xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]),
        title="capture smoke",
        class_names={"tick_label": "smoke-tick"},
    )
    document = chart.to_html(custom_css=CUSTOM_CSS)

    deadline = time.monotonic() + 120.0

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("capture smoke did not finish in 120s")
        return value

    with ChromiumSession(
        find_chromium(), gl="software", sandbox=False, launch_timeout_s=remaining()
    ) as session:
        _, sid, page_path = session._page_session(document, remaining())
        session._call(
            "Page.navigate",
            {"url": page_path.as_uri()},
            session_id=sid,
            timeout_s=remaining(),
        )
        session._wait_event("Page.loadEventFired", session_id=sid, timeout_s=remaining())
        reply = session._call(
            "Runtime.evaluate",
            {"expression": CAPTURE, "awaitPromise": True, "returnByValue": True},
            session_id=sid,
            timeout_s=remaining(),
        )
    if reply.get("exceptionDetails"):
        raise SystemExit(f"capture failed in page: {reply['exceptionDetails']}")
    result = json.loads(reply["result"]["value"])
    if result.get("error"):
        raise SystemExit(f"capture failed: {result['error']}")

    # The Python schema is the door every wire snapshot passes.
    snapshot = snapshot_from_payload(result["snapshot"])
    assert snapshot.style_epoch == 7
    slots = {inst.slot for inst in snapshot.instances}
    assert "tick_label" in slots, f"no tick_label captured; saw {sorted(slots)}"

    tick_decls = [
        snapshot.declarations[inst.declaration]
        for inst in snapshot.instances
        if inst.slot == "tick_label"
    ]
    colors = {decl.get("color") for decl in tick_decls}
    assert "rgb(7, 89, 133)" in colors, (
        f"custom_css class did not reach the capture; tick colors: {colors}"
    )

    # The oracle loop closes: a native export fed the capture reproduces the
    # browser-resolved value with no browser in the export path.
    svg = chart.to_svg(style_snapshot=snapshot)
    assert 'fill="rgb(7, 89, 133)"' in svg, "captured color did not survive native export"

    print(
        f"style capture smoke ok: {len(snapshot.instances)} instances, "
        f"{len(snapshot.declarations)} declarations, "
        f"{snapshot.payload_bytes()} bytes; browser-resolved rgb(7, 89, 133) "
        "round-tripped into a native SVG"
    )


if __name__ == "__main__":
    main()
