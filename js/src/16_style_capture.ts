// Browser computed-style capture: the live cascade as a ResolvedStyleSnapshot.
//
// The client-side half of the two-resolver architecture (wire-protocol §8):
// walk every rendered `data-xy-slot` element, read the allowlisted computed
// properties (concrete used values by definition — no var(), no relative
// units survive getComputedStyle), intern identical declarations, and emit
// the same payload shape `python/xy/styling/resolved.py` validates on
// arrival. Never called from the hover or animation path: the kernel invokes
// it only for an explicit `style_snapshot_request`, after fonts and layout
// settle (54_kernel.ts).

import type { ResolvedStyleSnapshot, StyleSnapshotInstance } from "./14_style_snapshot";
import { STYLE_SNAPSHOT_PROPERTIES, STYLE_SNAPSHOT_VERSION } from "./14_style_snapshot";

// Computed values that carry no styling information for a slot: recording
// them would bloat declarations without distinguishing anything (interning
// still works, but the payload budget is finite and "none" says nothing).
// Fully-transparent background is the browser's spelling of "unpainted",
// which is exactly the writers' default — absence, not a declaration.
const SKIP_VALUES = new Set(["", "none", "normal", "auto", "rgba(0, 0, 0, 0)"]);

// Schema properties whose computed form is a shorthand serialization: the
// computed `background` carries position/size tokens (`0% 0% / auto`) that
// are serialization sugar, not styling — the schema's concreteness gate
// rightly refuses them (the smoke caught exactly this). Capture reads the
// concrete longhand and records it under the schema's name.
const CAPTURE_SOURCE: Record<string, string> = { background: "background-color" };

// SVG presentation properties compute on EVERY element — an HTML tick label
// reports `fill: rgb(0, 0, 0)` (the SVG initial paint) it never uses. The
// writers prefer `fill` over `color`, so capturing that phantom black would
// outrank the element's real text color (the smoke caught exactly this).
// These properties are real styling only on SVG elements.
const SVG_ONLY_PROPERTIES = new Set([
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-opacity",
  "stroke-width",
]);

// Chart tokens ride the snapshot's token bag; they live as custom
// properties on the chart root.
const TOKEN_PREFIXES = ["--chart-", "--xy-"];

function num(value: number): number {
  // Geometry to 1/100 px: sub-centipixel noise is rendering jitter, and
  // stable payload bytes matter more (canonical-ordering contract).
  return Math.round(value * 100) / 100;
}

export function captureStyleSnapshot(
  root: HTMLElement,
  opts?: { styleEpoch?: number; states?: readonly string[] },
): ResolvedStyleSnapshot {
  const doc = root.ownerDocument;
  const win = doc.defaultView;
  if (!win) throw new Error("style capture needs a live window");
  const rootRect = root.getBoundingClientRect();
  const rootStyle = win.getComputedStyle(root);

  const declarations: Record<string, string | number>[] = [];
  const index = new Map<string, number>();
  const instances: StyleSnapshotInstance[] = [];
  const perSlotCount = new Map<string, number>();

  const elements = root.querySelectorAll<HTMLElement>("[data-xy-slot]");
  for (const el of elements) {
    const slot = el.dataset.xySlot;
    if (!slot) continue;
    // Only chrome the document is actually rendering: a hidden tooltip or a
    // closed modebar menu has no boxes, and a clean capture must not invent
    // state-gated chrome that is not on screen.
    if (el.getClientRects().length === 0) continue;
    const style = win.getComputedStyle(el);
    const isSvg = el instanceof win.SVGElement;
    const decl: Record<string, string | number> = {};
    for (const prop of STYLE_SNAPSHOT_PROPERTIES) {
      if (!isSvg && SVG_ONLY_PROPERTIES.has(prop)) continue;
      const value = style.getPropertyValue(CAPTURE_SOURCE[prop] ?? prop).trim();
      if (!value || SKIP_VALUES.has(value)) continue;
      decl[prop] = value;
    }
    const key = JSON.stringify(
      Object.keys(decl)
        .sort()
        .map((k) => [k, decl[k]]),
    );
    let at = index.get(key);
    if (at === undefined) {
      at = declarations.length;
      index.set(key, at);
      declarations.push(decl);
    }
    const nth = perSlotCount.get(slot) ?? 0;
    perSlotCount.set(slot, nth + 1);
    const rect = el.getBoundingClientRect();
    const instance: StyleSnapshotInstance = {
      s: slot,
      d: at,
      q: [String(nth)],
      g: [
        num(rect.left - rootRect.left),
        num(rect.top - rootRect.top),
        num(rect.width),
        num(rect.height),
      ],
    };
    if (el.childElementCount === 0) {
      const text = (el.textContent ?? "").trim();
      if (text) (instance as { c?: string }).c = text.slice(0, 200);
    }
    instances.push(instance);
  }

  const tokens: Record<string, string | number> = {};
  for (const prefix of TOKEN_PREFIXES) {
    // Inline root tokens are the authored/theme values the client applied;
    // computed custom properties are not enumerable, so read the ones the
    // chart itself declares on its root style attribute.
    for (const name of Array.from(root.style)) {
      if (name.startsWith(prefix)) {
        const value = rootStyle.getPropertyValue(name).trim();
        if (value) tokens[name] = value;
      }
    }
  }

  const dpr = win.devicePixelRatio || 1;
  const scheme = rootStyle.colorScheme.includes("dark") ? "dark" : "light";
  return {
    version: STYLE_SNAPSHOT_VERSION,
    style_epoch: opts?.styleEpoch ?? 0,
    environment: {
      width: num(rootRect.width),
      height: num(rootRect.height),
      dpr,
      color_scheme: scheme as "light" | "dark",
    },
    tokens,
    states: opts?.states ?? [],
    unrepresentable: [],
    declarations,
    instances,
  };
}

// Layout/fonts settle barrier for capture: fonts.ready, then two macrotask
// ticks. setTimeout rather than requestAnimationFrame — headless capture
// hosts throttle rAF on unfocused pages, and a capture must settle there
// exactly like it settles in a notebook.
export async function styleCaptureSettled(doc: Document): Promise<void> {
  try {
    await doc.fonts?.ready;
  } catch {
    // A document without FontFaceSet still captures; there is nothing to
    // wait for.
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}
