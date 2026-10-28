"""Default chart controls must leave compact data targets reachable."""

from pathlib import Path

import pytest

import xy
from conftest import probe_document, run_browser_probe
from xy.export import find_chromium

_PROBE = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    view.fluid = true;
    view.fluidH = true;
    const snapshot = () => JSON.stringify(view.gpuTraces.map(g => ({
      x: Array.from(g._cpu.x), y: Array.from(g._cpu.y), runs: Array.from(g._runs || []),
    })));
    view._drawNow();
    const raw = snapshot();
    const results = [];
    for (const width of [360, 380, 768, 1024]) {
      view.root.style.width = width + "px";
      view._resize(width, 300);
      if (view._raf) cancelAnimationFrame(view._raf);
      view._raf = null;
      view._drawNow();
      view.root.dispatchEvent(new PointerEvent("pointerenter"));
      const canvas = view.canvas.getBoundingClientRect();
      const px = canvas.left + view._dataPxX(3) - view.plot.x;
      const py = canvas.top + view._dataPxY(12) - view.plot.y;
      const hit = document.elementFromPoint(px, py);
      const root = view.root.getBoundingClientRect();
      const bar = view._modebar;
      const trigger = view._modebarHeaderButton;
      const visible = trigger && getComputedStyle(trigger).display !== "none" ? trigger : bar;
      const box = visible.getBoundingClientRect();
      const title = view._titleElements[0].element.getBoundingClientRect();
      const result = {
        width, dataHit: hit === view.canvas,
        controlsWithinRoot: box.left >= root.left && box.right <= root.right &&
          box.top >= root.top && box.bottom <= root.bottom,
        controlsAbovePlot: box.bottom <= root.top + view.plot.y,
        titleClear: box.right <= title.left || box.left >= title.right ||
          box.bottom <= title.top || box.top >= title.bottom,
        rawUnchanged: snapshot() === raw,
      };
      const compact = trigger && getComputedStyle(trigger).display !== "none";
      const key = (element, value) => element.dispatchEvent(
        new KeyboardEvent("keydown", { key: value, bubbles: true }),
      );
      if (compact) {
        trigger.focus();
        key(trigger, "ArrowDown");
      }
      const zoom = view._zoomMenuButton;
      zoom.focus();
      key(zoom, "ArrowDown");
      result.keyboardMenu = document.activeElement?.hasAttribute("data-xy-modebar-menu-item") &&
        view._zoomMenuOpen;
      key(document.activeElement, "Escape");
      result.menuFocusRestored = document.activeElement === zoom && !view._zoomMenuOpen;
      if (compact) {
        key(zoom, "Escape");
        result.compactFocusRestored = document.activeElement === trigger &&
          trigger.getAttribute("aria-expanded") === "false" &&
          getComputedStyle(bar).display === "none";
      } else result.compactFocusRestored = true;
      results.push(result);
    }
    document.body.setAttribute("data-xy-modebar-header", JSON.stringify({ results }));
  } catch (err) {
    document.body.setAttribute("data-xy-modebar-header-error", String(err.stack || err));
  }
})();
</script>
"""


@pytest.mark.parametrize("scale", [1, 2])
@pytest.mark.parametrize(
    "title",
    ["Measured values", "Line · spike + missing sample (known bridge bug)"],
)
def test_default_modebar_leaves_data_and_titles_clear(
    scale: int,
    title: str,
    tmp_path: Path,
) -> None:
    """Both full controls and their compact entry remain outside the data rectangle."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no Chromium available for modebar header placement")
    chart = xy.line_chart(
        xy.line(list(range(11)), [1, 2, 3, 12, 3, float("nan"), 4, 5, 4, 3, 2], name="Measured"),
        xy.legend(show="auto"),
        title=title,
        width=720,
        height=300,
    )
    result = run_browser_probe(
        chromium,
        probe_document(chart, _PROBE),
        tmp_path / "modebar_header.html",
        "data-xy-modebar-header",
        label="modebar header placement",
        extra_args=(f"--force-device-scale-factor={scale}",),
    )
    for case in result["results"]:
        assert case["dataHit"], case
        assert case["controlsWithinRoot"], case
        assert case["controlsAbovePlot"], case
        assert case["titleClear"], case
        assert case["rawUnchanged"], case
        assert case["keyboardMenu"], case
        assert case["menuFocusRestored"], case
        assert case["compactFocusRestored"], case


def test_no_header_space_keeps_floating_controls_and_manual_positions(tmp_path: Path) -> None:
    """Tight authored layouts retain the floating fallback and explicit drag intent."""
    chromium = find_chromium()
    if not chromium:
        pytest.skip("no Chromium available for modebar fallback placement")
    chart = xy.line_chart(xy.line([0, 1], [1, 2]), width=380, height=300, padding=[0, 0, 0, 0])
    probe = r"""
<script>
(() => {
  try {
    const view = window.__fcProbeView;
    view._drawNow();
    view.root.dispatchEvent(new PointerEvent("pointerenter"));
    const fallback = view._modebar.dataset.xyModebarPlacement === "floating" &&
      getComputedStyle(view._modebarHeaderButton).display === "none" &&
      getComputedStyle(view._modebar).display !== "none";
    view._modebarMoved = true;
    view._modebar.style.left = "100px";
    view._modebar.style.top = "90px";
    view._fitModebar(true);
    document.body.setAttribute("data-xy-modebar-fallback", JSON.stringify({
      fallback,
      manualLeft: view._modebar.style.left,
      manualTop: view._modebar.style.top,
    }));
  } catch (err) {
    document.body.setAttribute("data-xy-modebar-fallback-error", String(err.stack || err));
  }
})();
</script>
"""
    result = run_browser_probe(
        chromium,
        probe_document(chart, probe),
        tmp_path / "modebar_fallback.html",
        "data-xy-modebar-fallback",
        label="modebar fallback placement",
    )
    assert result == {"fallback": True, "manualLeft": "100px", "manualTop": "90px"}
