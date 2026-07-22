from __future__ import annotations

from pathlib import Path

from xy.components import CHART_DOM_SLOTS

ROOT = Path(__file__).resolve().parents[1]
_STATIC = ROOT / "python" / "xy" / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# The client source is TypeScript ES modules under js/src — 50_chartview.ts
# was decomposed into 50 (core) + 51_annotations/52_tooltip/53_interaction/
# 54_kernel/56_animation/57_viewstate. Assert source-level invariants against
# the whole concatenation so a further split never silently drops a check.
# (label, text) pairs: the label only names the source in failure messages.
#
# The built bundles under python/xy/static are MINIFIED by vite (identifiers
# renamed, whitespace collapsed), so exact source lines cannot be asserted
# against them. Only string-literal / property-name invariants are (see
# test_built_bundles_keep_minification_safe_invariants); every source-level
# check still transfers to the shipped bundles because `node js/build.mjs
# --check` (CI + `make js-check`) proves the committed bundles are compiled
# from exactly this source.
_CLIENT_SRC = (
    "js/src/*.ts",
    "\n".join(_read(p) for p in sorted((ROOT / "js" / "src").glob("*.ts"))),
)
_INDEX = ("static/index.js", _read(_STATIC / "index.js"))
_STANDALONE = ("static/standalone.js", _read(_STATIC / "standalone.js"))

CLIENT_FILES = (_CLIENT_SRC,)
BUNDLES = (_INDEX, _STANDALONE)
FORMATTER_FILES = (("js/src/30_ticks.ts", _read(ROOT / "js/src/30_ticks.ts")),)
LOD_FILES = (("js/src/45_lod.ts", _read(ROOT / "js/src/45_lod.ts")),)
# The chrome default stylesheet lives in the theme part; its rules are string
# literals, so the bundle-level test re-asserts them in both built bundles.
THEME_FILES = (("js/src/20_theme.ts", _read(ROOT / "js/src/20_theme.ts")),)

# Chrome styling contract (§36) — shared between the source-level test and the
# minification-safe bundle test: these all live inside string literals, which
# the minifier preserves verbatim.
_CHROME_WHERE_RULES = (
    ':where(.xy [data-xy-slot="tooltip"]){',
    ':where(.xy [data-xy-slot="legend"]){',
    ':where(.xy [data-xy-slot="legend_swatch"]){',
    ':where(.xy [data-xy-slot="modebar"]){',
    ':where(.xy [data-xy-slot="modebar_button"]){',
    ":where(.xy [data-xy-modebar-menu]){",
    ":where(.xy [data-xy-modebar-menu-item]){",
    ':where(.xy [data-xy-slot="modebar_button"].xy-active){',
    ':where(.xy [data-xy-slot="selection"]){',
    ':where(.xy [data-xy-slot="badge_item"]){',
    ':where(.xy [data-xy-slot="tick_label"]){',
    ':where(.xy [data-xy-slot="axis_title"]){',
    ':where(.xy [data-xy-slot="annotation_label"]){',
    ':where(.xy [data-xy-slot="canvas"]){cursor:',
    ':where(.xy [data-xy-slot="canvas"][data-xy-dragmode="pan"]){cursor:',
)
_CHROME_TOKENS = (
    "--chart-tooltip-bg",
    "--chart-tooltip-text",
    "--chart-legend-bg",
    "--chart-modebar-bg",
    "--chart-modebar-active",
    "--chart-selection",
    "--chart-selection-fill",
    "--chart-crosshair",
    "--chart-badge-bg",
    "--chart-badge-text",
)
_BANNED_HTML_SINKS = (
    "insertAdjacentHTML",
    "outerHTML",
    "document.write",
)


def test_chrome_visual_defaults_are_a_defeatable_where_stylesheet() -> None:
    """Chrome styling lives in a layered, zero-specificity :where() stylesheet
    so user class_names / styles always win (the CSS+Tailwind contract).
    Every chrome slot's visual defaults + --chart-* token must be present, and
    the elements must carry only structural inline styles (no inline
    background/color that would beat a utility class)."""
    for path, text in THEME_FILES:
        assert "@layer base{" in text, (
            f"{path} leaves XY defaults unlayered, which outranks Tailwind utilities"
        )
        for rule in _CHROME_WHERE_RULES:
            assert rule in text, f"{path} missing defeatable chrome rule {rule!r}"
        for token in _CHROME_TOKENS:
            assert token in text, f"{path} no longer themes {token!r} in the stylesheet"
        assert "--xy-badge-text:#0f172a" in text
        assert "--xy-badge-text:#f8fafc" in text
        assert "var(--chart-badge-text,var(--xy-badge-text))" in text
        assert "var(--chart-badge-bg,var(--xy-badge-bg))" in text
        assert "ensureChromeStylesheet" in text

    # The inline tooltip/legend/modebar cssText must not re-set themeable
    # properties (that would beat utility classes on specificity).
    chartview = (ROOT / "js/src/50_chartview.ts").read_text(encoding="utf-8")
    assert "ensureChromeStylesheet(root);" in chartview
    assert "background:var(--chart-tooltip-bg" not in chartview
    # modebar active state is a class toggle, never inline (its builder now lives
    # in 53_interaction.ts, so assert against the whole client source).
    assert 'btn.classList.toggle("xy-active"' in _CLIENT_SRC[1]


def test_normative_styling_spec_tracks_responsive_theme_tokens() -> None:
    styling = _read(ROOT / "spec/api/styling.md")
    assert "--chart-tick-label-max-width" in styling
    normalized_styling = " ".join(styling.split())
    assert "badges to `rgba(30,35,44,.88)` bg / `#f8fafc` text" in normalized_styling


def test_client_user_text_surfaces_use_text_nodes_not_html() -> None:
    """User labels may be hostile strings; the client must never parse them."""
    required_text_sinks = (
        "t.textContent = s.title;",
        "row.appendChild(document.createTextNode(it.name));",
        "badge.textContent = item;",
        "d.textContent = text;",
        "this.tooltip.appendChild(document.createTextNode(ln));",
    )
    required_style_sinks = ("sw.style.background = safeCssPaint(this.root, bg);",)

    for path, text in CLIENT_FILES:
        for sink in required_text_sinks:
            assert sink in text, f"{path} no longer protects {sink!r}"
        for sink in required_style_sinks:
            assert sink in text, f"{path} no longer sanitizes {sink!r}"
        for sink in _BANNED_HTML_SINKS:
            assert sink not in text, f"{path} must not use HTML sink {sink}"

        inner_html_lines = [line.strip() for line in text.splitlines() if ".innerHTML" in line]
        assert inner_html_lines == [
            'grip.innerHTML = this._icon("drag");',
            "b.innerHTML = this._icon(name);",
            'zoomIndicator.innerHTML = this._icon("chevrondown");',
            'selectModeIcon.innerHTML = this._icon("select");',
            'selectIndicator.innerHTML = this._icon("chevrondown");',
            "icon.innerHTML = this._icon(name);",
            "icon.innerHTML = this._icon(name);",
            "icon.innerHTML = this._icon(name);",
            "this._selectMenuIcon.innerHTML = this._icon(iconName);",
        ]


def test_selection_mode_icons_are_crisp_and_the_trigger_tracks_active_mode() -> None:
    """Selection glyphs avoid tiny dashed paths and expose the chosen gesture."""
    required = (
        'selectModeIcon.dataset.xyModebarSelectIcon = "";',
        "this._selectMenuIcon.innerHTML = this._icon(iconName);",
        'select: ["select", "Box Select"]',
        '"select-lasso": ["lasso", "Lasso Select"]',
        '"select-x": ["selectx", "X Range"]',
        '"select-y": ["selecty", "Y Range"]',
    )
    for path, text in CLIENT_FILES:
        for snippet in required:
            assert snippet in text, f"{path} no longer reflects the active selection mode"
        assert 'stroke-dasharray="2.5 2"' not in text, (
            f"{path} restored fractional dashed selection glyphs that blur at toolbar size"
        )

    for path, text in THEME_FILES:
        assert "min-width:42px" in text, f"{path} crowds the selection icon and chevron"
        assert "[data-xy-modebar-select-icon]" in text, path


def test_modebar_exports_are_local_and_exclude_interaction_chrome() -> None:
    """Browser exports stay self-contained and never serialize the toolbar itself."""
    required = (
        'exportMenu.dataset.xyModebarExportMenu = "";',
        'new Blob([svg], { type: "image/svg+xml;charset=utf-8" })',
        'new Blob([this._exportCsvText()], { type: "text/csv;charset=utf-8" })',
        "link.download = filename;",
        "const content = new XMLSerializer().serializeToString(clone);",
        '[data-xy-slot="modebar"],[data-xy-slot="tooltip"]',
        'const columns = ["trace", "name", "kind", "index", "x", "y"',
    )
    for path, text in CLIENT_FILES:
        for snippet in required:
            assert snippet in text, f"{path} missing toolbar export contract {snippet!r}"


def test_pointer_capture_tolerates_synthetic_accessibility_clicks() -> None:
    """Keyboard/automation focus clicks must not abort interaction setup.

    Browsers can reject pointer capture for synthetic pointer events. Every
    capture site therefore needs to degrade cleanly instead of surfacing an
    uncaught ``InvalidStateError`` through the host framework.
    """
    for path, text in CLIENT_FILES:
        capture_lines = [
            line.strip() for line in text.splitlines() if ".setPointerCapture(" in line
        ]
        # canvas drag, band select, lasso handle, modebar grip, axis band
        assert len(capture_lines) == 5, f"{path} has an unexpected capture site"
        assert all(line.startswith("try {") and "catch (_err)" in line for line in capture_lines), (
            f"{path} leaves pointer capture unguarded for synthetic events"
        )


def test_exact_kernel_pick_preserves_shared_tooltip_fields() -> None:
    """Exact pick replies must retain fields resident on sibling layers."""
    required = (
        '} else if (msg.type === "pick_result") {',
        "this._applySharedTooltipFields(msg.row);",
        "this._lastRow = msg.row;",
    )
    for path, text in CLIENT_FILES:
        positions = [text.index(snippet) for snippet in required]
        assert positions == sorted(positions), (
            f"{path} no longer rehydrates a precise tooltip before rendering it"
        )


def test_extra_legends_are_not_suppressed_with_the_primary_legend() -> None:
    """`show_legend=False` controls trace-derived chrome, not explicit artists."""
    for path, text in CLIENT_FILES:
        assert "if (s.show_legend !== false) {" in text, (
            f"{path} no longer gates only the primary legend"
        )
        assert "if (s.show_legend === false) return;" not in text, (
            f"{path} returns before rendering explicit extra legends"
        )


def test_client_numeric_styles_default_to_pixels_for_lengths() -> None:
    """Numeric component styles should behave like common Python/React style APIs."""
    required_style_helpers = (
        "const UNITLESS_STYLE_PROPS = new Set([",
        'if (key.startsWith("--")) return key;',
        # snake_case (the Python API form, e.g. `font_size`) must normalize to
        # the CSS property name, not reach setProperty("font_size", …) verbatim
        # (a silent no-op in the browser). The underscore pass runs before the
        # unitless check so `line_height`/`z_index` are recognized as unitless.
        'key.replace(/_/g, "-").replace(/[A-Z]/g,',
        'if (property.startsWith("--") || UNITLESS_STYLE_PROPS.has(property)) return String(value);',
        "return `${value}px`;",
    )

    for path, text in CLIENT_FILES:
        for helper in required_style_helpers:
            assert helper in text, f"{path} no longer normalizes numeric component styles"


def test_client_selection_band_paint_is_a_defeatable_stylesheet_default() -> None:
    """The box-select/zoom band must paint via the layered :where()
    stylesheet (keyed on data-xy-band), never inline — otherwise a
    `class_names={"selection": …}` utility or `styles[selection]` would lose to
    the inline style, the one slot that breaks the "your styles always win"
    contract (§36)."""
    for path, text in CLIENT_FILES:
        assert "this.selRect.dataset.xyBand =" in text, (
            f"{path} no longer drives the selection band via a data attribute"
        )
        assert "selRect.style.border" not in text and "selRect.style.background" not in text, (
            f"{path} pins selection band paint inline; it must be a stylesheet default"
        )
    for path, text in THEME_FILES:
        assert '[data-xy-slot="selection"][data-xy-band="zoom"]){' in text, (
            f"{path} is missing the defeatable zoom-band :where() default"
        )


def test_client_applies_every_public_dom_slot() -> None:
    slot_snippets = {
        "root": '_applySlot(root, "root")',
        "title": '_applySlot(t, "title")',
        "chrome": '_applySlot(this.chrome, "chrome")',
        "canvas": '_applySlot(this.canvas, "canvas")',
        "labels": '_applySlot(this.labels, "labels")',
        "legend": '_applySlot(lg, "legend")',
        "legend_item": '_applySlot(row, "legend_item")',
        "legend_swatch": '_applySlot(sw, "legend_swatch")',
        "colorbar": '_applySlot(box, "colorbar")',
        "colorbar_bar": '_applySlot(bar, "colorbar_bar")',
        "colorbar_tick": '_applySlot(tick, "colorbar_tick")',
        "colorbar_title": '_applySlot(label, "colorbar_title")',
        "tooltip": '_applySlot(this.tooltip, "tooltip")',
        "modebar": '_applySlot(bar, "modebar")',
        "modebar_button": '_applySlot(b, "modebar_button")',
        "selection": '_applySlot(this.selRect, "selection")',
        "crosshair_x": '_applySlot(this.crosshairX, "crosshair_x")',
        "crosshair_y": '_applySlot(this.crosshairY, "crosshair_y")',
        "badge": '_applySlot(box, "badge")',
        "badge_item": '_applySlot(badge, "badge_item")',
        # tick_label + axis_title share one call keyed on the label kind.
        "tick_label": '_applySlot(d, kind === "label" ? "axis_title" : "tick_label")',
        "axis_title": '_applySlot(d, kind === "label" ? "axis_title" : "tick_label")',
        "annotation_label": '_applySlot(d, "annotation_label")',
    }
    assert tuple(slot_snippets) == CHART_DOM_SLOTS

    for path, text in CLIENT_FILES:
        for slot, snippet in slot_snippets.items():
            assert snippet in text, f"{path} does not apply public DOM slot {slot!r}"


def test_client_stamps_public_dom_slot_attributes() -> None:
    for path, text in CLIENT_FILES:
        assert "el.dataset.xySlot = slot;" in text, f"{path} no longer stamps data-xy-slot"
        assert text.index("el.dataset.xySlot = slot;") < text.index("const dom = this.spec.dom;"), (
            f"{path} stamps slot attributes after reading spec.dom"
        )


def test_standalone_tooltips_retain_encoded_color_and_size_channels() -> None:
    """Static HTML hovers should expose the same tooltip fields as widget hovers."""
    for path, text in CLIENT_FILES:
        assert "this._lastRow = row;" in text, f"{path} no longer caches the hovered row"
        assert "row.color_category = String(color.categories[code]);" in text, (
            f"{path} drops color_category"
        )
        assert (
            "row.color_value = this._denormalizeUnit(cpu.color[hit.index], color.domain);" in text
        ), f"{path} drops color_value"
        assert (
            "row.size_value = this._denormalizeUnit(cpu.size[hit.index], size.domain);" in text
        ), f"{path} drops size_value"

    entries = (ROOT / "js/src/60_entries.ts").read_text(encoding="utf-8")
    assert "g._cpu.color = column(g.trace.color.buf);" in entries
    assert "g._cpu.size = column(g.trace.size.buf);" in entries


def test_client_tooltip_value_formatter_preserves_strings() -> None:
    for path, text in FORMATTER_FILES:
        assert 'if (typeof v === "string") return v;' in text, (
            f"{path} coerces string tooltip values"
        )
        assert "if (!Number.isFinite(n)) return String(v);" in text, (
            f"{path} drops non-finite fallback"
        )


def test_client_can_suppress_builtin_tooltip_for_framework_chrome() -> None:
    for path, text in CLIENT_FILES:
        assert "this.spec.show_tooltip === false" in text, (
            f"{path} can't suppress the builtin tooltip"
        )


def test_client_exposes_first_class_interaction_events() -> None:
    required = (
        "this.interaction = spec.interaction || {};",
        "new CustomEvent(`xy:${name}`",
        'this._dispatchChartEvent("click", detail);',
        'this._dispatchChartEvent("brush",',
        'this._dispatchChartEvent("select",',
        'this.comm.send({ type: "view_change", ...detail });',
        'const msg: any = { type: "click", trace: hit.trace, index: hit.index, screen, modifiers };',
        "new BroadcastChannel(`xy:${group}`)",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer exposes interaction marker {marker!r}"


def test_client_interaction_event_payload_contract_is_stable() -> None:
    required = (
        '_eventView(source = "view")',
        "source,",
        'if (this._interactionFlag("hover")) {',
        'this._dispatchChartEvent("hover", {',
        "row,",
        "trace: hit.trace,",
        "index: hit.index,",
        'view: this._eventView("hover"),',
        'this._dispatchChartEvent("leave", { view: this._eventView("leave"), active: false });',
        'this._dispatchChartEvent("click", detail);',
        "const detail = {",
        "x,",
        "y,",
        'view: this._eventView("click"),',
        "row: hit && this._localRow ? this._localRow(hit) : null,",
        "trace: hit ? hit.trace : null,",
        "index: hit ? hit.index : null,",
        'this._dispatchChartEvent("brush", { range, view: this._eventView("brush") });',
        'this._dispatchChartEvent("select", {',
        "range: { x0, x1, y0, y1 },",
        'view: this._eventView("select"),',
        'if (this._interactionFlag("select", true)) {',
        'if (this.comm) this.comm.send({ type: "select_clear" });',
        'this._dispatchChartEvent("select", { total: 0, view: this._eventView("select_clear") });',
        'this._dispatchChartEvent("view_change", detail);',
        'this.comm.send({ type: "view_change", ...detail });',
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} changed interaction event payload marker {marker!r}"
        assert text.count('if (this._interactionFlag("select", true)) {') >= 2, (
            f"{path} must gate both selection clear and kernel selection events"
        )


def test_client_exposes_first_class_mark_state_styling() -> None:
    required = (
        "this.markStyle = spec.mark_style || {};",
        "u_selectedOpacity",
        "u_unselectedOpacity",
        'this._markStateNumber("unselected", "opacity", 0.12)',
        "_drawHoverState()",
        "_drawHoverPoint(",
        "var(--chart-selection-fill",
        "var(--chart-zoom-selection-fill",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer exposes mark-state styling marker {marker!r}"


def test_client_hardens_responsive_visibility_recovery() -> None:
    required = (
        "_armVisibilityResizeWatch()",
        "_syncContainerSize()",
        'this._listen(window, "pageshow"',
        'this._listen(document, "visibilitychange"',
        "new IntersectionObserver",
        "this._io?.disconnect();",
        "const compact = this.size.w < 520;",
        "_queueResize(cssW = null, cssH = null, measure = false)",
        'this._colorbar.dataset.xyCompact = compactVertical ? "true" : "false";',
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer exposes responsive marker {marker!r}"


def test_client_quiesces_and_rebuilds_repeated_context_loss() -> None:
    required = (
        'this.root.dataset.xyContextState = "lost";',
        'this.root.dataset.xyContextState = "ready";',
        "this._contextLossCount += 1;",
        "this._contextRestoreCount += 1;",
        'this._dispatchChartEvent("context_lost"',
        'this._dispatchChartEvent("context_restored"',
        "clearTimeout(this._viewTimer);",
        "clearTimeout(this._rebinTimer);",
        "if (this._destroyed || this._glLost || !this.gl) return;",
        "if (this._destroyed || this._contextRecoveryError) return;",
        'if (this._glLost && msg.type !== "append" && msg.type !== "pick_result") return;',
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} lost context-recovery marker {marker!r}"

    smoke = (ROOT / "scripts" / "render_smoke_nonumpy.py").read_text(encoding="utf-8")
    assert "for(let cycle=0;cycle<3;cycle++)" in smoke
    assert "ctxcycles != 3" in smoke
    assert "ctxpost != 1" in smoke


def test_client_shares_context_budget_across_same_origin_frames() -> None:
    # The browser's WebGL-context cap is process-wide (shared across a tab's
    # iframes), but the governor is per-document. A chart-per-iframe page (the
    # examples/fastapi gallery) would otherwise blow the cap and flood the
    # console with "Too many active WebGL contexts". The governor coordinates a
    # single shared budget across same-origin frames over a BroadcastChannel
    # (§18); these markers guard that machinery against silent removal.
    required = (
        'new BroadcastChannel("xy-webgl-context-governor")',
        "_initCrossFrame()",
        "_onForeignMessage(",
        # The message contract peers rely on: a live-context count keyed by frame.
        '{ t: "live", id: this.frameId, n }',
        '{ t: "hello", id: this.frameId }',
        '{ t: "bye", id: this.frameId }',
        # Effective budget = own live contexts + those reported by other frames.
        "this.localLive() + this.foreignLive() - this.budget()",
        # A bfcache restore must re-advertise, or peers omit the restored frame
        # forever and the page silently exceeds the browser cap; and it must
        # discard the membership map that may have gone stale while frozen.
        'window.addEventListener("pageshow"',
        "event.persisted",
        "this.foreign.clear()",
    )
    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} lost cross-frame governor marker {marker!r}"


def test_governed_recovery_waits_for_loss_event_before_restore() -> None:
    # Chromium silently drops WEBGL_lose_context.restoreContext() if it is called
    # before that context's webglcontextlost event has dispatched (or during the
    # dispatch) — the context is then stranded lost forever. A governed release
    # that is scrolled back into view in the same task must therefore defer its
    # restore until the loss event lands and then retry on a fresh task. Without
    # this, a chart-per-iframe dashboard leaves charts permanently blank on
    # scroll-in. Guard the deferral so it cannot regress.
    for path, text in CLIENT_FILES:
        assert "this._ctxLostPending = true" in text, (
            f"{path}: release no longer marks the loss event pending"
        )
        assert "this._ctxLostPending = false" in text, (
            f"{path}: loss handler no longer clears the pending flag"
        )
        # _recoverContext defers while the loss event is still pending.
        rec = text[text.index("_recoverContext() {") :][:900]
        assert "this._ctxReleasedExt && this._ctxLostPending" in rec, (
            f"{path}: _recoverContext must defer restore until the loss event dispatched"
        )
        assert "this._ctxRecoverRequested = true" in rec, (
            f"{path}: _recoverContext must record the deferred recovery"
        )


def test_cross_frame_rebalance_only_sheds_offscreen_views() -> None:
    # Shared-budget shedding must release only OFF-screen views: a sibling frame
    # loading a chart must never blank one the user is looking at. The _rebalance
    # candidate filter therefore requires `!view._ctxVisible`. (reserve() may
    # still release a visible view as a last resort for a dense single-document
    # grid, but that is intra-document, not driven by a peer frame.)
    for path, text in CLIENT_FILES:
        start = text.index("_rebalance() {")  # the method definition, not a call site
        body = text[start : start + 700]
        assert "!view._ctxVisible" in body, (
            f"{path}: _rebalance must only shed off-screen views (missing !view._ctxVisible)"
        )
        assert "this.budget()" in body, f"{path}: _rebalance must compare against the budget"


def test_client_refreshes_and_destroys_density_sample_overlays() -> None:
    chartview_required = (
        "_refreshReductionBadges()",
        "_reductionBadgeItems()",
        "entry.sampleOverlay && entry.sampleOverlay.sample",
        "this._destroyDensitySample(g);",
    )

    for path, text in CLIENT_FILES:
        for marker in chartview_required:
            assert marker in text, f"{path} no longer maintains density sample marker {marker!r}"

    lod = (ROOT / "js/src/45_lod.ts").read_text(encoding="utf-8")
    assert 'Object.prototype.hasOwnProperty.call(d, "sample")' in lod
    assert "view._applyDensitySample(g, d.sample, buffers);" in lod


def test_client_refreshes_theme_when_framework_theme_classes_change() -> None:
    """Keep canvas paint synchronized with class-driven light/dark themes."""
    required = (
        "new MutationObserver(() => this.refreshTheme())",
        'attributeFilter: ["class", "style"]',
        "this._themeMutationObserver?.disconnect();",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} lost class-driven theme refresh {marker!r}"


def test_client_lod_layer_stays_chart_agnostic_and_renderer_delegated() -> None:
    source_lod = (ROOT / "js/src/45_lod.ts").read_text(encoding="utf-8")
    assert "trace.kind" not in source_lod
    assert "markOf(" not in source_lod

    # The intent comment is a source-only assertion — the built bundles are
    # compacted (comments stripped), so only code markers are checked there.
    assert "future heatmap/histogram tier reuses it instead of copy-pasting" in source_lod

    lod_required = (
        "function lodApplyDrill(view, g, upd, buffers)",
        "function lodApplyDensityUpdate(view, g, upd, buffers)",
        "function lodDrawDensityTier(view, g, x0, x1, y0, y1)",
        "lodRememberDensity(view, g, g.density);",
        "view._drawDensity(g, density",
        "view._drawPoints(",
        "lodDropDrill(view, g)",
    )
    for path, text in LOD_FILES:
        for marker in lod_required:
            assert marker in text, f"{path} no longer preserves shared LOD marker {marker!r}"

    chartview_required = (
        "lodDrawDensityTier(this, g",
        "markOf(g.trace.kind).draw(this, g",
        'if (upd.mode === "points") { this._applyDrill(g, upd, buffers); continue; }',
        "lodApplyDensityUpdate(this, g, upd, buffers);",
        "lodApplyDrill(this, g, upd, buffers);",
        "lodDropDrill(this, g);",
        'markOf(t.trace.kind).pointPick && (t.tier !== "density" || t.drill)',
    )
    for path, text in CLIENT_FILES:
        for marker in chartview_required:
            assert marker in text, f"{path} no longer delegates shared LOD marker {marker!r}"


def test_client_coalesces_wheel_zoom_without_animation_lag() -> None:
    required = (
        "_queueWheelZoom(factor, fx, fy, axesScope = null)",
        "this._pendingWheelZoom.factor *= factor;",
        "this._wheelZoomRaf = requestAnimationFrame",
        "this._zoomAt(pending.factor, pending.fx, pending.fy, false, 120, {",
        "this._queueWheelZoom(f, fx, fy);",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer coalesces wheel zoom marker {marker!r}"


def test_client_can_disable_navigation_without_disabling_hover() -> None:
    required = (
        'if (!this._interactionFlag("navigation", true)) return;',
        'this._listen(c, "wheel", (e) => {',
        'this._listen(c, "pointermove", (e) => {',
        "this._hover(e);",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer supports static interactive charts {marker!r}"


def test_client_heatmap_hover_rows_use_axis_display_values() -> None:
    required = (
        'const [x, xKind] = this._sourceDisplayValue(g, "x", rawX, "float");',
        'const [y, yKind] = this._sourceDisplayValue(g, "y", rawY, "float");',
        "row.x = x;",
        "row.y = y;",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer exposes heatmap display marker {marker!r}"


def test_client_point_hover_rows_use_category_display_labels() -> None:
    """Categorical tooltips expose labels instead of zero-based axis codes."""
    required = (
        'const [x, xKind] = this._sourceDisplayValue(g, "x", rawX, xMeta && xMeta.kind);',
        'const [y, yKind] = this._sourceDisplayValue(g, "y", rawY, yMeta && yMeta.kind);',
        "row.x = x;",
        "row.y = y;",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, (
                f"{path} no longer maps categorical point tooltips to display labels"
            )


def test_client_exposes_axis_style_hooks() -> None:
    required = (
        "_axisStyleNumber(axis, key, fallback)",
        "_axisStylePaint(axis, key, fallback)",
        '"grid_color"',
        '"axis_color"',
        '"tick_color"',
        '"label_color"',
        '"label_size"',
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer exposes axis styling marker {marker!r}"


def test_log_axis_uses_separate_readable_label_ticks() -> None:
    required = (
        "const labels = [];",
        "labels.push(v);",
        "return { ticks: out, labels: labels.length ? labels : out, step: 1, log: true };",
        "for (const v of (xt.labels || xt.ticks))",
        "for (const v of (yt.labels || yt.ticks))",
        "for (const v of (ticks.labels || ticks.ticks))",
    )

    for path, text in FORMATTER_FILES:
        for marker in required[:3]:
            assert marker in text, f"{path} no longer separates log tick labels"
    for path, text in CLIENT_FILES:
        for marker in required[3:]:
            assert marker in text, f"{path} no longer draws readable log tick labels"


def test_client_axis_tick_labels_have_collision_layout() -> None:
    required = (
        "_axisTickTarget(axisId, fallback)",
        "_axisTickLabelStrategy(axis)",
        "_axisTickLabelAngle(axis)",
        "_axisTickLabelAnchor(axis)",
        "_axisTickLabelMinGap(axis, dim)",
        '_tickLabelsCollide(labels, dim, fontSize, minGap, anchor = "center")',
        '_downsampleTickLabels(labels, dim, fontSize, minGap, anchor = "center")',
        "_layoutTickLabels(axis, dim, labels)",
        "tick_label_strategy",
        "tick_label_angle",
        "tick_label_anchor",
        "tick_label_min_gap",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer protects crowded axis tick labels"


def test_client_draws_first_class_annotation_markers() -> None:
    required = (
        "_annotationStrokePaint(style, fallback)",
        "_drawAnnotationMarker(ctx, x, y, style, ann)",
        'ann.kind === "marker"',
        '"circle", "square", "diamond", "cross"',
        "d.style.color = this._annotationLabelPaint(style, this.theme.label)",
        "stroke_color",
        "stroke_width",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer draws annotation marker primitives"


def test_widget_bundle_is_valid_esm_and_standalone_is_a_window_global() -> None:
    """index.js is anywidget's `_esm` (widget.py): the minified module must
    still export the full public namespace by name. standalone.js is inlined
    as a classic <script> by `Figure.to_html()`: it must be export-free and
    define a top-level `var xy` namespace (window.xy) with the same surface."""
    index_text = _read(_STATIC / "index.js")
    for alias in (
        "as render",
        "as renderStandalone",
        "as decodeFrame",
        "as ChartView",
        "as MARK_KINDS",
        "as markOf",
        "as default",
    ):
        assert alias in index_text, f"index.js no longer exports {alias.split()[-1]!r}"

    standalone_text = _read(_STATIC / "standalone.js")
    assert "export {" not in standalone_text and "export{" not in standalone_text, (
        "standalone.js must be a classic script (no ES exports)"
    )
    assert standalone_text.startswith("var xy="), (
        "standalone.js must define the window.xy namespace via a top-level var"
    )
    for prop in (
        ".render=",
        ".renderStandalone=",
        ".decodeFrame=",
        ".ChartView=",
        ".MARK_KINDS=",
        ".markOf=",
    ):
        assert prop in standalone_text, f"standalone.js namespace lost {prop!r}"


def test_annotation_labels_and_cursor_stay_css_defeatable() -> None:
    """Annotation labels (DOM) and the interaction cursor must be overridable by
    user CSS/Tailwind: the slot + font + cursor defaults live in the layered zero-
    specificity :where() stylesheet, never as inline styles that beat classes."""
    for path, text in CLIENT_FILES:
        assert '_applySlot(d, "annotation_label")' in text, (
            f"{path} annotation label carries no data-xy-slot for CSS targeting"
        )

    # Annotation label font is a stylesheet default, not inline (only the
    # position/transform structural bits and an *explicit* color stay inline).
    annotations = _read(ROOT / "js/src/51_annotations.ts")
    assert "font-size:11px;line-height:1.2;font-weight:500;" not in annotations, (
        "annotation label pins font inline; move it to the :where() stylesheet"
    )
    assert "if (style && (style.label_color || style.color)) {" in annotations
    assert '"opacity",' in annotations
    assert '"label_opacity",' in annotations
    assert 'if (key === "opacity" && ann.kind === "text") {' in annotations
    assert "if (style && style.label_opacity !== undefined) {" in annotations
    assert "d.style.opacity = String(Math.max(0, Math.min(1, labelOpacity)));" in annotations

    # Cursor is attribute-driven, never inline (inline cursor beats cursor-* utils).
    chartview = _read(ROOT / "js/src/50_chartview.ts")
    interaction = _read(ROOT / "js/src/53_interaction.ts")
    assert "cursor:" not in chartview, "canvas re-pins cursor inline"
    assert "this.canvas.style.cursor" not in interaction, "drag-mode re-pins cursor inline"
    assert "this.canvas.dataset.xyDragmode = mode;" in interaction
    assert "cursor:pointer" not in interaction, "modebar button pins cursor inline"


def test_client_renders_mark_level_styling() -> None:
    """Gradient fills (premultiplied, currentColor-aware), rounded corners +
    stroke borders on both rect-family GPU programs, and curve:"smooth"
    monotone-cubic densification are first-class mark styling
    (spec/api/styling.md#styling-the-marks)."""
    required = (
        "xyGradSample(",  # gradient sampler shared by area + rect shaders
        "u_gradMode",
        'u("u_radius")',  # rounded-corner SDF uniform
        'u("u_strokeWidth")',
        "(v_pos - v_base) / (abs(denom)",  # area gradient: per-column, seam-free + even
        "xySmoothResample(",  # monotone cubic (Fritsch–Carlson)
        "xyMonotoneTangents(",
        "xyMarkerSdf(d, u_symbol)",  # scatter symbol shapes (circle/square/diamond/triangle/cross)
        "_pointMarkStyle(",  # point stroke + symbol resolution
        "rgb = mix(rgb, sc.rgb, sc.a);",  # selected/unselected recolor (mark_style)
        "v_dash = mix(a_len0, mix(a_len0, a_len1, reveal), c.x);",  # fractional reveal preserves line dashes
        "_lineDash(g)",
        "_resolveMarkFill(",
        "_setRectStyleUniforms(",
        '=== "currentcolor"',  # currentColor resolves to the mark's own color
        'curve !== "smooth"',
    )
    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer supports mark styling marker {marker!r}"

    # Smoothing is visual-only: hover reads the source rows, so the resample
    # must never replace the retained CPU columns.
    src = _CLIENT_SRC[1]
    assert "g._cpu = { x, y, xMeta: g.xMeta, yMeta: g.yMeta };" in src
    assert "g._cpu = { x, y, base, xMeta: g.xMeta, yMeta: g.yMeta };" in src


def test_rect_gradient_preserves_per_item_alpha_stack() -> None:
    """Gradient rects compose vector opacity and artist-alpha while keeping
    the fragment output premultiplied for WebGL blending."""
    required = (
        "vec4 gradient = xyGradSample(xyGradT(v_t, u_res));",
        "(v_style.y >= 0.0 ? v_style.y : gradient.a) * v_style.x * u_opacity",
        "gradient.a > 1e-6 ? gradient.rgb / gradient.a : vec3(0.0)",
        "premult = vec4(gradientRgb * gradientAlpha, gradientAlpha);",
    )
    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} drops gradient alpha marker {marker!r}"


def test_standalone_density_rebin_worker() -> None:
    """Kernel-less pages refine density charts by re-binning the retained
    §28 sample in a bundled blob-URL worker — off the main thread, recorded
    as a badge, falling back to the stretched overview when workers are
    unavailable. The smoke proves it end-to-end under the production CSP."""
    required = (
        "XY_REBIN_WORKER_SRC",  # worker source ships inside the bundle
        "xyCreateRebinWorker(",
        "_scheduleSampleRebin(",  # standalone branch of the view-request path
        "_requestSampleRebin(",
        '"zoom re-binned from sample"',  # §28: the reduction is badged
        "this._rebinWorker.terminate();",  # lifecycle: destroy() tears it down
    )
    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} lost standalone re-bin marker {marker!r}"
    # The worker result path never touches the retained sample overlay (it is
    # the re-bin source); only the grid/texture swap.
    src = _CLIENT_SRC[1]
    assert "_applySampleRebinGrid(g" in src


def test_standalone_csp_allows_blob_workers_and_matches_smoke() -> None:
    """worker-src must be exactly blob: (the bundled re-bin worker) — no
    external worker scripts — and the render smoke must exercise the same
    policy string so its probes prove production behavior."""
    from xy.export import _STANDALONE_CSP

    assert "worker-src blob:; " in _STANDALONE_CSP
    smoke = (ROOT / "scripts" / "render_smoke_nonumpy.py").read_text(encoding="utf-8")
    assert "csp = (" in smoke, "smoke CSP block not found"
    block = smoke.split("csp = (", 1)[1].split(")", 1)[0]
    smoke_csp = "".join(part for part in block.split('"')[1::2])
    assert smoke_csp == _STANDALONE_CSP, "smoke CSP diverged from export._STANDALONE_CSP"


def test_client_supports_edge_to_edge_sparklines() -> None:
    """Dashboards need chrome-less, edge-to-edge charts: an explicit `padding`
    override collapses the label-aware margins, and tick_label_strategy="none"
    hides every tick label (not just skips collision layout)."""
    src = _CLIENT_SRC[1]
    # padding override feeds _layout's margins
    assert "Array.isArray(this.spec.padding) ? this.spec.padding : null" in src
    assert "responsivePad ? Math.min(pad[3], 46) : pad[3]" in src
    # "none" returns an empty label set even when the axis has only one tick.
    assert 'if (strategyValue === "none" || strategyValue === "off") return [];' in src
    assert "if (s.x_axis.label && !hideX)" in src
    assert "if (s.y_axis.label && !hideY)" in src
    for path, text in CLIENT_FILES:
        assert 'if (strategyValue === "none" || strategyValue === "off") return [];' in text, (
            f"{path} lost none-hides-labels"
        )


def test_client_named_axes_handle_silent_gutters_and_reversed_ticks() -> None:
    """Silent secondary chrome must not shrink the plot, and explicit ticks
    remain valid when a named scale's range is reversed."""
    required = (
        'this._axisTickLabelStrategy(axis) !== "none"',
        "const a = Math.min(lo, hi), b = Math.max(lo, hi);",
        "v >= a && v <= b",
    )
    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} lost named-axis range/layout guard {marker!r}"

        label_layout = text.split("_layoutTickLabels(axis, dim, labels)", 1)[1].split(
            "_axisLabelCss(axis, dim, fallbackCss)", 1
        )[0]
        assert label_layout.index("strategyValue") < label_layout.index("labels.length <= 1"), (
            f"{path} lets a single label bypass tick_label_strategy='none'"
        )


def test_built_bundles_keep_minification_safe_invariants() -> None:
    """Defense-in-depth on the shipped artifacts. The bundles are minified, so
    only invariants that survive minification are asserted here: string-literal
    content (the chrome stylesheet, channel names, badges) and property-name
    sinks. Everything line-level is asserted against js/src/*.ts above and
    transfers because `node js/build.mjs --check` proves the committed bundles
    are compiled from exactly that source."""
    src_inner_html = _CLIENT_SRC[1].count(".innerHTML")
    for path, text in BUNDLES:
        # Security: no HTML-parsing sinks, and no innerHTML sites beyond the
        # audited icon-injection ones counted in the source.
        for sink in _BANNED_HTML_SINKS:
            assert sink not in text, f"{path} must not use HTML sink {sink}"
        assert text.count(".innerHTML") == src_inner_html, (
            f"{path} innerHTML site count diverged from js/src (audited sites)"
        )
        # The §36 chrome contract ships intact: layered zero-specificity
        # defaults and every --chart-* token.
        assert "@layer base{" in text, f"{path} lost the layered chrome stylesheet"
        for rule in _CHROME_WHERE_RULES:
            assert rule in text, f"{path} missing defeatable chrome rule {rule!r}"
        for token in _CHROME_TOKENS:
            assert token in text, f"{path} no longer themes {token!r}"
        assert '[data-xy-slot="selection"][data-xy-band="zoom"]){' in text, (
            f"{path} is missing the defeatable zoom-band :where() default"
        )
        assert "min-width:42px" in text, path
        assert "[data-xy-modebar-select-icon]" in text, path
        # Slot stamping + cross-frame governor machinery still present.
        assert ".dataset.xySlot=" in text, f"{path} no longer stamps data-xy-slot"
        assert "xy-webgl-context-governor" in text, (
            f"{path} lost the cross-frame WebGL context governor channel"
        )
        # §28: reductions stay badged in the shipped client.
        assert "zoom re-binned from sample" in text, f"{path} lost the re-bin badge"
