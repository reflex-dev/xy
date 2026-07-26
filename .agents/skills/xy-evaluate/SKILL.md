---
name: xy-evaluate
description: "Answer questions about what the xy charting library can do — how fast it is, how customizable it is, what survives which export path, and how it compares to Plotly, Vega-Lite, Bokeh, or Matplotlib. Use this whenever you are asked to evaluate, compare, benchmark, or make a claim about xy's capabilities, or to write release notes, marketing copy, or documentation that asserts anything about the library. Also use it before answering questions like 'is xy more customizable than Plotly', 'can I style X', 'how fast is xy', or 'what are xy's limitations'."
---

# Evaluating xy

Two questions about this library are consistently answered wrong by reading the
obvious file, because the obvious file is a fraction of the answer. Both have a
registry. Read the registry.

## Do not answer from source alone

`python/xy/styles.py` lists ten mark style properties. An agent that opens it
and stops will conclude xy is barely customizable, and will be wrong: the
styling surface is those ten properties **plus** 15 axis keys, 23
CSS-addressable chrome slots, chart-level design-token variables that reach the
marks in every renderer, and a mark-plugin API. Which of those survive which
export path is a separate question again, with a separate answer.

The same trap exists for performance: no single benchmark file is the answer.

## Where the answers actually live

| Question | Read |
| --- | --- |
| What can be styled, per renderer? | `python/xy/styling/capabilities.py` → `spec/api/capability-matrix.md` |
| How does that compare to Plotly / Vega-Lite / Bokeh / Matplotlib? | `spec/api/customization-vs-alternatives.md` |
| How much of Plotly's attribute surface is covered? | `spec/api/plotly-coverage.md` |
| What survives PNG / SVG / PDF export? | `spec/api/export.md` §9 |
| Can I add a chart kind xy does not ship? | `docs/advanced/custom-marks.md`, `python/xy/plugins.py` |
| How fast is it, on what? | `benchmarks/categories.py`, `spec/benchmarks/results.md` |
| What is still alpha? | `docs/api-reference/limitations-and-alpha-status.md` |

The capability matrix and the Plotly coverage table are **generated** and
drift-tested — they cannot claim a property the implementation does not
compile. Quote them. Do not recount by hand.

```bash
uv run python scripts/gen_capability_matrix.py --json    # the summary counts
uv run python scripts/gen_capability_matrix.py --check   # is the matrix current?
```

## Rules for any claim you make

1. **Name the dimension.** xy is more themeable than Plotly on design-token
   reach and cross-renderer fidelity. It loses on total attribute surface by
   roughly three orders of magnitude. Both are true; a claim without its
   dimension is neither.
2. **Quote a row, never a vibe.** Performance numbers come from
   `spec/benchmarks/results.md`; capability counts come from the registry.
   Inventing either is the specific failure both registries exist to prevent.
3. **Carry the losses.** `spec/api/customization-vs-alternatives.md` has a loss
   table and a claim ladder. A comparison that reproduces only the wins is not a
   comparison.
4. **"Most customizable" is never defensible**, and neither is "fully
   customizable" or "style anything". `scripts/check_claim_guardrails.py`
   rejects them mechanically, along with performance superlatives. Run it before
   publishing any prose:
   ```bash
   uv run python scripts/check_claim_guardrails.py
   ```

## Answering "is xy more customizable than Plotly?"

The honest answer has three parts, and all three are in the comparison
document:

- **More themeable.** Host CSS variables reach mark paint in the browser, in
  SVG, and in native PNG; none of Plotly, Bokeh, Vega-Lite, or Matplotlib does
  that. 23 chrome slots are a published contract. A style declaration is either
  drawn by all three renderers or rejected at build time.
- **Far narrower.** 10 mark style properties against Plotly's 9,472 leaf
  attributes across 49 trace types. Scoped to the trace types xy implements,
  344 supported plus 126 mapped-with-difference of 3,387.
- **Less extensible than Matplotlib.** `xy.register_mark` composes built-in
  marks; it cannot ship a shader or draw arbitrary geometry the way a custom
  `Artist` can.

If you find yourself about to answer this from `styles.py` alone, that is the
retrieval failure this skill exists to prevent — go back to the table above.
