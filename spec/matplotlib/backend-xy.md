# Matplotlib XY backend and display-list contract

The public Matplotlib backend is
`module://xy.backends.backend_xy`. It targets Matplotlib 3.11 and is the
renderer used by `xy.pyplot` compatibility mode. Importing `xy.backends` does
not import Matplotlib; resolving the backend module is the optional-dependency
boundary.

## Backend protocol

`RendererXY` is a `matplotlib.backend_bases.RendererBase`,
`FigureCanvasXY` is a `FigureCanvasBase`, and `FigureManagerXY` is a
`FigureManagerBase`. The module exports Matplotlib's standard `FigureCanvas`,
`FigureManager`, `new_figure_manager`, `new_figure_manager_given_figure`,
`draw_if_interactive`, and `show` entry points.

The initial canvas supports:

- synchronous `draw` and `draw_idle`;
- Matplotlib callback registration and explicit event dispatch;
- live IPython anywidget and token-authenticated loopback `show()` hosts, both
  using the shared browser event adapter;
- timers driven by browser heartbeats, the blocking main loop, or
  `flush_events`, including a deterministic `fire` method for tests;
- a `NavigationToolbar2`-compatible controller for keyboard and pointer
  pan/zoom plus home/back/forward history;
- `copy_from_bbox`, `restore_region`, and display-list background `blit`;
- static standalone PNG, SVG, HTML, and JSON output.

Blit backgrounds retain the immutable command/resource containers from the
last draw. Restoring a background replaces only those outer containers;
animated Artists then append their current device-space operations before the
widget or loopback host publishes the new generation. Large static paths are
therefore not rebuilt for every pointer move or animation frame.

PNG consumes the same display list through XY's native raster command stream
and PNG encoder. It does not instantiate Agg, Cairo, another Matplotlib
renderer, or a browser. Paths and outlined text are curve-flattened, compound
fills retain nonzero-winding holes, collections remain ordered, and image
resources are decoded directly from XY's content-addressed PNG representation.
The consumer also covers rectangular and arbitrary path clips, tiled hatches,
quad meshes, and barycentrically interpolated Gouraud batches.
Repeated shaped clips share one exact supersampled mask within a raster pass.
Rectilinear Gouraud meshes use a vectorized four-triangle interpolation that is
equivalent to Matplotlib's center-subdivided QuadMesh geometry; arbitrary
triangle batches retain the general barycentric path.

SVG expands hatches to reusable patterns and Gouraud triangles to composited
vertex gradients. Artist groups remain nested `<g>` elements with stable,
XML-safe IDs, and the root includes a mutable namespaced default style so
examples that post-process Matplotlib SVG output retain their expected hooks.

## Display-list IR

`xy.backends.DisplayList` is independent of Matplotlib and contains only plain,
finite JSON values. Schema `xy.display-list/1` records:

- canvas width, height, and DPI;
- ordered commands;
- content-addressed binary resources;
- renderer metadata;
- mandatory `fallback_used` and `fallback_reason` fields.

Coordinates are device pixels with a bottom-left origin. Commands currently
cover compound paths, outlined text, marker and path collections, RGBA images,
quad-mesh batches, Gouraud triangle batches, and artist group boundaries.
Styles retain stroke/fill RGBA, line width, cap/join, dash, antialiasing, hatch,
clip, link, and artist-id information. Text commands retain the original text
while referencing content-addressed font metadata and Matplotlib-produced glyph
outline path resources. Identical metadata and device-space outlines are stored
once and shared by the SVG, standalone HTML, and native raster consumers.
TeX outlines are laid out at the requested property size before conversion, so
absolute declarations such as `\font\a ptmr8r at 14pt\a` retain their physical
point size instead of inheriting the generic 100-point path normalization.

Images are encoded by XY's stdlib PNG encoder and deduplicated by SHA-256.
Large numeric batches use content-addressed little-endian float array
resources, with dtype, shape, byte-count, and checksum validation, rather than
expanding millions of scalar values through the command tree. Both SVG and
native raster consumers decode the same packed resource.
Collections keep one copy of each transformed source path plus ordered
instances. The PNG, SVG, and HTML serializers consume this IR directly and
never instantiate a Matplotlib renderer. `DisplayList.to_rgba()` exposes the
native straight-alpha buffer for semantic and nonblank checks;
`DisplayList.to_png()` encodes that same buffer at the requested output scale.

## Acceptance boundary

Every serialized result exposes `fallback_used`; gallery acceptance must fail
when it is true. The developer oracle may compare the display list or its SVG
against a Matplotlib reference, but it may not replace an unsupported command
with Agg output and still count the case as passing.

Three-dimensional axes are rejected both before and immediately after every
Matplotlib Figure traversal. The second check covers `draw_event` callbacks
that mutate the final Figure before its display list can be published.

Renderer-conformance fixtures cover the same shaped clip, hatch geometry, and
Gouraud vertex data through JSON, standalone HTML/SVG, and native PNG/RGBA.
Every accepted path keeps `fallback_used=false`; these features do not invoke
Agg or another Matplotlib renderer.
