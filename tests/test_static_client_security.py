from __future__ import annotations

from pathlib import Path

from fastcharts.components import CHART_DOM_SLOTS

ROOT = Path(__file__).resolve().parents[1]
CLIENT_FILES = (
    ROOT / "js/src/50_chartview.js",
    ROOT / "python/fastcharts/static/index.js",
    ROOT / "python/fastcharts/static/standalone.js",
)
FORMATTER_FILES = (
    ROOT / "js/src/30_ticks.js",
    ROOT / "python/fastcharts/static/index.js",
    ROOT / "python/fastcharts/static/standalone.js",
)
LOD_FILES = (
    ROOT / "js/src/45_lod.js",
    ROOT / "python/fastcharts/static/index.js",
    ROOT / "python/fastcharts/static/standalone.js",
)


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


def test_client_respects_user_legend_max_height_style() -> None:
    """The responsive legend cap must not overwrite explicit component styles."""
    required_guards = (
        'this._slotStyleValue("legend", "max-height") == null',
        'this._slotStyleValue("legend", "maxHeight") == null',
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for guard in required_guards:
            assert guard in text, f"{path} no longer preserves explicit legend max-height"


def test_client_numeric_styles_default_to_pixels_for_lengths() -> None:
    """Numeric component styles should behave like common Python/React style APIs."""
    required_style_helpers = (
        "const UNITLESS_STYLE_PROPS = new Set([",
        'if (key.startsWith("--")) return key;',
        'if (property.startsWith("--") || UNITLESS_STYLE_PROPS.has(property)) return String(value);',
        "return `${value}px`;",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for helper in required_style_helpers:
            assert helper in text, f"{path} no longer normalizes numeric component styles"


def test_client_applies_every_public_dom_slot() -> None:
    slot_snippets = {
        "root": '_applySlot(root, "root")',
        "title": '_applySlot(t, "title")',
        "chrome": '_applySlot(this.chrome, "chrome")',
        "canvas": '_applySlot(this.canvas, "canvas")',
        "labels": '_applySlot(this.labels, "labels")',
        "legend": '_applySlot(lg, "legend")',
        "legend_item": '_applySlot(row, "legend_item")',
        "tooltip": '_applySlot(this.tooltip, "tooltip")',
        "modebar": '_applySlot(bar, "modebar")',
        "modebar_button": '_applySlot(b, "modebar_button")',
        "selection": '_applySlot(this.selRect, "selection")',
        "crosshair_x": '_applySlot(this.crosshairX, "crosshair_x")',
        "crosshair_y": '_applySlot(this.crosshairY, "crosshair_y")',
        "badge": '_applySlot(box, "badge")',
        "badge_item": '_applySlot(badge, "badge_item")',
    }
    assert tuple(slot_snippets) == CHART_DOM_SLOTS

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for slot, snippet in slot_snippets.items():
            assert snippet in text, f"{path} does not apply public DOM slot {slot!r}"


def test_client_stamps_public_dom_slot_attributes() -> None:
    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        assert "el.dataset.fcSlot = slot;" in text
        assert text.index("el.dataset.fcSlot = slot;") < text.index("const dom = this.spec.dom;")


def test_standalone_tooltips_retain_encoded_color_and_size_channels() -> None:
    """Static HTML hovers should expose the same tooltip fields as widget hovers."""
    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        assert "this._lastRow = row;" in text
        assert "row.color_category = String(color.categories[code]);" in text
        assert (
            "row.color_value = this._denormalizeUnit(cpu.color[hit.index], color.domain);" in text
        )
        assert "row.size_value = this._denormalizeUnit(cpu.size[hit.index], size.domain);" in text

    standalone = (ROOT / "js/src/60_entries.js").read_text(encoding="utf-8")
    generated = (ROOT / "python/fastcharts/static/standalone.js").read_text(encoding="utf-8")
    for text in (standalone, generated):
        assert "g._cpu.color = column(g.trace.color.buf);" in text
        assert "g._cpu.size = column(g.trace.size.buf);" in text


def test_client_tooltip_value_formatter_preserves_strings() -> None:
    for path in FORMATTER_FILES:
        text = path.read_text(encoding="utf-8")
        assert 'if (typeof v === "string") return v;' in text
        assert "if (!Number.isFinite(n)) return String(v);" in text


def test_client_can_suppress_builtin_tooltip_for_framework_chrome() -> None:
    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        assert "this.spec.show_tooltip === false" in text


def test_client_exposes_first_class_interaction_events() -> None:
    required = (
        "this.interaction = spec.interaction || {};",
        "new CustomEvent(`fastcharts:${name}`",
        'this._dispatchChartEvent("click", detail);',
        'this._dispatchChartEvent("brush",',
        'this._dispatchChartEvent("select",',
        'this.comm.send({ type: "view_change", ...detail });',
        'const msg = { type: "click", trace: hit.trace, index: hit.index };',
        "new BroadcastChannel(`fastcharts:${group}`)",
        "var(--chart-crosshair",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
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
        'this._dispatchChartEvent("leave", { view: this._eventView("leave") });',
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
        'this._dispatchChartEvent("view_change", detail);',
        'this.comm.send({ type: "view_change", ...detail });',
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path} changed interaction event payload marker {marker!r}"


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

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
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
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path} no longer exposes responsive marker {marker!r}"


def test_client_refreshes_and_destroys_density_sample_overlays() -> None:
    chartview_required = (
        "_refreshReductionBadges()",
        "_reductionBadgeItems()",
        "entry.sampleOverlay && entry.sampleOverlay.sample",
        "this._destroyDensitySample(g);",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in chartview_required:
            assert marker in text, f"{path} no longer maintains density sample marker {marker!r}"

    lod_files = (
        ROOT / "js/src/45_lod.js",
        ROOT / "python/fastcharts/static/index.js",
        ROOT / "python/fastcharts/static/standalone.js",
    )
    for path in lod_files:
        text = path.read_text(encoding="utf-8")
        assert "view._applyDensitySample(g, d.sample, buffers);" in text


def test_client_lod_layer_stays_chart_agnostic_and_renderer_delegated() -> None:
    source_lod = (ROOT / "js/src/45_lod.js").read_text(encoding="utf-8")
    assert "trace.kind" not in source_lod
    assert "markOf(" not in source_lod

    lod_required = (
        "future heatmap/histogram tier reuses it instead of copy-pasting",
        "function lodApplyDrill(view, g, upd, buffers)",
        "function lodApplyDensityUpdate(view, g, upd, buffers)",
        "function lodDrawDensityTier(view, g, x0, x1, y0, y1)",
        "lodRememberDensity(view, g, g.density);",
        "view._drawDensity(g, density",
        "view._drawPoints(",
        "lodDropDrill(view, g)",
    )
    for path in LOD_FILES:
        text = path.read_text(encoding="utf-8")
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
    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in chartview_required:
            assert marker in text, f"{path} no longer delegates shared LOD marker {marker!r}"


def test_client_coalesces_wheel_zoom_without_animation_lag() -> None:
    required = (
        "_queueWheelZoom(factor, fx, fy)",
        "this._pendingWheelZoom.factor *= factor;",
        "this._wheelZoomRaf = requestAnimationFrame",
        "this._zoomAt(pending.factor, pending.fx, pending.fy, false);",
        "this._queueWheelZoom(f, fx, fy);",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path} no longer coalesces wheel zoom marker {marker!r}"


def test_client_heatmap_hover_rows_use_axis_display_values() -> None:
    required = (
        'const [x, xKind] = this._sourceDisplayValue(g, "x", rawX, "float");',
        'const [y, yKind] = this._sourceDisplayValue(g, "y", rawY, "float");',
        "row.x = x;",
        "row.y = y;",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path} no longer exposes heatmap display marker {marker!r}"


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

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
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

    for path in FORMATTER_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required[:3]:
            assert marker in text, f"{path} no longer separates log tick labels"
    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required[3:]:
            assert marker in text, f"{path} no longer draws readable log tick labels"


def test_client_axis_tick_labels_have_collision_layout() -> None:
    required = (
        "_axisTickTarget(axisId, fallback)",
        "_axisTickLabelStrategy(axis)",
        "_axisTickLabelAngle(axis)",
        "_axisTickLabelMinGap(axis, dim)",
        "_tickLabelsCollide(labels, dim, fontSize, minGap)",
        "_downsampleTickLabels(labels, dim, fontSize, minGap)",
        "_layoutTickLabels(axis, dim, labels)",
        "tick_label_strategy",
        "tick_label_angle",
        "tick_label_min_gap",
    )

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
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

    for path in CLIENT_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in required:
            assert marker in text, f"{path} no longer draws annotation marker primitives"
