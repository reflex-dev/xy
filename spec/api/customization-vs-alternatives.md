# Customization versus the alternatives

`spec/benchmarks/methodology.md` exists because performance claims are worthless
without a committed harness. Customization claims have the same problem and had
no equivalent, so this document is that equivalent: the question asked in each
row, the method used to answer it, the version of every library compared, and —
the part that makes it evidence rather than marketing — the rows XY loses.

A matrix where one library wins everything is evidence of nothing. If a future
edit removes the losses, it has removed the reason to believe the wins.

## Method

Same rules as the benchmark harness, adapted to a capability question.

1. **Versions are pinned and recorded.** The comparison is against the versions
   in `benchmarks/requirements-ci.in`: Plotly 6.9.0, Bokeh 3.9.1, Altair 6.2.2
   (Vega-Lite 6), Matplotlib 3.11.1. A row that changes when a competitor
   releases is a row that has to be re-checked, not silently inherited.
2. **Every row names its method.** One of: `schema` (counted from a machine
   -readable schema — reproducible by running the script named in the row),
   `code` (read from the library's source, with the symbol named), or `docs`
   (taken from the library's own documentation, which is the right source for
   an intended-contract question and the wrong one for a coverage count).
3. **Same-work comparison.** XY's per-slot DOM styling is not compared against
   Matplotlib's rcParams as if they answered the same question. Where two
   libraries solve a problem in incomparable ways the row says so instead of
   picking the framing that flatters XY.
4. **The XY column is generated, not asserted.** Everything in the XY column
   that is countable comes from `xy.styling.capabilities`, which
   `tests/test_capability_registry.py` pins to the actual implementation, and
   `tests/test_customization_comparison.py` re-checks the counts quoted below
   against it. A number here that the registry does not know about fails the
   suite rather than sitting in prose.
5. **Losses ship.** The loss table below is not an appendix. It is the reason
   the win table is credible, and it is maintained with the same care.

## What XY is genuinely better at

| Question | XY | Plotly | Vega-Lite | Bokeh | Matplotlib | Method |
| --- | --- | --- | --- | --- | --- | --- |
| Can host design tokens (`var(--brand)`) paint marks? | yes, in every renderer — resolved in Python for static export | no | no | no | no | code |
| Stable, documented DOM slot contract for chrome | 23 named slots, `data-xy-slot` | no published contract | no | partial (CSS classes, undocumented as contract) | n/a — no DOM | code |
| Tailwind classes on chart chrome | yes, per slot | no | no | partial | n/a | docs |
| Same style declaration honored by GPU, vector, and raster output | yes, by construction: one validated subset compiled once | no — the browser and Kaleido share a renderer, but there is no native vector/raster path to agree with | no | no | n/a — one renderer family | code |
| Unsupported style declaration fails loudly | yes, before ingest | no — unknown keys are dropped | schema-validated | partial | partial | code |
| Per-property record of which renderer draws what | yes, `xy.styling.capabilities`, generated and drift-tested | no | no | no | no | code |

## What XY is genuinely worse at

| Question | XY | Best alternative | Method |
| --- | --- | --- | --- |
| Total styleable attribute surface | 10 shipped mark style properties, 15 axis keys, 23 chrome slots | **Plotly**: 9,472 non-`src` leaf attributes across 49 trace types and `layout` (plotly 6.9.0) | schema |
| Chart families you can style at all | 20 mark kinds | **Plotly**: 49 trace types, including 3-D, geo, and financial families XY does not implement | schema |
| Writing a genuinely new mark | `xy.register_mark` composes existing primitives only; no custom shader | **Matplotlib**: a custom `Artist` can draw anything the backend can | docs |
| Custom rendering primitives | none — deferred from §24 v0 | **Bokeh**: custom models ship their own TypeScript | docs |
| Global style defaults as a first-class file format | theme object only | **Matplotlib**: `matplotlibrc` plus ~300 rcParams | docs |
| Per-slot styles and classes in static export | dropped — browser only | **Matplotlib**: no split to have, every style path is the export path | code |
| Colorbar styling in static export | no native channel at all | **Plotly**: colorbar attributes apply in Kaleido export | code |
| Author stylesheet in native PNG | rejected; needs `Engine.chromium` | **Plotly**: n/a — Kaleido is always a browser | code |

## Copyable claim taxonomy

The performance version of this table is at `spec/benchmarks/results.md`
§ Copyable claim taxonomy, and the rule is the same: a claim is publishable only
if it names the dimension it is true on.

| Claim shape | Safe wording | Required context |
| --- | --- | --- |
| Token themeability | "XY resolves host CSS variables into mark paint in the browser, SVG, and native PNG; Plotly, Bokeh, Vega-Lite, and Matplotlib do not." | the mechanism, the renderers, the named alternatives |
| Slot contract | "XY publishes 23 stable chrome slots as a supported contract; the alternatives compared expose no equivalent published contract." | slot count, "published contract" not "styleable" |
| Cross-renderer fidelity | "A mark style declaration XY accepts is drawn by all three renderers or rejected at build time." | the subset is validated; this is not a claim about arbitrary CSS |
| Breadth | **Do not claim breadth.** Plotly's attribute surface is roughly three orders of magnitude larger. | — |
| Extensibility | "XY marks can be extended by composing built-in primitives without forking; it does not offer custom shaders or a custom-artist API." | what the plugin can and cannot do |
| Cap/join fidelity | "`stroke-linecap` is drawn identically by all three renderers, verified per renderer; `stroke-linejoin` is not offered because the WebGL client has no join geometry." | the specific property, the specific blocker |

## The claim ladder

What is defensible depends on what has shipped, so the ladder is written down
rather than re-argued each release. A rung is earned by an artifact, not by an
opinion.

| Once this exists | You may say |
| --- | --- |
| `xy.styling.capabilities` + the generated matrix | "measurably more themeable than Plotly on the dimensions in the published capability matrix" |
| The comparison document with its loss table | "more themeable, less extensible than Matplotlib — here is the matrix, losses included" |
| `xy.register_mark` | "themeable *and* extensible, by composition" |
| A shader-level plugin API and per-slot styling in static export | revisit this table; do not extrapolate to it from here |
| — | **"most customizable" — never.** Plotly's attribute surface is roughly three orders of magnitude larger and Matplotlib's custom `Artist` is strictly more powerful. No amount of shipping changes those two facts. |

The last row is enforced rather than trusted:
`scripts/check_claim_guardrails.py` rejects "most customizable", "fully
customizable", "style anything", and "more customizable than any/all" wherever
they appear in `README.md` or `docs/`, and requires a comparative claim against
a named library to carry its dimension and its evidence.

Claims that are never defensible, regardless of context: "most customizable",
"most themeable charting library", "more extensible than Matplotlib", "as
customizable as Plotly". `scripts/check_claim_guardrails.py` rejects the first
two shapes mechanically; the other two are judgment and belong in review.
