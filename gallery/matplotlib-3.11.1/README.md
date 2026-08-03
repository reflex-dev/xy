# Matplotlib 3.11.1 source / 3.11.0 oracle gallery contract

This directory vendors the 459 non-3-D Python examples selected from the exact
Matplotlib `stable` gallery archives supplied on 2026-07-30. The documentation
build is Matplotlib 3.11.1; the separately pinned compatibility oracle is the
released Matplotlib 3.11.0 wheel. Files below `examples/` are byte-for-byte
copies: do not format, lint, or edit them.

The supplied Python and Jupyter archives each contain the same 507 examples;
the 48 three-dimensional examples are excluded from XY's runnable contract.
The notebooks are not duplicated here. `manifest.json` records both archive
hashes, every included source and notebook hash, and a normalized AST proof
that each notebook's code cells equal its matching Python source after the
gallery module docstring is removed.

Of the 459 included sources, 437 directly import `matplotlib.pyplot` and are valid
drop-in replacement tests. The remaining 22 directly exercise Matplotlib
font, backend, or GUI embedding APIs and are retained as `non_pyplot` coverage
rather than misreported as `xy.pyplot` failures.

`baseline.json` is the current monotonic acceptance record. It stores the
exact xy implementation commit, current harness and manifest hashes, and the
SHA-256 of the standard and extended reports promoted into it. A passing
execution, figure structure, canvas dimension, semantic result, behavior
probe, or tolerant visual result may not regress. Temporary waivers may only
be removed; adding a new waiver fails the base-branch comparison.

The supplied 3.11.1 gallery's `event_handling/resample.py` passes `step=` to
`FillBetweenPolyCollection.set_data`, while the 3.11.0 oracle omits that
keyword. The manifest explicitly permits one reference-only adapter ID for
that exact source. Every other adapter, path, or engine is rejected during
promotion.

`extended-environment.json` is the executable setup contract for the 12
extended examples. It pins the Ubuntu runner, system and Python dependencies,
required TeX/font files, per-engine backend, clean argument vector,
deterministic input or multiprocessing driver, timeout, and expected output
for every source. Matplotlib reference runs may use GTK3/4 under Xvfb where an
upstream example requires those managers; xy runs always use
`module://xy.backends.backend_xy`.

Rebuild the generated files only from the two provenance-locked archives:

```console
python -m scripts.pyplot_gallery.contract build \
  --python-archive /path/to/gallery_python.zip \
  --notebook-archive /path/to/gallery_jupyter.zip \
  --audit-summary /path/to/gallery-audit/summary.json
python -m scripts.pyplot_gallery.contract check
python -m scripts.pyplot_gallery.extended_environment check
```

Run a deterministic differential shard with:

```console
python -m scripts.pyplot_gallery.run_gallery \
  --output /tmp/xy-gallery-0 \
  --profile standard \
  --shard 0/8
```

Interactive and animation-classified examples also run deterministic live
canvas behavior probes. Reports record callback/event delivery, widget
operations, timer turns, and initial/middle/final animation updates. Animation
captures are the three driven frames rather than a blank pre-animation
`show()` screenshot. Missing or failed required behavior is a hard ratchet
failure.

The extended CI image first runs the environment preflight under Xvfb, then
runs the unsharded `--profile extended` corpus and applies:

```console
python -m scripts.pyplot_gallery.extended_environment \
  verify-report /path/to/report.json
```

That final check requires all 12 examples from both engines, their expected
captures or PDF output, behavior evidence, every structural/visual/semantic
gate, `fallback_used=false`, and zero temporary waivers. Installing the
dependencies alone never counts as compatibility.

Matplotlib's license and required copyright notice are retained in `LICENSE`.
The archive URLs and SHA-256 digests are recorded in `provenance.json`.
The complete contract is retained in the repository and exercised by CI. It is
intentionally excluded from xy source distributions, which contain only the
inputs needed to build and install the package.
