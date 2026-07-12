/**
 * xy render client.
 *
 * A thin GPU render client (design dossier §32): receives a data-less spec +
 * offset-encoded f32 columns as raw binary (§29 — no JSON numbers, no parse),
 * uploads them once to WebGL2 buffers, and draws with instanced/point
 * primitives. Pan/zoom is a uniform update — it never touches data buffers (§7).
 *
 * Full scatter support:
 *  - per-point color: constant, continuous (colormap LUT), categorical (palette)
 *  - per-point size: constant or continuous (mapped to a px range)
 *  - GPU picking → exact-row hover tooltip (§7/§17 Tier-0 hover; exact values
 *    come from the kernel's f64 canonical store, §16)
 *  - Tier-2 density surface for massive scatter (§5): a kernel-binned count grid
 *    uploaded as a log-normalized R8 texture and colormapped at composite time,
 *    re-binned on zoom via a kernel round-trip (stale grid stays drawn until
 *    then, §17)
 *
 * Dependency-free: this file is the whole client. DOM is used only for chrome —
 * title, axis tick labels, legend, tooltip (§7).
 */

"use strict";

const PROTOCOL = 3;
