# Matplotlib compatibility changelog

This changelog records changes to the upstream compatibility target and to the
meaning of xy's compatibility levels. It complements the project changelog,
which covers user-visible releases across the whole package.

## Matplotlib 3.11 development snapshot — 2026-07-13

- Pinned upstream revision `bde111fb4e`
  (`v3.11.0-348-gbde111fb4e`, 2026-07-10).
- Captured the supported 66-method `Axes` Plotting inventory as a generated,
  reviewed snapshot instead of a hard-coded assertion.
- Added `grouped_bar`, `pie_label`, and `violin` from the 3.11 development
  surface.
- Added a dedicated CI environment for optional Matplotlib-object interop and
  isolated dual-engine execution of the full compatibility corpus.
- Published approximation levels and a generated method compatibility matrix.

### Post-review corrections — 2026-07-13

- Downgraded "Unstructured triangles" from *exact geometry* to *equivalent
  semantics*: the family has no cross-engine reference comparison yet.
- Converted the formerly silent option discards into loud rejections: pie
  shadow/frame/rotatelabels/hatch, quiver/barbs/quiverkey head geometry,
  units, increments and styling, contour origin/linestyles/corner_mask,
  table placement, tricontour extend, non-linear norm objects everywhere,
  spy aspect, and pie_label rotate.
- Implemented (rather than rejected) where the marks could honor the value:
  contour `extent`; plain `Normalize` reduced to vmin/vmax for pcolormesh and
  the tri* family; stem/eventplot/triplot dashed linestyles via data-space
  dash segmentation (scales with zoom — not screen-space patterns);
  `bar_label(fontsize=)` and pie/pie_label/table textprops
  fontsize/ha/va; streamplot `start_points`, `integration_direction`,
  array widths/colors, `num_arrows`.
- `streamplot` now always uses the shim's bounded fixed-step integrator;
  results no longer differ between environments with and without Matplotlib
  installed, and paths approximate Matplotlib's adaptive integrator.
- `hist(histtype="stepfilled")` renders a filled step polygon instead of
  silently degrading to the unfilled step outline.
- Documented the accepted visual approximations explicitly (barbs glyph,
  imshow smoothing collapse and truecolor passthrough, annotate arrowprops,
  errorbar limit carets, data-space dashes) and the HTML-only scope of
  chrome rcParams.

Future entries must identify the Matplotlib release/revision, inventory
additions or removals, and any compatibility-level changes.
