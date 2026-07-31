# `xy.pyplot` Matplotlib gallery audit — 2026-07-30

Environment:

- `xy` commit: `d505ef5789d8b18e23fd838300b039932dc399ce`
- Matplotlib: `3.11.0`
- Python: `3.14.5`
- source archives:
  - `gallery_python.zip` from Matplotlib stable, SHA-256
    `46b4cb42d5bb56cc39e2b5b2b520b38d` in its download URL
  - `gallery_jupyter.zip` from Matplotlib stable, SHA-256
    `fcaddee3a42ae2e2c41e00ae08d70347` in its download URL
- gallery inventory: 507 Python scripts and 507 matching notebooks
- execution: 507 scripts × Matplotlib/xy, isolated subprocesses, 45 second timeout

Results:

- Matplotlib completed 476/507 scripts in the local environment.
- `xy.pyplot` completed 189/507 scripts.
- 185 examples yielded paired output, comprising 316 paired figures.
- One figure was pixel-identical (`images_contours_and_fields/barcode_demo.py`).
- Six paired figures differed in canvas dimensions.

Each comparison sheet is Matplotlib 3.11.0, `xy`, and a 3×-contrast pixel
difference from left to right.

| File | Official gallery source | Observation | SHA-256 |
|---|---|---|---|
| `fancy-arrowpatch.png` | `text_labels_and_annotations/angles_on_bracket_arrows.py` | Open bracket arrows become large filled polygons. | `3c7b75884bb6f3525276ce5a139da307082fb47b78375f240507f96ec5f232b1` |
| `figure-text-only.png` | `text_labels_and_annotations/dfrac_demo.py` | A text-only figure gains a default axes and its 525×75 canvas becomes 525×120. | `4e879cdd09fb539972a3dd53775d878e402343543f49615f4d99d8860cd517d4` |
| `inset-axes.png` | `lines_bars_and_markers/scatter_hist.py`, inset-axes figure | Marginal histograms render over the main axes instead of in their inset axes. | `ba87617122354552984d0341c50ba67c9dff8a3efceef501dd7c64fed9f06128` |
| `matshow.png` | `images_contours_and_fields/matshow.py` | The Matplotlib 480×480 canvas becomes 640×480. | `65f1a37537a17ede2ec92bc709a431c327b83f9470adc85843d94f6f0d791e41` |
