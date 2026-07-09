from __future__ import annotations

from pathlib import Path

from fastcharts.components import CHART_DOM_SLOTS

ROOT = Path(__file__).resolve().parents[1]
_STATIC = ROOT / "python" / "fastcharts" / "static"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# The hand-written client is split across ordered js/src parts — 50_chartview.js
# was decomposed into 50 (core) + 51_annotations/52_tooltip/53_interaction/
# 54_kernel. Assert source-level invariants against the whole concatenation so a
# further split never silently drops a check, plus each built bundle separately.
# (label, text) pairs: the label only names the source in failure messages.
_CLIENT_SRC = (
    "js/src/*.js",
    "\n".join(_read(p) for p in sorted((ROOT / "js" / "src").glob("*.js"))),
)
_INDEX = ("static/index.js", _read(_STATIC / "index.js"))
_STANDALONE = ("static/standalone.js", _read(_STATIC / "standalone.js"))

CLIENT_FILES = (_CLIENT_SRC, _INDEX, _STANDALONE)
FORMATTER_FILES = (("js/src/30_ticks.js", _read(ROOT / "js/src/30_ticks.js")), _INDEX, _STANDALONE)
LOD_FILES = (("js/src/45_lod.js", _read(ROOT / "js/src/45_lod.js")), _INDEX, _STANDALONE)
# The chrome default stylesheet lives in the theme part; both built bundles
# concatenate it.
THEME_FILES = (("js/src/20_theme.js", _read(ROOT / "js/src/20_theme.js")), _INDEX, _STANDALONE)


def test_chrome_visual_defaults_are_a_defeatable_where_stylesheet() -> None:
    """Themeable chrome styling lives in a zero-specificity :where() stylesheet
    so user class_names / styles always win (the CSS+Tailwind contract).
    Every chrome slot's visual defaults + --chart-* token must be present, and
    the elements must carry only structural inline styles (no inline
    background/color that would beat a utility class)."""
    where_rules = (
        ':where(.fastcharts [data-fc-slot="tooltip"]){',
        ':where(.fastcharts [data-fc-slot="legend"]){',
        ':where(.fastcharts [data-fc-slot="legend_swatch"]){',
        ':where(.fastcharts [data-fc-slot="modebar"]){',
        ':where(.fastcharts [data-fc-slot="modebar_button"]){',
        ':where(.fastcharts [data-fc-slot="modebar_button"].fc-active){',
        ':where(.fastcharts [data-fc-slot="selection"]){',
        ':where(.fastcharts [data-fc-slot="badge_item"]){',
        ':where(.fastcharts [data-fc-slot="tick_label"]){',
        ':where(.fastcharts [data-fc-slot="axis_title"]){',
        ':where(.fastcharts [data-fc-slot="annotation_label"]){',
        ':where(.fastcharts [data-fc-slot="canvas"]){cursor:',
        ':where(.fastcharts [data-fc-slot="canvas"][data-fc-dragmode="pan"]){cursor:',
    )
    tokens = (
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
    for path, text in THEME_FILES:
        for rule in where_rules:
            assert rule in text, f"{path} missing defeatable chrome rule {rule!r}"
        for token in tokens:
            assert token in text, f"{path} no longer themes {token!r} in the stylesheet"
        assert "ensureChromeStylesheet" in text

    # The inline tooltip/legend/modebar cssText must not re-set themeable
    # properties (that would beat utility classes on specificity).
    chartview = (ROOT / "js/src/50_chartview.js").read_text(encoding="utf-8")
    assert "ensureChromeStylesheet(root);" in chartview
    assert "background:var(--chart-tooltip-bg" not in chartview
    # modebar active state is a class toggle, never inline (its builder now lives
    # in 53_interaction.js, so assert against the whole client source).
    assert 'btn.classList.toggle("fc-active"' in _CLIENT_SRC[1]


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

    for path, text in CLIENT_FILES:
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

    for path, text in CLIENT_FILES:
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

    for path, text in CLIENT_FILES:
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
        "legend_swatch": '_applySlot(sw, "legend_swatch")',
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
        assert "el.dataset.fcSlot = slot;" in text, f"{path} no longer stamps data-fc-slot"
        assert text.index("el.dataset.fcSlot = slot;") < text.index("const dom = this.spec.dom;"), (
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

    standalone = (ROOT / "js/src/60_entries.js").read_text(encoding="utf-8")
    generated = (ROOT / "python/fastcharts/static/standalone.js").read_text(encoding="utf-8")
    for text in (standalone, generated):
        assert "g._cpu.color = column(g.trace.color.buf);" in text
        assert "g._cpu.size = column(g.trace.size.buf);" in text


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
        "new CustomEvent(`fastcharts:${name}`",
        'this._dispatchChartEvent("click", detail);',
        'this._dispatchChartEvent("brush",',
        'this._dispatchChartEvent("select",',
        'this.comm.send({ type: "view_change", ...detail });',
        'const msg = { type: "click", trace: hit.trace, index: hit.index };',
        "new BroadcastChannel(`fastcharts:${group}`)",
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
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer exposes responsive marker {marker!r}"


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
        "_queueWheelZoom(factor, fx, fy)",
        "this._pendingWheelZoom.factor *= factor;",
        "this._wheelZoomRaf = requestAnimationFrame",
        "this._zoomAt(pending.factor, pending.fx, pending.fy, false);",
        "this._queueWheelZoom(f, fx, fy);",
    )

    for path, text in CLIENT_FILES:
        for marker in required:
            assert marker in text, f"{path} no longer coalesces wheel zoom marker {marker!r}"


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
        "_axisTickLabelMinGap(axis, dim)",
        "_tickLabelsCollide(labels, dim, fontSize, minGap)",
        "_downsampleTickLabels(labels, dim, fontSize, minGap)",
        "_layoutTickLabels(axis, dim, labels)",
        "tick_label_strategy",
        "tick_label_angle",
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


def test_widget_bundle_is_valid_esm_not_leaking_marker_prose() -> None:
    """index.js is anywidget's `_esm` (widget.py). The bundler splits 60_entries
    on `// ---- exports ----`; any text trailing that marker on its line would
    land as bare, unparseable code in the module. Guard the exact regression:
    the ESM must carry no marker prose and must tail with `export` statements."""
    index_text = _read(_STATIC / "index.js")
    assert "stripped for the IIFE build" not in index_text, (
        "index.js leaked the export-marker comment prose as bare code"
    )
    tail = [ln for ln in index_text.splitlines() if ln.strip()][-2:]
    assert all(ln.startswith("export ") for ln in tail), (
        f"index.js must end with export statements, got {tail!r}"
    )
    # The IIFE bundle is export-free (exports are illegal in a Function body).
    assert "export {" not in _read(_STATIC / "standalone.js")


def test_annotation_labels_and_cursor_stay_css_defeatable() -> None:
    """Annotation labels (DOM) and the interaction cursor must be overridable by
    user CSS/Tailwind: the slot + font + cursor defaults live in the zero-
    specificity :where() stylesheet, never as inline styles that beat classes."""
    for path, text in CLIENT_FILES:
        assert '_applySlot(d, "annotation_label")' in text, (
            f"{path} annotation label carries no data-fc-slot for CSS targeting"
        )

    # Annotation label font is a stylesheet default, not inline (only the
    # position/transform structural bits and an *explicit* color stay inline).
    annotations = _read(ROOT / "js/src/51_annotations.js")
    assert "font-size:11px;line-height:1.2;font-weight:500;" not in annotations, (
        "annotation label pins font inline; move it to the :where() stylesheet"
    )
    assert "if (style && (style.label_color || style.color)) {" in annotations

    # Cursor is attribute-driven, never inline (inline cursor beats cursor-* utils).
    chartview = _read(ROOT / "js/src/50_chartview.js")
    interaction = _read(ROOT / "js/src/53_interaction.js")
    assert "cursor:" not in chartview, "canvas re-pins cursor inline"
    assert "this.canvas.style.cursor" not in interaction, "drag-mode re-pins cursor inline"
    assert "this.canvas.dataset.fcDragmode = mode;" in interaction
    assert "cursor:pointer" not in interaction, "modebar button pins cursor inline"


def test_client_renders_mark_level_styling() -> None:
    """Gradient fills (premultiplied, currentColor-aware), rounded corners +
    stroke borders on both rect-family GPU programs, and curve:"smooth"
    monotone-cubic densification are first-class mark styling
    (docs/styling.md#styling-the-marks)."""
    required = (
        "fcGradSample(",  # gradient sampler shared by area + rect shaders
        "u_gradMode",
        'u("u_radius")',  # rounded-corner SDF uniform
        'u("u_strokeWidth")',
        "fcGradSample(fcGradT(v_t, u_res)) * u_color.a",  # opacity composes w/ gradient
        "(v_pos - v_base) / (abs(denom)",  # area gradient: per-column, seam-free + even
        "fcSmoothResample(",  # monotone cubic (Fritsch–Carlson)
        "fcMonotoneTangents(",
        "fcMarkerSdf(d, u_symbol)",  # scatter symbol shapes (circle/square/diamond/triangle/cross)
        "_pointMarkStyle(",  # point stroke + symbol resolution
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


def test_client_supports_edge_to_edge_sparklines() -> None:
    """Dashboards need chrome-less, edge-to-edge charts: an explicit `padding`
    override collapses the label-aware margins, and tick_label_strategy="none"
    hides every tick label (not just skips collision layout)."""
    src = _CLIENT_SRC[1]
    # padding override feeds _layout's margins
    assert "Array.isArray(this.spec.padding) ? this.spec.padding : null" in src
    assert "marginLeft = pad ? pad[3]" in src
    # "none" returns an empty label set (previously returned all labels unlaid-out)
    assert 'if (strategy === "none") return [];' in src
    for path, text in CLIENT_FILES:
        assert 'if (strategy === "none") return [];' in text, f"{path} lost none-hides-labels"
