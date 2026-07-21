from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "python" / "xy" / "static"
CLIENTS = (
    (
        "source",
        "\n".join(
            path.read_text(encoding="utf-8") for path in sorted((ROOT / "js/src").glob("*.js"))
        ),
    ),
    (
        "widget bundle",
        (STATIC / "index.js").read_text(encoding="utf-8"),
    ),
    (
        "standalone bundle",
        (STATIC / "standalone.js").read_text(encoding="utf-8"),
    ),
)


def test_chart_exposes_parallel_semantic_layer() -> None:
    required = (
        'root.setAttribute("role", "region")',
        'this.canvas.setAttribute("role", "img")',
        "this.canvas.tabIndex = 0",
        'this.a11yLive.setAttribute("role", "status")',
        'this.a11yLive.setAttribute("aria-live", "polite")',
        'this.tooltip.setAttribute("aria-hidden", "true")',
        "this.a11ySummary.textContent = this._a11ySummaryText()",
        "document.getElementById(`${a11yId}-summary`)",
    )
    for label, text in CLIENTS:
        for snippet in required:
            assert snippet in text, f"{label} missing accessibility contract {snippet!r}"


def test_categorical_axes_announce_categories_instead_of_numeric_padding() -> None:
    required = (
        'axis.kind === "category"',
        "Array.isArray(axis.categories)",
        "categories.slice(0, 6)",
        "has ${categories.length} categories:",
    )
    for label, text in CLIENTS:
        for snippet in required:
            assert snippet in text, f"{label} missing categorical axis summary {snippet!r}"


def test_keyboard_navigation_reuses_hover_and_tooltip_pipeline() -> None:
    required = (
        'this._listen(c, "keydown", (e) => this._onA11yKey(e))',
        "const hit = { trace: g.trace.id, index: offset, g }",
        "this._showTooltip(hit, clientX, clientY)",
        "this._drawKeepPick()",
        "Point ${prefix.flat + 1} of ${prefix.total}.",
        "if (this._interactionTransitionActive()) return;",
        'this.a11yLive.textContent = "Readout closed."',
        'this._dispatchChartEvent("leave"',
    )
    for label, text in CLIENTS:
        for snippet in required:
            assert snippet in text, f"{label} keyboard path drifted from hover pipeline"


def test_keyboard_activation_uses_the_click_contract() -> None:
    required = (
        'const activate = e.key === "Enter" || e.key === " ";',
        'if (!this._interactionFlag("click") || !this._hoverTarget) return;',
        'const msg = { type: "click", trace: hit.trace, index: hit.index, screen, modifiers };',
    )
    for label, text in CLIENTS:
        for snippet in required:
            assert snippet in text, f"{label} keyboard activation drifted"


def test_keyboard_exact_replies_preserve_position_and_stale_replies_are_ignored() -> None:
    required = (
        "options.announce !== false",
        "announce: !this._a11yKeyboardReadout",
        "msg.seq !== this._pickSeq",
        "this._a11yKeyboardReadout = { flat, total }",
    )
    for label, text in CLIENTS:
        for snippet in required:
            assert snippet in text, f"{label} exact keyboard readout contract drifted"


def test_toolbar_names_and_reports_toggle_state() -> None:
    required = (
        'bar.setAttribute("role", "toolbar")',
        'bar.setAttribute("aria-label", "Chart controls")',
        'b.setAttribute("aria-label", title)',
        'btn.setAttribute("aria-pressed", String(name === mode))',
    )
    for label, text in CLIENTS:
        for snippet in required:
            assert snippet in text, f"{label} missing accessible toolbar state"


def test_accessibility_media_preferences_are_explicit() -> None:
    for label, text in CLIENTS:
        assert "@media (prefers-reduced-motion:reduce)" in text, label
        assert "@media (forced-colors:active)" in text, label
        assert '[data-xy-slot="canvas"]:focus-visible' in text, label


def test_cross_browser_probe_covers_all_engines_and_honest_metrics() -> None:
    probe = (ROOT / "scripts/browser_conformance.mjs").read_text(encoding="utf-8")
    assert "{ chromium, firefox, webkit }" in probe
    assert "signatureMae" in probe
    assert "maxLayoutDelta" in probe
    assert "Browser text glyphs are" in probe
    assert "s.pressed.length !== 1" in probe
    assert 's.pressed.join() !== "Pan"' not in probe
