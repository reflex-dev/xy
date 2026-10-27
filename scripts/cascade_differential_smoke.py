#!/usr/bin/env python3
"""Differential smoke: the native cascade against the browser, same inputs.

The Phase-3 exit gate in executable form: one chart, one stylesheet,
resolved twice — once by headless Chromium through the live capture, once
by the mount-free native cascade — and the shared profile properties must
agree. Colors compare parsed (Lightning CSS normalizes `rgb(7, 89, 133)`
to `#075985`; the browser computes `rgb(7, 89, 133)` — same color, two
spellings), lengths compare as px numbers.

    uv run python scripts/cascade_differential_smoke.py [chromium-path]
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

from xy._chromium import ChromiumSession  # noqa: E402
from xy.styling import cascade  # noqa: E402
from xy.styling.resolved import snapshot_from_payload  # noqa: E402

CHROMIUM_CANDIDATES = [
    "chrome-headless-shell",
    "chromium",
    "chromium-browser",
    "chrome",
    "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

CSS = (
    ".smoke-tick { color: rgb(7, 89, 133); font-weight: 600; letter-spacing: 2px; }\n"
    ".smoke-title { color: rgb(120, 20, 20); }"
)

CAPTURE = """
(async () => {
  const until = Date.now() + 60000;
  let root = null;
  while (!(root = document.querySelector('[data-xy-slot="root"]'))) {
    if (Date.now() > until) return JSON.stringify({error: "no chart root"});
    await new Promise((r) => setTimeout(r, 50));
  }
  await window.xy.styleCaptureSettled(document);
  return JSON.stringify({snapshot: window.xy.captureStyleSnapshot(root)});
})()
"""


def find_chromium() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in CHROMIUM_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    raise SystemExit("no chromium found")


def color_rgba(value: str) -> tuple[int, int, int, float]:
    """Any concrete color spelling to an exact rgba tuple."""
    v = value.strip().lower()
    if v.startswith("#"):
        digits = v[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 6:
            digits += "ff"
        r, g, b, a = (int(digits[i : i + 2], 16) for i in (0, 2, 4, 6))
        return r, g, b, round(a / 255.0, 4)
    m = re.match(r"rgba?\(([^)]+)\)", v)
    if m:
        parts = [p.strip() for p in re.split(r"[,/]", m.group(1)) if p.strip()]
        r, g, b = (int(float(p)) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return r, g, b, round(a, 4)
    raise AssertionError(f"unparseable color {value!r}")


def px(value: str) -> float:
    return float(str(value).strip().removesuffix("px"))


def slot_decls(snapshot, slot: str) -> dict:
    for inst in snapshot.instances:
        if inst.slot == slot:
            return dict(snapshot.declarations[inst.declaration])
    return {}


def main() -> None:
    import xy

    chart = xy.scatter_chart(
        xy.scatter([1.0, 2.0, 3.0], [2.0, 1.0, 3.0]),
        title="differential",
        class_names={"tick_label": "smoke-tick", "title": "smoke-title"},
    )

    # Arm 1: the browser.
    document = chart.to_html(custom_css=CSS)
    deadline = time.monotonic() + 120.0

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("differential smoke did not finish in 120s")
        return value

    with ChromiumSession(
        find_chromium(), gl="software", sandbox=False, launch_timeout_s=remaining()
    ) as session:
        _, sid, page_path = session._page_session(document, remaining())
        session._call(
            "Page.navigate", {"url": page_path.as_uri()}, session_id=sid, timeout_s=remaining()
        )
        session._wait_event("Page.loadEventFired", session_id=sid, timeout_s=remaining())
        reply = session._call(
            "Runtime.evaluate",
            {"expression": CAPTURE, "awaitPromise": True, "returnByValue": True},
            session_id=sid,
            timeout_s=remaining(),
        )
    result = json.loads(reply["result"]["value"])
    if result.get("error"):
        raise SystemExit(f"browser capture failed: {result['error']}")
    browser = snapshot_from_payload(result["snapshot"])

    # Arm 2: the mount-free cascade over the same inputs.
    native, unsupported = cascade.resolve_for_figure(chart.figure(), custom_css=CSS)
    assert unsupported == (), f"profile CSS reported unsupported: {unsupported}"

    disagreements: list[str] = []
    for slot, prop, kind in (
        ("tick_label", "color", "color"),
        ("tick_label", "font-weight", "number"),
        ("tick_label", "letter-spacing", "px"),
        ("title", "color", "color"),
    ):
        b = slot_decls(browser, slot).get(prop)
        n = slot_decls(native, slot).get(prop)
        if b is None or n is None:
            disagreements.append(f"{slot}.{prop}: browser={b!r} native={n!r} (missing)")
            continue
        try:
            if kind == "color":
                same = color_rgba(str(b)) == color_rgba(str(n))
            elif kind == "px":
                same = abs(px(str(b)) - px(str(n))) < 0.01
            else:
                same = float(str(b).removesuffix("px")) == float(str(n).removesuffix("px"))
        except (AssertionError, ValueError) as exc:
            disagreements.append(f"{slot}.{prop}: {exc}")
            continue
        if not same:
            disagreements.append(f"{slot}.{prop}: browser={b!r} native={n!r}")
    if disagreements:
        raise SystemExit(
            "cascade disagrees with the browser oracle:\n  " + "\n  ".join(disagreements)
        )

    print(
        "cascade differential smoke ok: browser and mount-free cascade agree on "
        "tick color/weight/letter-spacing and title color for the shared profile"
    )


if __name__ == "__main__":
    main()
