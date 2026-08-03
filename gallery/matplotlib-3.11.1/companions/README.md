# XY-native companions for non-pyplot sources

The gallery contract contains 22 sources that never import
`matplotlib.pyplot`. They are retained in the 507-source manifest, but they
cannot test whether `import xy.pyplot as plt` is a drop-in replacement.

Four of those sources are finite, headless programs. Explicit XY-native
companions live in `xy_native/`:

| Upstream source | XY-native companion | What it exercises |
|---|---|---|
| `misc/font_indexing.py` | `xy_native/font_indexing.py` | Embedded atlas indexing and advances |
| `misc/ftface_props.py` | `xy_native/ftface_props.py` | Embedded atlas global metrics |
| `units/basic_units.py` | `xy_native/basic_units.py` | Explicit conversion before native chart construction |
| `user_interfaces/canvasagg.py` | `xy_native/canvasagg.py` | Native Rust PNG export and RGBA decoding |

These are maintained ports, not transformed upstream inputs. They do not
increase the pyplot-eligible denominator or numerator. The other 18 sources
need a GUI toolkit/event loop or start a web server and remain classified as
backend-embedding coverage. `manifest.json` records all 22 dispositions and
locks every upstream and companion hash.

The upstream source files remain byte-for-byte unchanged under `../examples/`.
Their license and copyright notice are in `../LICENSE`.
