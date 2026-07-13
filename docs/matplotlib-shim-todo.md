# `xy.pyplot` compatibility audit and TODO

This document tracks the work required to make `xy.pyplot` a reliable
Matplotlib-flavoured compatibility layer. It deliberately separates the
shim's supported target from full Matplotlib parity: the former is achievable;
the latter would require recreating systems that conflict with xy's small,
fast, browser-oriented design.

## Reference point and audit method

- Audit date: 2026-07-13.
- Upstream checkout: `ignore/matplotlib`.
- Upstream revision: `bde111fb4e`, described by Git as
  `v3.11.0-348-gbde111fb4e` (2026-07-10).
- Shim: `python/xy/pyplot/`.
- Contract test: `tests/pyplot/test_axes_charts.py::`
  `test_official_matplotlib_311_2d_plotting_surface_is_complete`.
- Executable examples: `tests/pyplot/corpus/`.

Name-level comparisons below were made from public top-level functions in
upstream `matplotlib/pyplot.py`, and public declarations on upstream `Axes`,
`_AxesBase`, `Figure`, and `FigureBase`. They are useful breadth indicators,
not semantic compatibility scores: renderer lifecycle methods, properties,
and APIs deliberately outside xy's design are included in the upstream sets.

## Current baseline

| Surface | Present in `xy.pyplot` | Notes |
|---|---:|---|
| Declared Matplotlib 3.11 2-D plotting-method contract | 66 / 66 (100%) | Name presence on both `Axes` and stateful `pyplot` |
| Public upstream `pyplot` functions | 92 / 165 (56%) | 73 names absent; see appendix A |
| Public upstream `Axes`/`_AxesBase` declarations | 89 / 193 (46%) | 104 names absent; see appendix B |
| Public upstream `Figure`/`FigureBase` declarations | 13 / 73 (18%) | 60 names absent; see appendix C |
| Compatibility corpus | 53 scripts | No expected failures |
| Current shim suite | 157 passed, 7 skipped | Skips require real Matplotlib |

The existing 100% statement is intentionally narrow. It means every method in
the selected Matplotlib 3.11 2-D **Plotting** inventory exists. It does not mean
that every keyword, returned Artist, transform, layout rule, backend feature,
or rendered pixel matches Matplotlib.

## Definition of done for the supported shim

The shim can be called complete for ordinary 2-D scripts when:

- [ ] Every documented supported call has geometry and return-value tests, not
      only an `hasattr` check.
- [ ] The same compatibility corpus runs against xy and the pinned Matplotlib
      reference in CI.
- [ ] Material data, limits, bins, levels, labels, container shapes, and image
      dimensions are compared with Matplotlib where exact parity is intended.
- [ ] A representative visual suite performs perceptual/difference checks,
      with explicit tolerances for the different renderer.
- [ ] No material keyword is silently discarded. It is implemented,
      documented as an approximation, or rejected with a helpful error.
- [ ] The common state, axes, figure, and mutation APIs listed in the P1/P2
      sections below work without installing Matplotlib.
- [ ] Optional support for real Matplotlib objects is tested in a dedicated CI
      environment.
- [ ] Public compatibility boundaries and intentional exclusions are current
      in both this document and `docs/matplotlib-compat.md`.

## P0 — make the compatibility claim measurable

- [ ] Add a CI job with the pinned/reference-compatible Matplotlib installed so
      the seven skipped tests in `test_launch_compat.py` always run.
- [ ] Run every corpus script through both `xy.pyplot` and
      `matplotlib.pyplot`; isolate process-global pyplot state between cases.
- [ ] Record and compare semantic oracles per chart family:
  - line/scatter data, masks, colors, sizes, and default color-cycle movement;
  - bar rectangles, category positions, stacking bases, and labels;
  - histogram counts, edges, density, cumulative and stacked outputs;
  - image extents, origin, normalization domain and RGBA behavior;
  - contour levels and paths; triangular topology and mesh bounds;
  - vector endpoints, streamline seeds, colors and widths;
  - returned tuples, containers, collections, texts and removable handles;
  - axis domains, reversed axes, ticks, labels and shared-axis behavior.
- [ ] Add representative Matplotlib-versus-xy PNG comparisons. Use perceptual
      tolerances and geometry masks rather than requiring identical antialiasing.
- [ ] Turn the hard-coded 66-name inventory into a generated, reviewed snapshot
      from the pinned upstream documentation/source so upstream additions are
      visible as a deliberate snapshot diff.
- [ ] Add coverage for every supported method, not just every broad family.
- [ ] Add a guard that detects accepted-and-discarded material keyword values.
- [ ] Publish the compatibility matrix from test metadata so documentation
      cannot drift from executable coverage.

## P1 — correctness gaps inside the advertised surface

### Remove accidental dependency on installed Matplotlib

- [x] Make `Axes.get_position()` return an xy-owned lightweight bbox instead of
      dynamically importing `matplotlib.transforms.Bbox`. Evidence: `Axes.get_position()`
      now returns the shim `Bbox`, and `test_axes_layout.py` blocks Matplotlib imports.
- [ ] Provide dependency-free behavior for transformed images, collections,
      normalization and streamplot paths, or clearly separate optional
      Matplotlib-object interop from the dependency-free shim.
- [ ] Test every public method in an environment where importing `matplotlib`
      fails; calling an advertised method must not accidentally require it.
- [ ] Keep the existing lightweight-import boundary: importing `xy.pyplot`
      must not load Matplotlib, the widget stack, or browser machinery.

### Implement or reject current no-ops

- [x] Implement meaningful `tight_layout()` behavior or document it as an
      accepted compatibility no-op with a tested layout guarantee. Evidence:
      `tests/pyplot/test_layout_noops.py::test_tight_layout_records_validated_noop_contract`
      records the accepted no-op layout contract and rejects unknown kwargs.
- [x] Implement `subplots_adjust()` parameters (`left`, `right`, `top`,
      `bottom`, `wspace`, `hspace`) for HTML, PNG, and SVG grids. Evidence:
      `tests/pyplot/test_layout_noops.py::test_subplots_adjust_records_supported_spacing_values`
      records all supported spacing values for grid exporters and rejects unknown kwargs.
- [x] Implement `Figure.autofmt_xdate()` label rotation/alignment. Evidence:
      `tests/pyplot/test_layout_noops.py::test_autofmt_xdate_rotates_x_tick_labels_on_all_axes`
      verifies rotation and horizontal alignment state on every axes.
- [x] Implement `Axes.margins()` and make it affect automatic domains. Evidence:
      automatic x/y domains expand by configured margins while explicit limits remain fixed.
- [x] Implement `Axes.set_position()` and preserve the requested figure rect. Evidence:
      `set_position([left, bottom, width, height])` updates `get_position().bounds` and
      `_figure_rect`.
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
- [ ] Audit marker fill styles, custom marker paths, join styles, clipping,
      hatches, z-order and transforms across all returned handles.

## P2 — common pyplot/Axes/Figure workflow compatibility

These should be implemented before backend-management or GUI APIs because they
appear frequently in ordinary scripts and notebooks.

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
- [x] `get/set_xbound`, `get/set_ybound`, x/y margins, and sticky-edge behavior. Evidence: `tests/pyplot/test_axes_helpers.py::test_autoscale_bounds_and_relim_helpers` verifies bound setters/getters and margin-aware automatic domains; sticky edges are intentionally out of scope because xy artists do not expose sticky-edge metadata.
- [x] `ticklabel_format()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies stored style, scientific limits, and offset policy.
- [x] `minorticks_on()` and `minorticks_off()` with an explicit minor-tick model. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies explicit minor tick state toggles.
- [x] `get_xlabel`, `get_ylabel`, `get_title`, `get_xaxis`, and `get_yaxis`. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies label/title getters and axis proxy identity.
- [x] `get_legend()` and `get_legend_handles_labels()`. Evidence: `tests/pyplot/test_axes_helpers.py::test_ticklabel_minor_label_axis_and_legend_helpers` verifies legend presence and labeled handles.
- [x] `set_prop_cycle()` beyond the fixed default color sequence. Evidence: `tests/pyplot/test_axes_helpers.py::test_prop_cycle_setp_getp_rc_context_and_colormap_helpers` verifies per-Axes color cycle order.
- [x] `secondary_xaxis()` and `secondary_yaxis()` if secondary-axis layout is
      promoted into supported scope; otherwise keep them explicitly excluded. Evidence:
      `tests/pyplot/test_axes_helpers.py::test_subplot2grid_box_and_secondary_axes_contract`
      verifies both helpers raise `NotImplementedError` with the compatibility-table error path.

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

- [ ] `plot`: `scalex`, `scaley`, marker face/edge styling, fillstyle, cap/join
      styles, `markevery`, general transforms and all draw styles.
- [ ] `scatter`: exact `vmin`/`vmax`/norm interaction, linewidth/stroke arrays,
      custom marker paths and full nonfinite color handling.
- [ ] `hlines`/`vlines`: linestyles, collection semantics, transforms and
      per-segment styles.
- [ ] `fill`/`fill_between`/`fill_betweenx`: edge rendering, interpolation at
      mask crossings, transforms and complete step semantics.
- [ ] `arrow`/`axline`: head shape/overhang, transforms and style fidelity.
- [ ] `axhline`/`axvline`/spans: linestyles and transform fidelity.
- [ ] `errorbar`: upper/lower limit flags, cap thickness, bars-above ordering,
      independent line styles, errorevery and full container semantics.

### Bars, histograms and distributions

- [ ] `bar`/`barh`: edge alignment, heterogeneous widths, complete x/y error
      styling, hatch, log mode and unit-aware/category behavior.
- [ ] `bar_label`: label type, custom callable formatting, padding/font
      properties and complete horizontal/negative-bar placement.
- [ ] `hist`: every histtype, heterogeneous bins, rwidth, log mode, bottom
      arrays and exact returned patches.
- [ ] `hist2d(norm=...)` and complete normalization/colorizer support.
- [ ] `hexbin(C=..., reduce_C_function=...)`, `mincnt`, marginals, norm,
      colorizer and explicit vmin/vmax.
- [ ] `boxplot`: notches, custom whiskers, bootstrap, user medians, confidence
      intervals, cap visibility/width, autorange and component properties.
- [ ] `bxp`: component style parity, labels/ticks, cap widths and returned
      component geometry.
- [ ] `violinplot`/`violin`: bandwidth methods, quantiles, side, extrema,
      points and component styling.
- [ ] `ecdf`: exact weights/complementary/orientation/compression behavior and
      returned Artist parity.

### Images, meshes and contours

- [ ] `imshow`: interpolation modes/stages, transforms, clipping, alpha arrays,
      filter radius, resampling, colorizer and norm variants without requiring
      Matplotlib.
- [ ] `pcolor`, `pcolorfast`, `pcolormesh`: shading modes, edge/line styling,
      antialiasing, snap, rasterized behavior and norm/colorizer variants.
- [ ] `contour`/`contourf`: origin, extent, linestyles, corner masks, extend,
      hatches, locators, norms and filled-region topology parity.
- [ ] `clabel`: inline path cutting, formatting, manual positions, rotation and
      complete text styling.
- [ ] `tripcolor`/`tricontour`/`tricontourf`: norms, masks, shading,
      antialiasing, hatches, extends and triangulation-object interoperability.
- [ ] `spy` and `matshow`: sparse inputs, precision semantics and return types.

### Pie, table, spectra and vector fields

- [ ] `pie`: shadow, frame, rotated labels, hatches, explode/autopct placement,
      normalize behavior, text properties and wedge properties.
- [ ] `table`: cell/row/column alignment, placement, edges, sizing, colors and
      mutable cell objects.
- [ ] Spectral methods: window, detrending, sides, padding, frequency scaling,
      modes, scale and return-value parity.
- [ ] `stem`, `stairs`, `eventplot`, and `stackplot`: complete style/container
      behavior, hatches, orientation and baselines.
- [ ] `quiver`: units, head geometry, pivots, angles, scaling, norm, z-order and
      scalar-mappable behavior.
- [ ] `barbs`: increments, flags, rounding, empty barbs, flips, colors and
      sizes rather than a quiver approximation.
- [ ] `quiverkey`: coordinates, label positions, fonts and sizing.
- [ ] `streamplot`: density, integration direction/length, broken-streamline
      behavior, arrows, transforms, z-order and consistent dependency-free
      integration.

### Scales, units and dates

- [ ] Implement `symlog`, `logit`, and `asinh` or retain loud errors and add
      explicit compatibility tests/documentation for each.
- [ ] Honor log base/subs/nonpositive options in `loglog`, `semilogx`, and
      `semilogy`.
- [ ] Define a bounded units/converter story for datetime, timedelta and common
      categorical inputs; do not attempt the entire Matplotlib units registry
      unless real usage requires it.
- [ ] Add date locators/formatters sufficient for ordinary time-series plots.

## P4 — Artist, collection, transform and container compatibility

- [ ] Expose bounded `ax.lines`, `collections`, `patches`, `texts`, `images`,
      `artists`, `tables`, and `containers` views over shim-owned entries.
- [ ] Add `get_children()` with stable ownership and removal semantics.
- [ ] Add `add_line`, `add_container`, `add_table`, and wider `add_patch` /
      `add_collection` mappings for common Matplotlib objects.
- [ ] Complete `Line2D`, `PathCollection`, image, contour, bar, stem, errorbar,
      pie, table and streamplot return-object surfaces used by gallery code.
- [ ] Add common Artist getters/setters and aliases, including visibility,
      z-order, clipping, transform, label, alpha and rasterization flags where
      meaningful.
- [ ] Define lightweight xy-owned `Bbox`, identity/affine transform and
      coordinate-space objects sufficient for supported calls.
- [ ] Support data, axes-fraction, figure-fraction and offset point/pixel
      coordinate systems consistently across HTML, PNG and SVG.
- [ ] Decide which external Matplotlib patches, collections, transforms,
      normalizers and triangulations are supported as optional adapters, then
      test that exact allowlist.
- [ ] Reject arbitrary unsupported Artists with errors that identify the
      closest supported primitive.

## P5 — rcParams, styles, colors and export

- [ ] Audit which of the currently listed rcParams actually affect output;
      listing a default must not imply behavior that is ignored.
- [ ] Add the high-frequency rcParams for axes face/spines, font family/size,
      label/title sizes, tick styling, legend, savefig, image origin and color
      cycle.
- [ ] Add nested `rc_context()` restoration and `rcdefaults()` tests.
- [ ] Support style dictionaries and a small documented style-sheet allowlist,
      or keep `style.use()` restricted and report unsupported styles precisely.
- [ ] Expand color parsing only where xy's CSS/native pipeline can preserve the
      value; test named colors, alpha, under/over/bad and reversed colormaps.
- [ ] Add explicit behavior for file-like export with a declared format.
- [ ] Decide whether JPEG, WebP and PDF export belong in supported scope.
      Implement selected formats or produce actionable `NotImplementedError`s.
- [ ] Test metadata, transparent backgrounds, face/edge colors, bounding boxes,
      padding, orientation and DPI semantics for `savefig()`.

## P6 — typing, documentation and maintenance

- [ ] Add a useful typed public surface for `xy.pyplot`, `Axes`, `Figure`,
      common Artists, containers and return tuples; reduce broad `Any` usage.
- [ ] Add API documentation generated from the supported compatibility matrix.
- [ ] Fix the stale `docs/chart-roadmap.md` rows that still call pie, vector
      fields and irregular-grid families planned even though the shim exposes
      implementations.
- [ ] Document approximation levels: exact geometry, equivalent semantics,
      visual approximation, accepted no-op, optional interop, and unsupported.
- [ ] Add a compatibility changelog tied to upstream Matplotlib releases.
- [ ] Re-run the source inventory whenever the pinned Matplotlib revision moves.
- [ ] Keep all shim code inside `python/xy/pyplot/` and preserve the one-way
      dependency boundary enforced by `tests/pyplot/test_boundaries.py`.

## Explicitly out of scope

These exclusions are intentional unless a future project explicitly promotes
one of them. Missing names belonging primarily to these systems should not be
treated as ordinary shim bugs.

### Renderer and backend replacement

- Matplotlib renderer internals, draw traversal, stale propagation, graphics
  contexts, backend canvases, renderer-specific filters and exact pixel parity.
- Backend selection and manager APIs: `switch_backend`, `new_figure_manager`,
  `get_current_fig_manager`, REPL display-hook installation and backend toolbars.
- Reproducing Agg, PDF, PS, SVG, PGF, Cairo, Qt, Tk, GTK, wx, macOS or WebAgg.

### GUI event loops and blocking interaction

- `ion`, `ioff`, `isinteractive`, `pause`, `ginput`, `waitforbuttonpress`, GUI
  main loops and Matplotlib callback registry compatibility.
- Native-window pan/zoom tool state, toolbar modes and backend keymaps.
- Matplotlib-style picking/event objects beyond xy's own browser interaction
  and selection APIs.

### Full Artist and transform graph

- Arbitrary third-party Artist subclasses and arbitrary draw overrides.
- Complete transform composition, blended transforms, path effects, clipping
  graphs and layout bbox negotiation.
- Full introspection parity for every Artist property.
- Blitting and renderer-driven animation lifecycle.

### Projection and domain systems

- 3-D plotting and `mplot3d`.
- Polar, radar, ternary, geographic and custom projection registration.
- Cartopy/Basemap integration.
- Full TeX/MathText/PGF layout parity and Matplotlib font-manager behavior.

### Animation

- `FuncAnimation`, `ArtistAnimation`, movie writers and blitting. xy's native
  streaming/update APIs are the preferred model.

### Every Matplotlib module

This shim targets plotting calls and common script ergonomics. It does not aim
to replace `matplotlib.artist`, `collections`, `patches`, `path`, `transforms`,
`ticker`, `dates`, `units`, `tri`, `animation`, `widgets`, `backend_*`, or
`toolkits` as import-compatible standalone modules. Small compatibility objects
may be provided inside `xy.pyplot` when required by supported workflows.

## Appendix A — missing public upstream `pyplot` functions

This is the complete name-level difference at the reference revision (73
names). Several are intentionally out of scope; the P2 section identifies the
high-value subset.

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

## Appendix B — missing public upstream `Axes`/`_AxesBase` declarations

This is the complete name-level difference at the reference revision (104
names). It includes properties and renderer/navigation methods as well as
ordinary user APIs.

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

## Appendix C — missing public upstream `Figure`/`FigureBase` declarations

This is the complete name-level difference at the reference revision (60
names).

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

## Appendix D — supported 2-D plotting-method inventory

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
