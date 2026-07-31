# `xy.pyplot` Matplotlib 3.11 compatibility evidence

This directory contains review evidence for
[reflex-dev/xy#413](https://github.com/reflex-dev/xy/pull/413), captured from
implementation commit `0efb0cfbb744fe7dd9c010fe5964e070686e9910`.

The comparisons are deliberately tolerant rather than pixel-identical. The
acceptance contract checks figure and capture counts, dimensions, axes and
colorbar geometry, labels, limits, legends, artist families, interaction
behavior, and blurred/downsampled perceptual similarity.

## Standard gallery result

| Gate | Result |
|---|---:|
| Matplotlib completed | 472/472 |
| `xy.pyplot` completed | 472/472 |
| Figure/capture parity | 472/472 |
| Dimension policy | 472/472 |
| Semantic gate | 472/472 |
| Visual gate | 472/472 |
| Behavior gate | 71/71 |
| Fallbacks | 0 |
| Waivers | 0 |

The clean standard report has SHA-256
`02bb095b563bbd47bfc209d7cb0fafe143adb282483d3427d81249c6f22359a1`.

## Renderer comparisons

| Family | Matplotlib | `xy.pyplot` |
|---|---|---|
| Normalization and mesh | [reference](power_norm-matplotlib.png) | [XY](power_norm-xy.png) |
| 3-D surface | [reference](surface3d-matplotlib.png) | [XY](surface3d-xy.png) |
| Inset axes | [reference](zoom_inset_axes-matplotlib.png) | [XY](zoom_inset_axes-xy.png) |
| Bracket arrows | [reference](angles_on_bracket_arrows-matplotlib.png) | [XY](angles_on_bracket_arrows-xy.png) |
| Figure-level text | [reference](figure_title-matplotlib.png) | [XY](figure_title-xy.png) |
| `matshow` | [reference](matshow-matplotlib.png) | [XY](matshow-xy.png) |

The mesh regression is documented with
[the old output](power_norm-before-xy.png),
[the corrected output](power_norm-after-xy.png), and
[the old difference image](power_norm-before-difference.png).

## Interaction comparisons

| Family | Matplotlib | `xy.pyplot` |
|---|---|---|
| Coordinate status | [reference](coords_report-matplotlib.png) | [XY](coords_report-xy.png) |
| Mouse cursor | [reference](mouse_cursor-matplotlib.png) | [XY](mouse_cursor-xy.png) |
| Resample callback | [reference](resample-matplotlib.png) | [XY](resample-xy.png) |
| Polygon selector | [reference](polygon_selector-matplotlib.png) | [XY](polygon_selector-xy.png) |

The live browser host is captured in
[chart view](live-browser-chart.png) and
[event diagnostics](live-browser-events.png).

