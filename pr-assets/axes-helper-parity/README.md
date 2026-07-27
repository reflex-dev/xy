# Axes helper parity evidence

This evidence compares:

- Matplotlib 3.11.0
- XY before: `074122d9b702fa16bdf8b78b318eb5b483e869b3`
- XY after: `06c7aeddb413f5fed49918cff26758797bde78aa`

The example is a non-shared 2x2 scientific plot grid using
`Axes.label_outer()`. Before the fix, XY left every inner X/Y label visible.
After the fix, only labels on the outer GridSpec edges remain, matching
Matplotlib.

The product PR does not contain these assets. This branch exists only so its
immutable raw URLs can be embedded in the review description.

## Reproduction

Run `render.py` once with Matplotlib, once against the before checkout, and
once against the after checkout. Then combine the three PNGs with `montage.py`.

The checked-in images were produced at 120 DPI with the exact revisions above.
