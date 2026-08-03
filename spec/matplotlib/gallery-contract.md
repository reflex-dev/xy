# Matplotlib 3.11.1 source / 3.11.0 oracle gallery contract

The exact Matplotlib `stable` gallery archives supplied on 2026-07-30 are xy's
executable definition of `pyplot` drop-in compatibility. Those sources come
from the Matplotlib 3.11.1 documentation build; the reference runtime remains
the separately pinned Matplotlib 3.11.0 wheel. The contract measures
successful execution, structure, semantics, behavior, and material visual
formatting. It deliberately does not require identical antialiasing, glyph
rasterization, or pixels.

## Corpus and provenance

The source archives contain 507 Python examples. The contract excludes their
48 three-dimensional examples and vendors the remaining 459 under
`gallery/matplotlib-3.11.1/examples/`. `manifest.json` records the SHA-256 and
byte count of every included source. It also records every matching notebook
SHA-256 and a normalized AST digest proving that all 459 included notebook
code-cell programs equal their Python source after removal of the source module
docstring.

Both generation and verification enforce the exclusion boundary. Rebuilding
an existing destination removes only excluded members that are present in the
upstream archive and rejects every local Python source outside that archive;
verification independently rejects an excluded path in the committed
manifest.

The generator changes no source bytes. A test execution creates a temporary
file and uses a token-aware rewrite for only these two direct import forms:

```python
import matplotlib.pyplot as plt
from matplotlib import pyplot as plt
```

The rewritten AST must equal an independently constructed AST in which only
the pyplot provider changes. Strings, comments, unrelated Matplotlib imports,
and ambiguous mixed imports cannot be rewritten. The token-aware pass replaces
the selected module-name character spans directly, from right to left; it does
not reconstruct the source with `tokenize.untokenize`. Consequently every
non-target character and the transformed SHA-256 are stable across supported
CPython 3.11 and 3.12 patch releases, including sources whose f-string token
boundaries changed between interpreters.

Exactly 437 examples are eligible for this import swap:

| Classification | Count | Meaning |
|---|---:|---|
| `standard` | 425 | Matplotlib completed in the standard headless profile |
| `extended` | 12 | Needs TeX, GUI/toolkit packages, input, arguments, or multiprocessing support |
| `non_pyplot` | 22 | Direct backend, font, or GUI embedding example with no pyplot import |

The 22 non-pyplot sources remain in the manifest. They are never counted as
`xy.pyplot` successes or failures.

One patch-level source/API mismatch is explicit and fail-closed:
`event_handling/resample.py` from the 3.11.1 documentation passes `step=` to
`FillBetweenPolyCollection.set_data`, while the 3.11.0 oracle lacks that
keyword. The manifest allowlists one reference-only adapter ID for that exact
path. Promotion rejects every unlisted adapter or use by the XY engine.

### Extended environment

The 12 extended cases are described individually by
`gallery/matplotlib-3.11.1/extended-environment.json`. The generated metadata
is part of the hash/manifest contract and records:

- the pinned Ubuntu 24.04 runner and system-Python virtual environment with
  system site packages so apt's PyGObject bindings remain visible;
- exact TeX, dvipng, Ghostscript, GTK3/4, Xvfb, font, GDK Pixbuf SVG
  (`librsvg2-common`), and `colorspacious` dependencies plus preflight commands
  and TeX font files; the preflight decodes a real SVG through GDK Pixbuf;
- separate reference and xy backend choices (xy always uses the public XY
  backend; GTK is never substituted for XY);
- an empty `argv`, deterministic input or multiprocessing driver, timeout,
  and expected figure/PDF output for each source.

The extended job is deliberately unsharded and its post-run verifier requires
the exact 12 paths, successful reference and xy execution, no capture errors,
no renderer fallback, all structural/visual/semantic/behavior gates, and no
temporary waivers. A provisioned environment with failing examples is
reported as incomplete rather than accepted by the historical ratchet.

## Execution and result format

`scripts.pyplot_gallery.run_case` executes the transformed program as a real
file in a new process and process group. This preserves `__file__`, clean
`sys.argv`, `__main__` pickling, and multiprocessing spawn behavior. It forces
`XY_PYPLOT_MODE=compat` for xy runs, makes input/show calls deterministic, and
kills the entire process group on timeout. Before executing upstream code, the
harness seeds both Python's process-global `random` generator and NumPy's
legacy global generator with `19680801`; each result records the applied seed
and available generators.

Each result records:

- status, exception and traceback;
- the exact Python implementation and `major.minor.micro` interpreter version;
- stdout/stderr paths and hashes;
- duration and peak resident memory;
- warnings and capture errors;
- ordered figure captures and PNG dimensions;
- every `PdfPages.savefig` page as a frontend-canvas PNG plus the emitted PDF
  artifact hash and root page-tree count;
- figure, axes, projection, scale, limit, label, legend, colorbar, layout, and
  Artist-family semantics;
- requested and resolved pyplot mode;
- required interaction, coordinate-reporting, cursor, navigation, and
  animation classes and their behavior evidence;
- `fallback_used` from `FigureCanvasXY`.

Any compat render whose canvas reports `fallback_used=True` fails gallery
acceptance. Missing native output is a failure too; another Matplotlib renderer
cannot silently stand in for XY.

`scripts.pyplot_gallery.run_gallery` selects deterministic SHA-based shards,
runs both engines in isolated processes, writes `report.json` and `junit.xml`,
and keeps reference/xy/difference PNGs only for failed or review-required
comparisons. The top-level report repeats the selected execution interpreter;
resumption rejects cached results from another interpreter or from before this
provenance was recorded. Promotion requires every engine result to agree with
that report-level identity.

## Interaction, navigation, and animation evidence

Every manifest entry classified as `interactive`, `coordinates`, `cursor`,
`navigation`, or `animation` has a hard behavior gate in addition to its image
and semantic gates. A passing script without the required evidence fails
acceptance.

For an interactive figure, the harness installs a probe callback and sends a
real Matplotlib event object through the live canvas callback registry for
draw, resize, figure/axes enter and leave, pointer motion, button press and
release, scroll, key press and release, pick, and close. Location events use
the center of a live Axes so `inaxes` is meaningful. Results record source,
attempted, and delivered callback counts, probe delivery, and full callback
failures. Matplotlib's callback exception printer is temporarily replaced
while probing, so a source callback failure cannot be printed and silently
accepted. An xy run must use `FigureCanvasXY`.

Widgets discovered in the source namespace are operated through their public
value/activation API and receive pointer events in their own Axes. Buttons
receive a real click. Rectangle, ellipse, span, lasso, and polygon selectors
receive complete press/move/release or multi-vertex gestures, and acceptance
requires delivery of the selector's actual `onselect` callback. Selectors
disconnected after a blocking `show()` are reconnected for the deterministic
probe. Registered `xlim_changed` and `ylim_changed` callbacks
are exercised by a bounded limit change and must mutate visible state.
Draggable annotations and legends are picked and moved through the live event
path.

`coordinates` entries evaluate their real Axes formatter; XY must also expose
the resulting status text through its live toolbar state. `navigation`
entries receive a real 2-D pan and must change axes limits. The cursor example
hovers every Axes, traverses XY's widget transport,
and must request multiple distinct Matplotlib cursors. Browser canaries
separately load the exact histogram, tooltip, and
hyperlink SVG gallery exports and verify click, hover, and link behavior in
Chromium. Timers execute one deterministic callback turn with a probe in
addition to their source callbacks.

Both `pyplot.show()` and `Figure.show()` route through the harness's
nonblocking capture hook. This preserves scripts whose post-show cleanup
assumes a blocking GUI without allowing a gallery subprocess to open a real
window.

Matplotlib 3.11.0's `event_handling/resample.py` passes `step=` to
`FillBetweenPolyCollection.set_data`, although that release's method omitted
the keyword while retaining `_step` state. Compat mode accepts the exact
gallery call. The reference behavior probe installs the same narrowly-scoped
adapter and records its ID; this is a versioned source/API correction, not a
renderer fallback or per-example waiver.

Every `Animation` runs its initial, middle, and final updates. Intermediate
updates are replayed without retaining their images so stateful animations
reach the correct middle/final state. A finite sequence is exhausted up to
4096 frames; an unbounded sequence uses its declared `save_count`, or a
64-frame bound when none exists, and labels the last sample `bounded_final`.
The animation timer is exercised separately. Movie-writer examples buffer
frames while the source runs and retain first, middle, and final evidence.

Animation-required examples discard their normally blank pre-animation
`show()`/final screenshot. Their three ordered driven-frame PNGs are the
comparison captures, with the same fallback and semantic records as static
captures.

Static and interactive captures use one stable slot per live Figure identity,
in figure-creation order. A later `show()` or final capture replaces that
Figure's slot with its latest state instead of appending another image merely
because layout converged or event handling changed its PNG digest. Distinct
Figure objects are never deduplicated, including when Matplotlib reuses a
figure number after close. Multipage PDF sources are the deliberate exception:
each page save captures that page state before the source closes its Figure.

## Acceptance gates

Hard structural checks require a nonblank capture for every corresponding
figure, equal figure/capture counts, semantic parity, and these dimension
rules:

- explicit sizes: within one pixel;
- default sizes: each dimension within 2%;
- tight bounding boxes: each dimension within 5% and aspect ratio within 3%.

Axes rectangles must be within `0.02` normalized figure units with IoU at least
`0.90`. Projection, scales, directions, explicit titles and labels, legend
text, colorbar presence, and Artist-family counts must match. Explicit limits
use floating-point tolerance; autoscaled endpoints may differ by at most 5% of
the Matplotlib span.

The visual comparator composites transparency over the declared background,
uses the complete canvas, applies a 1.5-pixel Gaussian blur, and downsamples the
longest side to 256 pixels. Passing requires normalized RGB MAE no greater than
`0.08`, foreground-area ratio in `[0.67, 1.50]`, and five-pixel-dilated
foreground IoU of at least:

| Render class | IoU |
|---|---:|
| text/thin line | 0.55 |
| filled vector | 0.70 |
| raster/mesh | 0.80 |

MAE from `0.08` through `0.12`, or IoU up to `0.10` below its class threshold,
requires review. Larger differences fail. Raw differing-pixel percentage is
reporting-only.

“Blank” means the normalized foreground mask contains no foreground pixels.
This rejects a uniform synthetic canvas while permitting intentionally sparse
examples such as the first frame of a particle animation.

Performance is separate from correctness. A run above
`2 × baseline + 250 ms` warns; a run above `8 × baseline + 2 s` fails.

## Monotonic repair policy

The initial baseline at commit
`d505ef5789d8b18e23fd838300b039932dc399ce` is:

| Gate | Passing |
|---|---:|
| xy execution | 189 |
| figure/capture parity | 172 |
| exact canvas dimensions | 168 |
| tolerant visual gate | 127 |

Every failure is represented by a named temporary waiver in the checked-in
baseline; there are no implicit ignores. A previously passing gate may not
regress. A pull request may remove waiver IDs but cannot add any. Known
formatting issues link to #354 and #409–#411 in the manifest.

CI validates bytes, hashes, AST proofs, counts, and the waiver ratchet, then
runs the standard profile in eight differential shards. Failed shards upload
only their report, JUnit file, logs, and failure comparison images.

Promotion accepts disjoint reports for the same profile so those eight CI
shards remain independently hashable evidence. Every promoted report record
binds its report SHA-256, implementation commit, harness and interpreter,
input-manifest hash, emitted-manifest hash, and extended-environment hash.
Contract verification requires those records to agree with the promoted
baseline provenance.

The separate extended job installs and probes its declared dependencies under
Xvfb, runs all 12 examples in one profile, validates the actual report as
12/12, and uploads the same failure-only evidence. The dependency preflight
and compatibility result are separate checks.
