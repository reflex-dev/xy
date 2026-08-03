# Non-pyplot gallery companions

XY's Matplotlib 3.11 gallery contract has 459 non-3-D sources, of which 437
directly bind `matplotlib.pyplot` and can be evaluated by changing only that
binding to `xy.pyplot`. The remaining 22 are a separate contract:

- they remain represented as `profile: "non_pyplot"` and
  `pyplot_eligible: false` in the immutable upstream manifest;
- they never count as a pyplot execution pass, failure, waiver, or denominator;
- four finite, headless programs have maintained native-XY companion ports;
- 16 GUI embedding examples remain toolkit integration references; and
- two server examples remain live backend/server integration references.

The companion registry at
`gallery/matplotlib-3.11.1/companions/manifest.json` maps all 22 upstream
sources to their disposition. It hash-locks both the upstream source and each
maintained companion. Tests require the registry to agree with the canonical
459-source manifest and require every companion to avoid `xy.pyplot`.

The companions are intentionally API-level translations rather than import
rewrites:

- font diagnostics describe XY's generated DejaVu Sans coverage atlas because
  native XY does not link FreeType at runtime. They mirror the rasterizer's
  character normalization: controls and zero-width characters are dropped,
  unsupported whitespace advances as an ordinary space, and other unsupported
  codepoints use U+FFFD;
- unit values are explicitly converted to ordinary numeric arrays before
  entering the dependency-free chart API; and
- the direct-canvas example calls `Chart.to_png(engine=xy.Engine.default)`,
  which is the native Rust raster path, then decodes the returned PNG into an
  RGBA image and writes BMP explicitly, independent of the output suffix.

This evidence does not claim that XY provides Matplotlib GUI embedding,
FreeType object introspection, or an independent units registry. Those
semantics belong to optional Matplotlib compat mode where applicable.
