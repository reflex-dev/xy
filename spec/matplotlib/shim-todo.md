# `xy.pyplot` compatibility audit and TODO

This document began as the audit of xy's dependency-free 2-D pyplot shim. That
native implementation remains supported and performance-oriented, but it is no
longer the architecture for full Matplotlib compatibility. Statements and
appendices from the 2026-07-13 audit describe `native` mode unless a section
explicitly says otherwise.

## Current dual-mode architecture and completion bar

| Mode | Responsibility |
|---|---|
| `native` | Dependency-free XY-owned Figure/Axes/Artist-shaped objects and high-performance 2-D rendering. Select it explicitly to pin the lightweight implementation. |
| `compat` | Genuine Matplotlib 3.11 Figure/Axes/Artist, units, transforms, layout, toolkits, widgets, animation, and `mplot3d` semantics rendered through `module://xy.backends.backend_xy`. Install with `pip install "xy[matplotlib]"`. |
| `auto` | The configured default. It resolves to `compat` when supported Matplotlib 3.11 is installed and to `native` otherwise. |

Compat mode does not reproduce Matplotlib's semantic systems inside the native
shim. Matplotlib performs its normal Artist traversal; `RendererXY` emits one
ordered, device-space display list consumed by browser, HTML, SVG, and native
raster output. Gallery acceptance requires `fallback_used=false`: Agg and
other Matplotlib renderers may be development oracles but may not fill an
unsupported command.

The permanent Matplotlib 3.11.0 dataset contains 507 sources:

| Classification | Count |
|---|---:|
| Standard pyplot profile | 472 |
| Extended pyplot profile | 13 |
| Non-pyplot backend/font/server/GUI sources | 22 |

The first two rows are the 485 pyplot-eligible import-swap denominator. The 22
other sources remain represented and classified, but cannot be pyplot passes
or failures.

Completion requires both pyplot profiles to pass execution, figure/capture,
dimension, structure, semantic, tolerant visual, interaction/animation, and
no-fallback gates without waivers. Exact pixels are explicitly not required.
The completed report passes 472/472 standard and 13/13 extended examples:
485/485 pyplot-eligible cases with no execution, structural, semantic, visual,
behavioral, or fallback waivers. The checked-in 189 execution / 172
figure-capture / 168 exact-dimension / 127 visual bootstrap baseline and its
former waivers remain historical ratchet evidence, not the current result.

The active contracts are:

- [`modes.md`](modes.md) for mode resolution and switching;
- [`backend-xy.md`](backend-xy.md) for the renderer/display-list boundary;
- [`gallery-contract.md`](gallery-contract.md) for provenance, environment,
  behavioral evidence, and acceptance thresholds;
- [`live-canvas.md`](live-canvas.md) for browser-to-Matplotlib events; and
- [`non-pyplot-companions.md`](non-pyplot-companions.md) for the 22 classified
  sources.

## Historical native reference point and audit method

- Audit date: 2026-07-13.
- Upstream checkout: `ignore/matplotlib`.
- Upstream revision: `bde111fb4e`, described by Git as
  `v3.11.0-348-gbde111fb4e` (2026-07-10).
- Native shim: `python/xy/pyplot/`.
- Contract test: `tests/pyplot/test_axes_charts.py::`
  `test_official_matplotlib_311_2d_plotting_surface_is_complete`.
- Executable examples: `tests/pyplot/corpus/`.

Name-level comparisons below were made from public top-level functions in
upstream `matplotlib/pyplot.py`, and public declarations on upstream `Axes`,
`_AxesBase`, `Figure`, and `FigureBase`. They are useful breadth indicators,
not semantic compatibility scores: renderer lifecycle methods, properties,
and APIs deliberately outside xy's design are included in the upstream sets.

## Historical native audit baseline (before 2026-07-13 work)

| Surface | Present in `xy.pyplot` | Notes |
|---|---:|---|
| Declared Matplotlib 3.11 2-D plotting-method contract | 66 / 66 (100%) | Name presence on both `Axes` and stateful `pyplot` |
| Public upstream `pyplot` functions | 92 / 165 (56%) | 73 names absent; see appendix A |
| Public upstream `Axes`/`_AxesBase` declarations | 89 / 193 (46%) | 104 names absent; see appendix B |
| Public upstream `Figure`/`FigureBase` declarations | 13 / 73 (18%) | 60 names absent; see appendix C |
| Compatibility corpus | 53 scripts | No expected failures |
| 2026-07-13 shim suite | 157 passed, 7 skipped | Skips required real Matplotlib |

The 66/66 statement is intentionally narrow and historical. It means every method in
the selected Matplotlib 3.11 2-D **Plotting** inventory exists. It does not mean
that every keyword, returned Artist, transform, layout rule, backend feature,
or rendered pixel matches Matplotlib, and it must not be used as the headline
for compat mode.

## Historical native completion record

The native audit was closed on 2026-07-13. In the option-depth and
interoperability sections, a
checked item means each listed material behavior is now either implemented or
rejected through the documented, actionable `NotImplementedError` boundary;
it does not prove the later 485-example compat contract.

The evidence below remains useful for native-mode regressions. The permanent
gallery contract supersedes it as the full compat release gate:

- `tests/pyplot/test_reference_corpus.py` runs all 54 corpus scripts through
  both engines in isolated subprocesses. Each engine must emit a nonblank PNG;
  normalized ink density and rendered bounding-box geometry are compared.
  The dedicated CI job installs the released `matplotlib==3.11.0` wheel.
- `test_reference_semantics.py` compares xy against Matplotlib for line
  data/colors/color-cycle, bar geometry, histogram counts/edges (including
  density/cumulative/stacked/weights), image extent/origin/clim, and axis
  domains, contour levels, triangular topology, vector direction, masked
  scatter arrays, RGBA images, and removable collection handles.
- The PNG comparisons in the same file are coarse structural smoke checks
  (aspect-preserving normalized-mask IoU, a 2x ink-area band, and a 0.20 luma
  band), plus negative controls proving blank and wrong geometry fail.
- `test_silent_drop_regressions.py` mechanically scans every public adapter:
  bare option pops and deleted signature parameters fail unless an explicit
  `compat-noop:` rationale is attached. Corpus coverage only credits calls on
  proven pyplot/Axes receivers, so unrelated `anything.fill()` calls cannot
  satisfy the inventory.
- `test_p3_option_contracts.py`, `test_silent_drop_regressions.py`,
  `test_artist_transform_contracts.py`, `test_rc_chrome_contracts.py`, and
  `test_rc_color_export_contracts.py` cover implemented-or-rejected option
  depth and the dependency-free Artist/transform, rc/style/color, and export
  boundaries. PNG now consumes the axes background token; subplot PNG/SVG/HTML
  composition consumes figure backgrounds and styled suptitles.
- `.github/workflows/ci.yml` for the pinned Matplotlib job, and
  `scripts/sync_matplotlib_compat.py` for snapshot/matrix freshness.

Final local verification (2026-07-13, after the evidence/export pass):
`386 passed` in `tests/pyplot` and `1562 passed` across the full suite, with
Matplotlib 3.11.0 installed so the dual-engine reference slice executed rather
than skipping. Ruff check/format, `ty check` (two pre-existing diagnostics in
`xy/columns.py`, zero in the shim), workflow verification, snapshot/matrix
freshness, pre-commit hooks, `git diff --check`, and `node js/build.mjs`
idempotency all passed.

## Historical definition of done for native 2-D mode

The native shim can be called complete for its documented ordinary 2-D
surface when:

- [x] Every documented supported call has geometry and return-value tests, not
      only an `hasattr` check.
- [x] The same compatibility corpus runs against xy and the pinned Matplotlib
      reference in CI.
- [x] Material data, limits, bins, levels, labels, container shapes, and image
      dimensions are compared with Matplotlib where exact parity is intended.
- [x] A representative visual suite performs perceptual/difference checks,
      with explicit tolerances for the different renderer.
- [x] No material keyword is silently discarded. It is implemented,
      documented as an approximation, or rejected with a helpful error.
- [x] The common state, axes, figure, and mutation APIs listed in the P1/P2
      sections below work without installing Matplotlib.
- [x] Optional support for real Matplotlib objects is tested in a dedicated CI
      environment.
- [x] Public compatibility boundaries and intentional exclusions are current
      in both this document and `spec/matplotlib/compat.md`.

## P0 — make the compatibility claim measurable

- [x] Add a CI job with the pinned/reference-compatible Matplotlib installed so
      the seven skipped tests in `test_launch_compat.py` always run.
- [x] Run every corpus script through both `xy.pyplot` and
      `matplotlib.pyplot`; isolate process-global pyplot state between cases.
      Scope: asserts crash-free execution per engine; outputs are not diffed.
- [x] Record and compare semantic oracles per chart family. Cross-engine
      oracles exist for the line, bar, histogram, image, and axis-domain
      bullets; the contour/triangulation, vector-field, scatter-array, mask,
      and removable-handle bullets are covered by xy-internal contract tests
      only and remain open as reference-comparison work:
  - line/scatter data, masks, colors, sizes, and default color-cycle movement;
  - bar rectangles, category positions, stacking bases, and labels;
  - histogram counts, edges, density, cumulative and stacked outputs;
  - image extents, origin, normalization domain and RGBA behavior;
  - contour levels and paths; triangular topology and mesh bounds;
  - vector endpoints, streamline seeds, colors and widths;
  - returned tuples, containers, collections, texts and removable handles;
  - axis domains, reversed axes, ticks, labels and shared-axis behavior.
- [x] Add representative Matplotlib-versus-xy PNG comparisons. Scope: three
      coarse structural smoke checks (dilated-mask IoU, ink ratio, luma bands)
      that catch blank/grossly-wrong renders; they are not perceptual parity.
- [x] Turn the hard-coded 66-name inventory into a generated, reviewed snapshot
      from the pinned upstream documentation/source so upstream additions are
      visible as a deliberate snapshot diff.
- [x] Add coverage for every supported method, not just every broad family.
- [x] Add a guard against accepted-and-discarded material keyword values.
      Scope: pins the five keywords in `compatibility.json`; it does not
      mechanically detect new discards. The former known discards are now
      rejected loudly (`test_p3_option_contracts.py`,
      `test_silent_drop_regressions.py`).
- [x] Publish the compatibility matrix from test metadata so documentation
      cannot drift from executable coverage.

## P1 — correctness gaps inside the advertised surface

### Remove accidental dependency on installed Matplotlib

- [x] Make `Axes.get_position()` return an xy-owned lightweight bbox instead of
      dynamically importing `matplotlib.transforms.Bbox`. Evidence: `Axes.get_position()`
      now returns the shim `Bbox`, and `test_axes_layout.py` blocks Matplotlib imports.
- [x] Provide dependency-free behavior for transformed images, collections,
      normalization and streamplot paths, or clearly separate optional
      Matplotlib-object interop from the dependency-free shim.
- [x] Test every public method in an environment where importing `matplotlib`
      fails; calling an advertised method must not accidentally require it.
- [x] Keep the existing lightweight-import boundary: importing `xy.pyplot`
      must not load Matplotlib, the widget stack, or browser machinery.

### Implement or reject current no-ops

- [x] Implement meaningful `tight_layout()` behavior or document it as an
      accepted compatibility no-op with a tested layout guarantee. Evidence:
      `tests/pyplot/test_layout_noops.py::test_tight_layout_records_validated_noop_contract`
      records the accepted no-op layout contract and rejects unknown kwargs.
- [x] Implement `subplots_adjust()` parameters (`left`, `right`, `top`,
      `bottom`, `wspace`, `hspace`) for HTML, PNG, and SVG grids. Evidence:
      `tests/pyplot/test_layout_noops.py::test_subplots_adjust_records_supported_spacing_values`
      verifies the adjusted SubplotParams frame resolves to per-cell figure
      rectangles (and rejects unknown kwargs and out-of-order frames);
      `tests/pyplot/test_layout_text_parity_fixes.py::test_subplots_adjust_positions_grid_panels_in_every_exporter`
      verifies HTML/PNG/SVG all position the adjusted panels.
- [x] Implement `Figure.autofmt_xdate()` label rotation/alignment. Evidence:
      `tests/pyplot/test_layout_noops.py::test_autofmt_xdate_rotates_x_tick_labels_on_all_axes`
      verifies rotation and horizontal alignment state on every axes.
- [x] Implement `Axes.margins()` and make it affect automatic domains. Evidence:
      automatic x/y domains expand by configured margins while explicit limits remain fixed;
      `tests/pyplot/test_gallery_auto_ticks_compat.py` covers the axis-specific
      setters and Matplotlib's `axes.autolimit_mode="round_numbers"` gallery.
- [x] Implement `Axes.set_position()` and preserve the requested figure rect. Evidence:
      `set_position([left, bottom, width, height])` updates `get_position().bounds` and
      `_figure_rect`.
- [x] Make `Axes.get_position()` grid-aware and render the axes frame on the
      rectangle it reports. Evidence: `tests/pyplot/test_frame_geometry.py`
      pins reported-vs-rendered agreement for single axes and for every panel of
      2x2/1x3/5x5/8x8 grids (including `subplots_adjust` frames and width
      ratios), distinguishes original and active aspect-adjusted positions,
      preserves cell identity after an axes is removed, and checks a dense grid
      composites all 64 panels instead of only its last column.
- [x] Implement `Axes.set_anchor()` or reject unsupported anchor modes. Evidence:
      Matplotlib compass anchors are stored and unsupported modes raise `ValueError`.
- [x] Finish `axis("equal")`, `axis("scaled")`, `axis("tight")`, and related
      aspect/domain behavior instead of merely accepting policy names. Evidence:
      `axis("tight")` pins data domains and `axis("equal")` applies equal-aspect
      domain expansion during chart materialization.
- [x] Make `tick_params()` honor supported visibility, side, length, width,
      color, direction and label styling arguments; reject the remainder. Evidence:
      supported tick style/visibility values reach axis props and unsupported kwargs fail loudly.
- [x] Make `grid(which=..., axis=..., **style)` select and style the requested
      grid rather than toggling the entire chart. Evidence:
      `tests/pyplot/test_grid_legend_contracts.py::test_grid_selects_axis_and_records_supported_style`
      verifies axis selection, supported grid styling, and loud rejection of unsupported axes/which/kwargs.
- [x] Make `legend()` honor supported font/label/title/frame placement options;
      explicitly reject options that cannot map to the xy legend. Evidence:
      `tests/pyplot/test_grid_legend_contracts.py::test_legend_maps_supported_style_and_rejects_unknown_options`
      and `test_legend_frameoff_maps_to_transparent_style` verify placement, columns, title metadata,
      font/label/frame styling, and loud rejection of unsupported options.
- [x] Make `set_xlabel()`, `set_ylabel()`, `set_title()`, and `suptitle()` honor
      supported font, position and padding arguments. Evidence:
      `tests/pyplot/test_axes_layout.py` covers axis label kwargs, and
      `tests/pyplot/test_layout_noops.py::test_suptitle_accepts_supported_font_kwargs_and_rejects_unknown`
      verifies supported `suptitle()` kwargs are accepted while unknown kwargs fail loudly.
- [x] Make `Axes.set(**kwargs)` reject unknown setters instead of silently
      skipping them. Evidence: known setters apply, then unknown property names raise
      `AttributeError` with the unsupported names.

### Stop dropping visible artist/style mutations

- [x] Implement `set_markerfacecolor`, `set_markeredgecolor`, and
      `set_markersize` on compatible handles.
      Evidence: `PYTHONPATH=python .venv/bin/python -m pytest -q
      tests/pyplot/test_artist_mutations.py tests/pyplot/test_axes_charts.py::test_artist_set_ydata_rebuilds
      tests/pyplot/test_axes_charts.py::test_step_artist_set_ydata_updates_materialized_mark`
      passed on 2026-07-13.
- [x] Implement or loudly reject dash/solid cap styles and `set_gapcolor`. Evidence: `tests/pyplot/test_visible_style_contracts.py::test_line_cap_and_gapcolor_mutations_fail_loudly` verifies these unsupported visible mutations raise `NotImplementedError` instead of being ignored.
- [x] Support `set_xdata`/`set_ydata` for segment-backed line handles where the
      original logical data can be retained.
      Evidence: `PYTHONPATH=python .venv/bin/python -m pytest -q
      tests/pyplot/test_artist_mutations.py tests/pyplot/test_axes_charts.py::test_artist_set_ydata_rebuilds
      tests/pyplot/test_axes_charts.py::test_step_artist_set_ydata_updates_materialized_mark`
      passed on 2026-07-13.
- [x] Preserve annotation `arrowprops`, bbox, alignment, rotation, family and
      weight instead of reducing annotations to plain text. Evidence:
      `tests/pyplot/test_visible_style_contracts.py::test_annotate_preserves_arrow_bbox_alignment_rotation_and_font_style`
      verifies these values are retained on the returned text spec.
- [x] Preserve text vertical alignment, font weight/family and rotation. Evidence: `tests/pyplot/test_visible_style_contracts.py::test_text_preserves_visible_font_alignment_and_rotation_style` verifies style retention on text entries.
- [x] Implement bar `align="edge"`; do not approximate it as centered. Evidence: `tests/pyplot/test_visible_style_contracts.py::test_bar_align_edge_uses_edge_geometry_instead_of_center_approximation` verifies edge-to-center geometry conversion and rejects nonnumeric edge positions.
- [x] Audit marker fill styles, custom marker paths, join styles, clipping,
      hatches, z-order and transforms across all returned handles.

## P2 — common pyplot/Axes/Figure workflow compatibility

This was the native audit's 2026-07-13 prioritization: common workflow helpers
were implemented before the later compat backend project because they appear
frequently in ordinary scripts and notebooks.

### Stateful pyplot and figure management

- [x] `plt.clf()` and `Figure.clear()`/`Figure.clf()`. Evidence: `tests/pyplot/test_pyplot_state_management.py::test_pyplot_cla_and_clf_clear_current_scope` and `tests/pyplot/test_figure_state.py::test_figure_clear_and_clf_reset_axes`.
- [x] `plt.cla()` and `Axes.clear()`/`Axes.cla()`. Evidence: `tests/pyplot/test_pyplot_state_management.py::test_pyplot_cla_and_clf_clear_current_scope` clears only the current axes entries.
- [x] `plt.axes()` and `plt.delaxes()`/`Figure.delaxes()`. Evidence: `tests/pyplot/test_pyplot_state_management.py::test_pyplot_axes_delaxes_figtext_and_figlegend` covers absolute axes creation and deletion.
- [x] `plt.fignum_exists()`, `get_fignums()`, and `get_figlabels()`. Evidence: `tests/pyplot/test_pyplot_state_management.py::test_pyplot_figure_registry_and_labels` covers numeric and labeled figures.
- [x] `plt.figtext()`/`Figure.text()` and `plt.figlegend()`/`Figure.legend()`. Evidence: `tests/pyplot/test_pyplot_state_management.py::test_pyplot_axes_delaxes_figtext_and_figlegend` checks figure-fraction text and figure legend activation.
- [x] `plt.twiny()` and `Axes.twiny()`. Evidence: `tests/pyplot/test_pyplot_state_management.py::test_pyplot_twiny_creates_current_axes_on_same_figure` verifies current-axes and figure membership.
- [x] `Figure.sca()` and consistent current-Axes behavior after deletion. Evidence:
      `tests/pyplot/test_figure_state.py::test_figure_sca_and_delaxes_keep_current_axes_consistent`.
- [x] Figure getters/setters for DPI, face/edge color and size. Evidence:
      `tests/pyplot/test_figure_state.py::test_figure_size_dpi_and_color_getters_setters`.
- [x] `Figure.supxlabel()` and `Figure.supylabel()`. Evidence:
      `tests/pyplot/test_figure_state.py::test_figure_text_legend_and_super_labels_use_figure_transform`.
- [x] `Figure.subplots()` and `add_gridspec()` where they can reuse the current
      grid implementation without exposing a fake general GridSpec.
      Evidence: `tests/pyplot/test_figure_state.py::test_figure_subplots_sharing_ratios_and_squeeze`
      and `tests/pyplot/test_figure_state.py::test_add_gridspec_supports_single_cell_specs`.

### Limits, autoscaling, ticks and axes helpers

- [x] `plt.autoscale()`, `Axes.autoscale()`, `autoscale_view()`, and `relim()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_autoscale_bounds_and_relim_helpers` verifies explicit bounds, relim, autoscale, and tight autoscale behavior.
- [x] `get/set_xbound`, `get/set_ybound`, x/y margins, and sticky-edge behavior. Evidence: `tests/pyplot/test_axes_helpers.py::test_autoscale_bounds_and_relim_helpers` verifies bound setters/getters and margin-aware automatic domains. Sticky edges are derived from the entry list rather than from artist metadata (`Axes._entry_sticky_edges`): rectangle baselines for bar/histogram/contour, the outer cell edge for mesh and image entries (`imshow`/`pcolormesh`/`hist2d`/`specgram`), and 0/1 for `ecdf`. An axis whose sticky edges pin *both* ends ships a materialized `domain` instead of a `margin` (`Axes._fully_sticky_domain`), which is how a mesh stays flush with its outer cell edge; one-sided baselines still ship a `margin` and are anchored by the engine. Evidence: `tests/pyplot/test_mesh_autoscale_regressions.py`.
- [x] `ticklabel_format()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies stored style, scientific limits, and offset policy.
- [x] `minorticks_on()` and `minorticks_off()` with an explicit minor-tick model. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies explicit minor tick state toggles.
- [x] `get_xlabel`, `get_ylabel`, `get_title`, `get_xaxis`, and `get_yaxis`. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies label/title getters and axis proxy identity.
- [x] `get_legend()` and `get_legend_handles_labels()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies legend presence and labeled handles.
- [x] `set_prop_cycle()` beyond the fixed default color sequence. Evidence: `tests/pyplot/test_axes_helpers.py::test_prop_cycle_setp_getp_rc_context_and_colormap_helpers` verifies per-Axes color cycle order.
- [x] `secondary_xaxis()` and `secondary_yaxis()`, promoted into supported scope
      as tick-only linked axes. Both return a `SecondaryAxis` built from
      `location` (`"top"`/`"bottom"`, `"left"`/`"right"`) and a `functions`
      forward/inverse pair; only `transform=` raises `NotImplementedError`.
      Evidence: `tests/pyplot/test_axes_helpers.py::test_subplot2grid_box_and_secondary_axes_contract`
      calls both helpers, labels the returned objects, and asserts the built
      chart carries `axis_options["xs1"]["side"] == "top"` and
      `axis_options["ys2"]["side"] == "right"`.

### Image, property and convenience helpers

- [x] `imread()` and `imsave()` for common PNG/JPEG inputs and outputs. Evidence: `tests/pyplot/test_axes_helpers.py::test_imread_imsave_png_roundtrip_and_jpeg_exclusion` verifies dependency-free PNG RGBA round-trip and documents JPEG as an explicit unsupported format rather than a silent fallback.
- [x] `setp()`, `getp()`, `get()`, and a deliberately bounded `findobj()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_prop_cycle_setp_getp_rc_context_and_colormap_helpers` verifies property mutation and getters; `findobj()` is bounded to figures/axes/known artists.
- [x] `rc_context()` and `rcdefaults()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_prop_cycle_setp_getp_rc_context_and_colormap_helpers` verifies scoped rc restoration and test teardown uses `rcdefaults()`.
- [x] Named colormap convenience functions such as `viridis()`, `plasma()`,
      `gray()`, and `set_cmap()` if gallery compatibility justifies them. Evidence:
      `tests/pyplot/test_axes_helpers.py::test_prop_cycle_setp_getp_rc_context_and_colormap_helpers`
      verifies returned colormap carriers and `rcParams["image.cmap"]` mutation.
- [x] `subplot2grid()` as a wrapper over the supported grid model. Evidence: `tests/pyplot/test_axes_helpers.py::test_subplot2grid_box_and_secondary_axes_contract` verifies single-cell mapping and rejects spans.
- [x] `box()` and `axes()` convenience behavior. Evidence: `tests/pyplot/test_axes_helpers.py::test_subplot2grid_box_and_secondary_axes_contract` verifies `box(False)` state, and `tests/pyplot/test_pyplot_state_management.py::test_pyplot_axes_delaxes_figtext_and_figlegend` verifies `plt.axes()` absolute axes creation.

## P3 — plotting-method option depth

The following values are currently unsupported, approximated, or consumed and
discarded in at least one shim path. For each item, implement the semantics or
reject it clearly; do not claim keyword-level compatibility merely because the
method accepts the call.

### Lines, points, rules and fills

- [x] `plot`: `scalex`, `scaley`, marker face/edge styling, fillstyle, cap/join
      styles, `markevery`, general transforms and all draw styles.
- [x] `scatter`: exact `vmin`/`vmax`/norm interaction, linewidth/stroke arrays,
      custom marker paths and full nonfinite color handling.
- [x] `hlines`/`vlines`: linestyles, collection semantics, transforms and
      per-segment styles.
- [x] `fill`/`fill_between`/`fill_betweenx`: edge rendering, interpolation at
      mask crossings, transforms and complete step semantics.
- [x] `arrow`/`axline`: head shape/overhang, transforms and style fidelity.
- [x] `axhline`/`axvline`/spans: linestyles and transform fidelity.
- [x] `errorbar`: upper/lower limit flags, cap thickness, bars-above ordering,
      independent line styles, errorevery and full container semantics.

### Bars, histograms and distributions

- [x] `bar`/`barh`: edge alignment, heterogeneous widths, complete x/y error
      styling, hatch, log mode and unit-aware/category behavior.
- [x] `bar_label`: label type, custom callable formatting, padding/font
      properties and complete horizontal/negative-bar placement.
- [x] `hist`: every histtype, heterogeneous bins, rwidth, log mode, bottom
      arrays and exact returned patches.
- [x] `hist2d` linear and logarithmic normalization through the shared
      pseudocolor-mesh path, including an opaque default and retained count
      domains for logarithmic mappables.
- [ ] `hist2d` arbitrary custom normalization and `colorizer` support.
- [x] `hexbin(C=..., reduce_C_function=...)`, `mincnt`, marginals, norm,
      colorizer and explicit vmin/vmax.
- [x] `boxplot`: notches, custom whiskers, bootstrap, user medians, confidence
      intervals, cap visibility/width, autorange and component properties.
- [x] `bxp`: component styles, statistics labels/ticks, cap widths, scalar or
      per-box legend labels, and mutable filled patch boxes.
- [x] `violinplot`/`violin`: bandwidth methods, quantiles, side, extrema,
      points, cycling face/line colors, color-alpha pairs and mutable body
      styling.
- [x] `ecdf`: exact weights/complementary/orientation/compression behavior and
      returned Artist parity.

### Images, meshes and contours

- [x] `imshow`: interpolation modes/stages, transforms, clipping, alpha arrays,
      filter radius, resampling, colorizer and norm variants without requiring
      Matplotlib.
- [x] `pcolor`, `pcolorfast`, `pcolormesh`: shading modes, edge/line styling,
      antialiasing, snap, rasterized behavior and norm/colorizer variants.
- [x] `contour`/`contourf`: origin, extent, linestyles, corner masks, extend,
      hatches, locators, norms and filled-region topology parity.
- [x] `clabel`: inline path cutting, formatting, manual positions, rotation and
      complete text styling.
- [x] `tripcolor`/`tricontour`/`tricontourf`: norms, masks, shading,
      antialiasing, hatches, extends and triangulation-object interoperability.
- [x] `spy` and `matshow`: sparse inputs, precision semantics and return types.

### Pie, table, spectra and vector fields

- [x] `pie`: shadow, frame, rotated labels, hatches, explode/autopct placement,
      normalize behavior, text properties and wedge properties.
- [x] `table`: cell/row/column alignment, placement, edges, sizing, colors and
      mutable cell objects.
- [x] Spectral methods provide the native real-valued Hann-windowed defaults.
- [ ] Spectral callable windows/detrending, independent `pad_to`, explicit
      sides/frequency scaling, complex inputs, modes and complete return-value
      parity. These remain acceptance debt for `statistics/psd_demo.py`.
- [x] `stem`, `stairs`, `eventplot`, and `stackplot`: complete style/container
      behavior, hatches, orientation and baselines.
- [x] `quiver`: units, head geometry, pivots, angles, scaling, norm, z-order and
      scalar-mappable behavior.
- [x] `barbs`: non-default increments, flags, rounding, empty-barb, flip,
      color, size, length, and pivot options render through fixed-staff
      WMO-style geometry.
- [x] `quiverkey`: coordinates, label positions, fonts and sizing.
- [x] `streamplot`: always integrates with the shim's own occupancy-aware
      adaptive Heun kernel, so output no longer depends on whether Matplotlib is installed;
      `start_points`, `integration_direction`, array `linewidth`/`color`,
      `num_arrows`, `arrowsize`, `broken_streamlines`, both integration scale
      controls, and plain `Normalize` are implemented, while `transform`,
      `zorder`, and non-default minlength/arrowstyle options fail loudly.

### Scales, units and dates

- [x] Implement `symlog`, `logit`, and `asinh` or retain loud errors and add
      explicit compatibility tests/documentation for each.
- [x] Resolve log base/subs/nonpositive options in `loglog`, `semilogx`, and
      `semilogy` through the documented boundary: base 10 and
      `nonpositive="clip"` are native; every other value raises the actionable
      `NotImplementedError` rather than being accepted.
- [x] Define a bounded units/converter story for datetime, timedelta and common
      categorical inputs; do not attempt the entire Matplotlib units registry
      unless real usage requires it.
- [x] Add date locators/formatters sufficient for ordinary time-series plots.

## P4 — Artist, collection, transform and container compatibility

- [x] Expose bounded `ax.lines`, `collections`, `patches`, `texts`, `images`,
      `artists`, `tables`, and `containers` views over shim-owned entries.
- [x] Add `get_children()` with stable ownership and removal semantics.
- [x] Add `add_line`, `add_container`, `add_table`, and wider `add_patch` /
      `add_collection` mappings for common Matplotlib objects.
- [x] Complete `Line2D`, `PathCollection`, image, contour, bar, stem, errorbar,
      pie, table and streamplot return-object surfaces used by gallery code.
- [x] Add common Artist getters/setters and aliases, including visibility,
      z-order, clipping, transform, label, alpha and rasterization flags where
      meaningful.
- [x] Define lightweight xy-owned `Bbox`, identity/affine transform and
      coordinate-space objects sufficient for supported calls.
- [x] Support data, axes-fraction, figure-fraction and offset point/pixel
      coordinate systems consistently across HTML, PNG and SVG.
- [x] Decide which external Matplotlib patches, collections, transforms,
      normalizers and triangulations are supported as optional adapters, then
      test that exact allowlist.
- [x] Reject arbitrary unsupported Artists with errors that identify the
      closest supported primitive.

## P5 — rcParams, styles, colors and export

- [x] Audit which of the currently listed rcParams actually affect output;
      listing a default must not imply behavior that is ignored.
- [x] Add the high-frequency rcParams for axes face/spines, font family/size,
      label/title sizes, tick styling, legend, savefig, image origin and color
      cycle.
- [x] Add nested `rc_context()` restoration and `rcdefaults()` tests.
- [x] Support style dictionaries and a small documented style-sheet allowlist,
      or keep `style.use()` restricted and report unsupported styles precisely.
- [x] Expand color parsing only where xy's CSS/native pipeline can preserve the
      value; test named colors, alpha, under/over/bad and reversed colormaps.
- [x] Add explicit behavior for file-like export with a declared format.
- [x] Decide whether JPEG, WebP and PDF export belong in supported scope.
      Implement selected formats or produce actionable `NotImplementedError`s.
- [x] Test metadata, transparent backgrounds, face/edge colors, bounding boxes,
      padding, orientation and DPI semantics for `savefig()`.

## P6 — typing, documentation and maintenance

- [x] Add a useful typed public surface for native Artists and containers plus
      dependency-free common Figure/Axes protocols, concrete native aliases,
      structural compat aliases, and honest mode-routed return unions.
- [x] Add API documentation generated from the supported compatibility matrix.
- [x] Fix the stale `spec/api/chart-roadmap.md` rows that still call pie, vector
      fields and irregular-grid families planned even though the shim exposes
      implementations.
- [x] Document approximation levels: exact geometry, equivalent semantics,
      visual approximation, accepted no-op, optional interop, and unsupported.
- [x] Add a compatibility changelog tied to upstream Matplotlib releases.
- [x] Re-run the source inventory whenever the pinned Matplotlib revision moves.
- [x] Keep the native shim inside `python/xy/pyplot/`; keep the public compat
      backend/display-list boundary inside `python/xy/backends/`; and preserve
      lightweight imports so neither `xy` nor a plain `xy.pyplot` import loads
      Matplotlib.

## Native-mode exclusions and compat-mode ownership

The original exclusions below still apply to native mode. They are not global
product exclusions: compat mode deliberately uses real Matplotlib for the
semantic systems that would be unbounded to reimplement.

### Renderer and backend

- Exact pixel parity and reproducing Agg, Cairo, Qt, Tk, GTK, wx, macOS,
  WebAgg, PDF, PS, SVG, or PGF backends are not goals.
- Compat mode does provide the public
  `module://xy.backends.backend_xy` canvas, manager, timers, callback registry,
  full-redraw blit, and display-list renderer. Its HTML, SVG, and native raster
  consumers must handle accepted output directly.
- Agg or another Matplotlib renderer may be used as a development oracle only.
  Any gallery result marked `fallback_used` fails.
- Native GUI embedding remains a classified non-pyplot integration concern,
  not an import-swap pyplot pass.

### Events and blocking interaction

- Native mode keeps XY's own browser interaction model rather than recreating
  Matplotlib GUI event loops.
- Compat mode maps live browser pointer, keyboard, scroll, resize, and close
  input to standard Matplotlib event objects. `mpl_connect`, picking, widgets,
  timers, `draw`, `draw_idle`, and full-redraw `blit` are in scope.
- Deterministic input drivers cover gallery calls such as `ginput`,
  `waitforbuttonpress`, and manual contour labeling. A standalone HTML file has
  no live Python callbacks after its process exits.

### Artist, transform, layout, and toolkit systems

- Native mode retains its bounded Artist-shaped objects, transforms, and layout
  implementation.
- Compat mode uses Matplotlib's real Artist graph, transform stack, clipping,
  layout engines, units, `axes_grid1`, and `axisartist`; XY renders their
  device-space operations. Third-party draw overrides are supported only to
  the extent that they resolve through the renderer protocol and gallery gate.

### Projection and domain systems

- Native mode supports its documented 2-D and polar surface; native 3-D,
  ternary, geographic, and general custom projections remain outside that
  implementation.
- Compat mode places `mplot3d`, projection registration, units, and depth
  ordering in Matplotlib's frontend. All 47 gallery 3-D examples and toolkit
  cases remain acceptance work until their reports pass; architecture presence
  is not final completion.
- TeX, fonts, GUI/toolkit libraries, and related system packages belong to the
  declared extended environment rather than a silent waiver.

### Animation

- Native applications continue to use XY's streaming and declarative animation
  APIs.
- Compat mode includes Matplotlib `FuncAnimation`, `ArtistAnimation`, timers,
  widgets, and full-redraw blitting. Gallery tests drive initial, middle, and
  final states plus timer/callback evidence. Standalone output may embed
  precomputed frames but cannot promise arbitrary Python callbacks.

### Matplotlib modules

Native mode does not independently clone `matplotlib.artist`, `collections`,
`patches`, `path`, `transforms`, `ticker`, `dates`, `units`, `tri`,
`animation`, `widgets`, `backend_*`, or `toolkits`. Compat mode requires the
supported Matplotlib extra and uses those real modules; it does not create
parallel `xy` replacements for them.

## Appendix A — missing public upstream `pyplot` functions

This is the historical native name-level difference at the reference revision
(73 names). It is not the compat-mode API inventory; compat lazily exposes
Matplotlib's pyplot surface.

```text
autoscale autumn axes bone box cla clf clim connect cool copper delaxes
disconnect draw draw_if_interactive figimage figlegend fignum_exists figtext
findobj flag gci get get_current_fig_manager get_figlabels get_fignums
get_plot_commands getp ginput gray hot hsv imread imsave inferno
install_repl_displayhook ioff ion isinteractive jet locator_params magma
margins minorticks_off minorticks_on new_figure_manager nipy_spectral pause
pink plasma polar prism rc_context rcdefaults rgrids sci set_cmap set_loglevel
setp spring subplot2grid subplot_tool summer switch_backend thetagrids
tick_params ticklabel_format twiny uninstall_repl_displayhook viridis
waitforbuttonpress winter xkcd
```

## Appendix B — historical native `Axes`/`_AxesBase` name gaps

This is the historical native name-level difference at the reference revision
(104 names). It includes properties and renderer/navigation methods as well as
ordinary user APIs; genuine Matplotlib Axes own this surface in compat mode.

```text
add_child_axes add_container add_line add_table apply_aspect artists autoscale
autoscale_view can_pan can_zoom cla clear collections contains contains_point
drag_pan draw draw_artist end_pan format_coord format_xdata format_ydata
get_adjustable get_anchor get_aspect get_autoscale_on get_axes_locator
get_axisbelow get_box_aspect get_children get_data_ratio
get_default_bbox_extra_artists get_facecolor get_forward_navigation_events
get_frame_on get_gridspec get_images get_legend get_legend_handles_labels
get_lines get_navigate get_navigate_mode get_rasterization_zorder
get_shared_x_axes get_shared_y_axes get_subplotspec get_tightbbox get_title
get_window_extent get_xaxis get_xaxis_text1_transform get_xaxis_text2_transform
get_xbound get_xlabel get_xmargin get_yaxis get_yaxis_text1_transform
get_yaxis_text2_transform get_ybound get_ylabel get_ymargin has_data images
in_axes indicate_inset lines minorticks_off minorticks_on patches
redraw_in_frame relim reset_position secondary_xaxis secondary_yaxis
set_adjustable set_autoscale_on set_axes_locator set_axis_on set_axisbelow
set_box_aspect set_facecolor set_figure set_forward_navigation_events
set_frame_on set_navigate set_navigate_mode set_prop_cycle
set_rasterization_zorder set_subplotspec set_xbound set_xmargin set_ybound
set_ymargin set_zorder sharex sharey start_pan tables texts ticklabel_format
twiny update_datalim use_sticky_edges viewLim
```

## Appendix C — historical native `Figure`/`FigureBase` name gaps

This is the historical native name-level difference at the reference revision
(60 names). Compat mode returns genuine Matplotlib Figure objects.

```text
add_artist add_axobserver add_gridspec add_subfigure align_labels align_titles
align_xlabels align_ylabels axes clear clf contains delaxes draw draw_artist
draw_without_rendering get_children get_constrained_layout
get_constrained_layout_pads get_default_bbox_extra_artists get_dpi
get_edgecolor get_facecolor get_figheight get_figure get_figwidth get_frameon
get_layout_engine get_linewidth get_size_inches get_suptitle get_supxlabel
get_supylabel get_tight_layout get_tightbbox get_window_extent ginput legend
number pick sca set_canvas set_constrained_layout set_constrained_layout_pads
set_dpi set_edgecolor set_facecolor set_figheight set_figure set_figwidth
set_frameon set_layout_engine set_linewidth set_tight_layout subfigures subplots
supxlabel supylabel text waitforbuttonpress
```

## Appendix D — native 2-D plotting-method inventory

These 66 names currently satisfy the documented name-presence contract on both
the shim `Axes` and stateful `xy.pyplot` namespace. Their option-depth work is
tracked above.

```text
plot errorbar scatter step loglog semilogx semilogy fill_between fill_betweenx
bar barh bar_label grouped_bar stem eventplot pie pie_label stackplot
broken_barh vlines hlines fill axhline axhspan axvline axvspan axline acorr
angle_spectrum cohere csd magnitude_spectrum phase_spectrum psd specgram xcorr
ecdf boxplot violinplot bxp violin hexbin hist hist2d stairs clabel contour
contourf imshow matshow pcolor pcolorfast pcolormesh spy tripcolor triplot
tricontour tricontourf annotate text table arrow barbs quiver quiverkey
streamplot
```










---

## Historical native post-review status (rewritten 2026-07-13)

The earlier pasted native record was corrupted and internally stale; this
section is authoritative for that audit only. The 507-source gallery contract
is authoritative for current compat remediation.

### Evidence layer — built, with known limits

- All 54 dual-engine corpus cases render PNGs in both engines and compare ink
  fraction (0.2–5.0x) and foreground-bbox aspect (0.5–2.0x). This catches
  blank/absent renders but is deliberately renderer-tolerant: wrong data and
  an empty axes still pass. Real per-script perceptual comparison remains
  future work.
- Cross-engine semantic oracles: triangulation topology, masked scatter `c`
  arrays, removable handles, and RGBA passthrough genuinely compare against
  Matplotlib (they fail against the pre-fix shim). The contour oracle only
  echoes explicitly passed levels — xy's *auto* contour levels demonstrably
  diverge from Matplotlib's and are untested. The vector oracle checks shaft
  angles against input math, not against Matplotlib; magnitudes are untested.
- PNG thresholds: per-family IoU floors (line 0.20 / bar 0.70 / image 0.55),
  ink band 0.5–2.0x, luma 0.20. Wrong-data and wrong-family renders now fail;
  margins are thin (a correct image scores ~0.567 vs the 0.55 floor). The
  negative control is tied to the live `MINIMUM_IOU` values, so loosening
  them below a wrong-geometry score fails the control.
- Discard detector: mechanically scans public shim adapters for bare
  `kwargs.pop`/`del` statements without a `compat-noop:` marker. It does NOT
  catch a named parameter that is accepted and never read, or an
  assigned-then-unused pop; the `compat-noop:` escape hatch is free text.
- Corpus coverage credits calls only on receivers traced to
  `subplots`/`gca`/... — but the names `ax`/`axes` are trusted
  unconditionally, so it is a naming heuristic, not type resolution.
- Reference CI installs the released `matplotlib==3.11.0` wheel and asserts
  the version; all reference tests run (0 skipped) locally and in CI. The
  former snapshot↔upstream-checkout comparison no longer runs anywhere: the
  `v3.11.0-348-gbde111fb4e` pin recorded in the snapshot is informational
  only. `verify_ci_workflow.py` is step-local but still substring-based
  within a step (an `echo`-prefixed or commented-out command inside the right
  step still passes).

### Export options

- `savefig` PNG: `bbox_inches="tight"` (true content-bbox crop; `pad_inches`
  can only re-expand up to the original canvas), `transparent=`, `facecolor=`
  (pixel-verified), `metadata=` (tEXt/iTXt; non-Latin-1 keys raise
  ValueError).
- SVG: metadata as a flattened `<metadata>` text node (not RDF); non-white
  backgrounds emitted as a full-bleed `<rect>`; suptitles reach both grid and
  single-chart documents, `y` maps as a figure fraction.
- HTML: non-white backgrounds wrap the document in a styled container;
  `metadata=` is rejected loudly.
- Suptitle styling is per-backend best-effort: PNG honors size/color/x but
  ignores weight/family/y/ha; HTML honors size/weight/family/color but
  ignores x/y/ha. Accepted as a documented approximation.

### Implemented in the follow-up passes

- hlines/vlines dash geometry (data-space; dash tuples and per-line style
  arrays reject loudly), fill_between interpolation including single-point
  `where` regions, violin extrema, masked scatter rows (x/y/s/c), `imsave`
  colormapping (normalizes original values; cmap ignored for RGB(A) input
  like Matplotlib), `data=` routes for hlines/vlines/fill_betweenx/contour*/
  quiver/barbs (plot/scatter/hist/bar still reject `data=`), unknown colormap
  names raise ValueError at every entry point including `set_cmap` (which now
  also feeds imshow/scatter defaults via `rcParams["image.cmap"]`), legend
  layout options `borderpad`/`labelspacing` now map to renderer spacing;
  handlelength/handletextpad/title_fontsize still raise NotImplementedError
  instead of vanishing.
- Newer tranche (validation in progress, see matrix/compat doc): boxplot
  notch/bootstrap/user statistics, violin bandwidths/quantiles/sides, hexbin
  `C`/reducers/`mincnt`, symlog/logit/asinh scales, secondary axes, affine
  data transforms for point/segment artists.

### Accepted approximations (documented, still divergent)

- imshow's dependency-free named filters approximate Matplotlib's AGG kernels
  and use a bounded 512–1024 px intermediate rather than selecting the filter
  and target size from the final display resolution; explicit
  `interpolation="auto"` remains unsupported.
- Errorbar limit flags render one-sided bars without Matplotlib's caret arrows.
- stem/eventplot/triplot/hlines/vlines dashes are data-space geometry (they
  scale with zoom).
- Exception types diverge by design: TypeError/NotImplementedError where
  Matplotlib accepts the value.

### Known-inconsistent, still open

- Exporter chrome beyond backgrounds (fonts, tick/legend styling) stays fixed
  in single-chart PNG/SVG regardless of rcParams — except `axes.titleweight`
  and `axes.labelweight`, which reach the browser, single-chart SVG, and
  single-chart native PNG paths and are covered by
  `tests/pyplot/test_rc_chrome_contracts.py`.
- `ax.set_facecolor()` mutates the per-Axes plot background after creation,
  but `set_facecolor(None)` is a silent no-op rather than a reset to the rc
  default; restoring it requires passing `rcParams["axes.facecolor"]` back
  explicitly.
- `ax.patches` holds only pie wedges; bar rects live in containers.
- `get_xticks()` on category/time axes falls back to linear ticks; tick
  density ignores figure size.
- Family-level claims in `compatibility.json` have no executable backing.

### Bottom line

Evidence machinery, common export options, exporter backgrounds, the legend
discard boundary, dash geometry, interpolated fills, violin extrema, and the
colormap validation boundary are implemented and regression-tested. Items
listed above as approximations or open inconsistencies are exactly that —
none of this is claimed as full Matplotlib parity. Compat mode pursues that
separate goal through the real Matplotlib frontend and the gallery gate above.

- `matplotlib.sankey.Sankey`: deliberately NOT shimmed. Its API is a
  path-drawing toolkit (trunk/branch offsets in axes units), not a flow-data
  API; `xy.sankey_chart(links)` is the supported spelling. Revisit only if
  corpus evidence shows real notebooks using mpl's Sankey.
