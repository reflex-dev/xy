# Finite-line source identity

Baseline: `4dffbc76` (native ABI48, renderer protocol14). The candidate changes
finite M4 lines from fused coordinate output to one index-selection/gather pass,
ships those canonical indices as `source_rows`, and uses the existing client
source-map reader. No Rust or protocol change is needed. Empty windows omit the
map; ordinary finite direct lines retain implicit identity.

## Reproduced failure and corrected contract

The browser generated pointer and keyboard requests against real standalone
geometry; Python `channel.handle_message` resolved those requests against the
canonical figure. Before the fix, the home fixture displayed x77 but sent
index49, and the exact reply returned x49. Initial and refined fixtures failed
the same source-identity contract. Independent transport tests subsequently
posted actual browser messages to a loopback Python dispatcher and consumed the
actual replies with the original fixture CSP unchanged.

The first keyboard regression was inadequate: `End` generated no new request
because line marks were excluded from point traversal, and the test reused the
previous pointer readout. The corrected implementation uses the registry's
`sampleNav` capability, without enabling GPU `pointPick` or line brush selection.
Tests require a distinct keyboard request and source row, the position
announcement, and an `Enter` callback for that new row. Traversal covers retained
direct/M4 samples rather than every canonical row at once.

An exact reply also exposed a bound-field error: core y became
1000000000.123456 while its authored `reading` alias retained the provisional
999999999.8333335. Same-trace line x/y aliases now refresh from exact channels.
Bound names that collide with core keys (x_kind, y_kind, index, trace, x, y)
remain available to authored tooltip fields/title through private lookup storage;
they do not overwrite the event row's coordinates, kind metadata or identity.
The existing `name` series pseudo-field is unchanged. This does not transport
arbitrary unbound table fields or add a formatter grammar.

## Geometry and payload measurements

`baseline-1..3.json` and `candidate-1..3.json` record alternating fresh processes,
three payload builds per case, identical interpreter/NumPy/native library and
720×320 deterministic fixtures. `summary.json` compares all nine cases. The
geometry SHA256 covers x/y metadata and emitted f32 bytes. All geometry hashes
and mark counts match baseline exactly.

| Case | Marks | Baseline bytes | Candidate bytes |
|---|---:|---:|---:|
| 1k finite/direct | 1,000 | 8,000 | 8,000 |
| 100k finite/M4 | 1,675 | 13,400 | 20,100 |
| 1M finite/M4 | 2,717 | 21,736 | 32,604 |
| 1M one gap | 2,717 | 32,616 | 32,616 |
| 1M fragmented | 24,380 | 332,568 | 332,568 |

The map adds four bytes per emitted finite M4 sample, a 50% increase over its
two f32 geometry coordinates. It is not four bytes per canonical input row.
Initial and refinement maps are uint32; the existing source-row limit is checked
before conversion instead of silently wrapping larger row IDs.

Process-median timings vary, including on gap paths whose selection is unchanged.
All individual samples and process medians are retained in the raw records;
these local measurements do not establish a speed advantage or a general timing regression.
FPS, memory and the fragmented renderer's draw-call cost are not measured here.

## Reproduce

Use a matching ABI48 native library and an environment containing the project's
declared development dependencies. Run the candidate's instrumented harness for
both imports, changing `PYTHONPATH` between the baseline and candidate source:

```bash
export XY_NATIVE_LIB=/absolute/path/to/libxy_core.so
PYTHONPATH=/absolute/baseline/python uv run --no-sync python \
  /absolute/candidate/scripts/bench_line_gaps.py --geometry-hashes --output baseline.json
PYTHONPATH=/absolute/candidate/python uv run --no-sync python \
  /absolute/candidate/scripts/bench_line_gaps.py --geometry-hashes --output candidate.json
```

The output includes package/source/native hashes. The default benchmark output
is unchanged when `--geometry-hashes` is absent. Focused tests are
`tests/test_line_pick_identity.py`, `tests/test_accessibility_contract.py` and
`tests/test_static_client_security.py`. Browser fixtures can be served through
the saved environment's loopback test adapter; file URLs are blocked by its
browser policy. The CLI PNG test's environment failure is not an export pass.

The source changes in 52_tooltip/53_interaction overlap files touched by pending
PRs509/521, but add no shared-axis tooltip or time-format feature. Those PRs must
reconcile these row-identity changes when rebasing. Unverified smooth/step hover
highlight placement remains separate from this patch and pending highlight work.
