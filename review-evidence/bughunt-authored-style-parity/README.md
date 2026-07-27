# Authored style parity evidence

Review-only evidence for `agent/bughunt-authored-style-parity`.

- Matplotlib reference: 3.11
- XY before: `2a7d6eb8a3451eeb3465df125000f2061a0d2ebc`
- XY after: `231ee5281fde8a430e742d525d3ddc55a02250f7`

`authored-style-comparison.png` compares the same dark-background bar chart
across Matplotlib, the stacked base, and the fix. It demonstrates preserved
error-bar color/width, visible default text and annotations, and authored axis
label rotation.

`marker-opacity-comparison.png` rasterizes SVG generated from the same marker
spec before and after the fix. Before, the marker fill honors `opacity=0.22`
while the cyan outline remains opaque. After, both paints use the authored
opacity.

The two `render_*.py` files contain the source plots used for the images.
These artifacts intentionally live on a review-evidence branch and are not
part of the product PR diff.
