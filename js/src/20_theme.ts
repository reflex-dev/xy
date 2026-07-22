// ---------------------------------------------------------------------------
// Colors & theming (§36: chrome inherits CSS; marks read --chart-* tokens)
// ---------------------------------------------------------------------------

function resolveCssColor(host, expr) {
  const probe = document.createElement("span");
  probe.style.display = "none";
  probe.style.color = expr;
  host.appendChild(probe);
  const rgb = getComputedStyle(probe).color;
  host.removeChild(probe);
  const m = rgb.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(/[,/\s]+/).filter(Boolean).map(Number);
  const [r, g, b, a = 1] = parts;
  return [r / 255, g / 255, b / 255, a];
}

function cssToken(el, name) {
  const v = getComputedStyle(el).getPropertyValue(name).trim();
  return v || null;
}

export function hexColor(hex) {
  const h = hex.replace("#", "");
  if (!/^(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(h)) {
    return null;
  }
  const full = h.length === 3 || h.length === 4 ? [...h].map((c) => c + c).join("") : h;
  const n = parseInt(full.slice(0, 6), 16);
  const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, a];
}

export function parseColor(host, c, fallback) {
  if (!c) return fallback;
  if (typeof c !== "string") return fallback;
  const expr = c.trim();
  if (!expr) return fallback;
  const out = expr.startsWith("#") ? hexColor(expr) : resolveCssColor(host, expr);
  if (out) return out;
  // Validated figures never land here — the Python build gate rejects
  // malformed colors (src/css.rs) — but a hand-written spec can. Say so
  // instead of silently painting the fallback color.
  if (typeof console !== "undefined" && console.warn) {
    console.warn(`xy: unresolvable color ${JSON.stringify(expr)}; using fallback`);
  }
  return fallback;
}

export function readTheme(root) {
  const text = resolveCssColor(root, "currentColor") || [0.2, 0.2, 0.2, 1];
  const withA = (c, a) => [c[0], c[1], c[2], a];
  const tok = (name) => {
    const v = cssToken(root, name);
    return v ? resolveCssColor(root, v) || null : null;
  };
  return {
    bg: tok("--chart-bg"),
    grid: tok("--chart-grid") || withA(text, 0.14),
    axis: tok("--chart-axis") || withA(text, 0.55),
    label: tok("--chart-text") || withA(text, 0.85),
  };
}

export function cssColor([r, g, b, a]: any) {
  return `rgba(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)},${a})`;
}

// Chrome *visual* defaults, one stylesheet per document. Rules live in the
// low-priority `base` cascade layer and are zero-specificity except for button
// rules, whose element/attribute selector must beat host form resets. Unlayered
// author CSS, later utility layers (including Tailwind), and inline `styles[slot]`
// therefore beat them without !important. The elements carry
// only structural inline styles (position/size/z-index/state); background,
// color, padding, border, font, and box-shadow stay overridable here.
// All colors flow through --chart-* tokens so container theming still cascades.
//
// The reduction badges and modebar's own surface defaults are scheme-aware:
// they read internal --xy-* defaults that flip to a dark palette whenever a
// `.dark` class sits on the chart root or any ancestor — the class-on-root
// convention every host we target uses (Reflex/next-themes, Radix Themes,
// Tailwind). These remain zero-specificity :where() rules, so public
// --chart-badge-* / --chart-modebar-* tokens or utility classes override them.
export const XY_CHROME_CSS = `
@layer base{
:where(.xy [data-xy-slot="title"]){text-align:center;font-size:14px;font-weight:600;color:var(--chart-text,inherit)}
:where(.xy [data-xy-slot="tooltip"]){max-width:calc(100% - 8px);max-height:calc(100% - 8px);box-sizing:border-box;white-space:normal;overflow-wrap:anywhere;overflow:auto;background:var(--chart-tooltip-bg,rgba(20,24,33,.92));color:var(--chart-tooltip-text,#fff);padding:5px 8px;border-radius:4px;font-size:11px;line-height:1.35;box-shadow:0 2px 8px rgba(0,0,0,.3)}
:where(.xy [data-xy-slot="legend"]){left:var(--xy-legend-left,auto);right:var(--xy-legend-right,auto);top:var(--xy-legend-top,auto);bottom:var(--xy-legend-bottom,auto);transform:var(--xy-legend-transform,none);max-width:var(--xy-legend-max-width);max-height:var(--xy-legend-max-height);gap:2px;font-size:11px;background:var(--chart-legend-bg,rgba(128,128,128,.08));border-radius:4px;padding:4px 8px;color:var(--chart-text,inherit)}
:where(.xy [data-xy-slot="legend_swatch"]){width:12px;height:10px;border-radius:2px;margin-right:5px}
:where(.xy [data-xy-slot="colorbar"]){color:var(--chart-text,inherit);font-size:10px}
:where(.xy [data-xy-slot="colorbar_bar"]){background:var(--xy-colorbar-gradient);border:1px solid currentColor;box-sizing:border-box}
:where(.xy [data-xy-slot="colorbar_title"]){font-weight:500}
:where(.xy [data-xy-slot="badge"]){gap:3px;font-size:11px;line-height:1.2}
:where(.xy [data-xy-slot="badge_item"]){padding:3px 6px;border-radius:4px;color:var(--chart-badge-text,var(--xy-badge-text));background:var(--chart-badge-bg,var(--xy-badge-bg));box-shadow:var(--xy-badge-shadow)}
:where(.xy){--xy-badge-text:#0f172a;--xy-badge-bg:rgba(255,255,255,.82);--xy-badge-shadow:0 1px 4px rgba(15,23,42,.14);--xy-modebar-bg:#fff;--xy-modebar-menu-bg:#fff;--xy-modebar-hover:#edf1f6;--xy-modebar-text:#5c6573;--xy-modebar-text-strong:#1b212a;--xy-modebar-text-soft:#798495;--xy-modebar-text-subtle:#9aa4b2;--xy-modebar-border:rgba(27,33,42,.12);--xy-modebar-separator:rgba(27,33,42,.08);--xy-modebar-active:#edf1f6;--xy-modebar-shadow:0 8px 24px rgba(28,32,36,.1),0 2px 6px rgba(28,32,36,.06);--xy-modebar-menu-shadow:0 8px 24px rgba(28,32,36,.12);--xy-modebar-button-shadow:0 1px 2px rgba(28,32,36,.06)}
:where(.dark .xy,.xy.dark){--xy-badge-text:#f8fafc;--xy-badge-bg:rgba(30,35,44,.88);--xy-badge-shadow:0 1px 4px rgba(0,0,0,.5);--xy-modebar-bg:#1b1d20;--xy-modebar-menu-bg:#1b1d20;--xy-modebar-hover:#282b31;--xy-modebar-text:#adb4bf;--xy-modebar-text-strong:#eceef1;--xy-modebar-text-soft:#adb4bf;--xy-modebar-text-subtle:#7f8996;--xy-modebar-border:rgba(236,238,241,.14);--xy-modebar-separator:rgba(236,238,241,.1);--xy-modebar-active:#282b31;--xy-modebar-shadow:0 8px 24px rgba(0,0,0,.3),0 2px 6px rgba(0,0,0,.22);--xy-modebar-menu-shadow:0 8px 24px rgba(0,0,0,.34);--xy-modebar-button-shadow:0 1px 2px rgba(0,0,0,.22)}
:where(.xy [data-xy-slot="modebar"]){align-items:center;gap:4px;background:var(--chart-modebar-bg,var(--xy-modebar-bg));border:1px solid var(--xy-modebar-border);border-radius:10px;padding:2px;color:var(--xy-modebar-text);box-shadow:var(--xy-modebar-shadow);font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:16px;line-height:normal;cursor:grab;touch-action:none;user-select:none;will-change:left,top}
:where(.xy [data-xy-slot="modebar"].xy-dragging){cursor:grabbing}
:where(.xy [data-xy-slot="modebar"])::before{position:absolute;top:50%;right:100%;width:34px;height:40px;content:"";pointer-events:none;transform:translateY(-50%)}
:where(.xy) button[data-xy-slot="modebar_button"]{box-sizing:border-box;display:inline-flex;min-width:28px;width:auto;height:28px;align-items:center;justify-content:center;gap:4px;padding:0 6px;border:1px solid transparent;background:transparent;border-radius:8px;color:var(--xy-modebar-text-soft);cursor:pointer;font:inherit;outline:none}
:where(.xy) button[data-xy-slot="modebar_button"]:hover:not(:disabled){background:var(--chart-modebar-active,var(--xy-modebar-hover));color:var(--xy-modebar-text-strong)}
:where(.xy) button[data-xy-slot="modebar_button"]:disabled{cursor:default}
:where(.xy) button[data-xy-slot="modebar_button"][aria-expanded="true"]{background:var(--chart-modebar-active,var(--xy-modebar-hover));color:var(--xy-modebar-text-strong);box-shadow:none}
:where(.xy) button[data-xy-slot="modebar_button"] svg{display:block;width:14px;height:14px}
:where(.xy [data-xy-modebar-drag-handle]){position:absolute;top:50%;left:0;z-index:1;display:grid;width:26px;height:28px;place-items:center;border:1px solid var(--xy-modebar-border);border-radius:7px;background:var(--chart-modebar-bg,var(--xy-modebar-bg));color:var(--xy-modebar-text-strong);box-shadow:0 2px 8px rgba(28,32,36,.1);opacity:0;pointer-events:none;transform:translate3d(-75%,-50%,0);transition:opacity 120ms ease,transform 160ms cubic-bezier(.23,1,.32,1)}
:where(.dark .xy [data-xy-modebar-drag-handle],.xy.dark [data-xy-modebar-drag-handle]){box-shadow:0 2px 8px rgba(0,0,0,.24)}
:where(.xy [data-xy-modebar-drag-handle]) svg{width:14px;height:14px}
:where(.xy [data-xy-modebar-drag-handle])::after{position:absolute;top:-4px;right:-5px;bottom:-4px;width:8px;content:""}
:where(.xy [data-xy-slot="modebar"]:focus-within [data-xy-modebar-drag-handle],.xy [data-xy-slot="modebar"].xy-dragging [data-xy-modebar-drag-handle]){opacity:1;pointer-events:auto;transform:translate3d(calc(-100% - 5px),-50%,0)}
:where(.xy [data-xy-slot="modebar"].xy-dragging [data-xy-modebar-drag-handle]){cursor:grabbing}
:where(.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"])::before{right:auto;left:100%}
:where(.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"] [data-xy-modebar-drag-handle]){right:0;left:auto;transform:translate3d(75%,-50%,0)}
:where(.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"] [data-xy-modebar-drag-handle])::after{right:auto;left:-5px}
:where(.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"]:focus-within [data-xy-modebar-drag-handle],.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"].xy-dragging [data-xy-modebar-drag-handle]){transform:translate3d(calc(100% + 5px),-50%,0)}
@media (hover:hover) and (pointer:fine){:where(.xy [data-xy-slot="modebar"])::before{pointer-events:auto}:where(.xy [data-xy-slot="modebar"]:hover [data-xy-modebar-drag-handle]){opacity:1;pointer-events:auto;transform:translate3d(calc(-100% - 5px),-50%,0)}:where(.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"]:hover [data-xy-modebar-drag-handle]){transform:translate3d(calc(100% + 5px),-50%,0)}}
:where(.xy [data-xy-modebar-separator]){display:block;flex:0 0 auto;width:1px;height:16px;background:var(--xy-modebar-border)}
:where(.xy [data-xy-modebar-tool-group]){display:flex;align-items:center;gap:2px}
:where(.xy) button[data-xy-slot="modebar_button"][data-xy-modebar-menu-trigger]{min-width:60px;gap:3px;padding:0 5px;color:var(--xy-modebar-text-strong);font-size:12px;font-variant-numeric:tabular-nums}
:where(.xy) button[data-xy-slot="modebar_button"][data-xy-modebar-select-trigger]{min-width:47px;gap:4px;padding:0 6px}
:where(.xy) button[data-xy-slot="modebar_button"][data-xy-modebar-action="pan"],:where(.xy) button[data-xy-slot="modebar_button"][data-xy-modebar-export-trigger]{min-width:28px;width:28px;padding:0}
:where(.xy [data-xy-modebar-select-icon]){display:flex;flex:0 0 auto}
:where(.xy [data-xy-modebar-menu-indicator]){display:flex;flex:0 0 auto;transition:transform .15s}
:where(.xy) button[data-xy-slot="modebar_button"] [data-xy-modebar-menu-indicator] svg{width:10px;height:10px;color:var(--xy-modebar-text-subtle)}
:where(.xy [data-xy-modebar-menu]){box-sizing:border-box;width:144px;gap:0;padding:4px;background:var(--chart-modebar-bg,var(--xy-modebar-menu-bg));border:1px solid var(--xy-modebar-border);border-radius:8px;color:var(--xy-modebar-text);box-shadow:var(--xy-modebar-menu-shadow)}
:where(.xy [data-xy-modebar-export-menu]){width:112px}
:where(.xy) button[data-xy-modebar-menu-item]{display:grid;width:100%;height:26px;min-height:26px;grid-template-columns:14px 1fr;align-items:center;gap:8px;padding:4px 6px;border:0;border-radius:6px;background:transparent;color:var(--xy-modebar-text);font-size:12px;line-height:16px;text-align:left;white-space:nowrap}
:where(.xy) button[data-xy-modebar-menu-item]:hover:not(:disabled),:where(.xy) button[data-xy-modebar-menu-item]:focus-visible{background:var(--chart-modebar-active,var(--xy-modebar-hover));color:var(--xy-modebar-text-strong);outline:none}
:where(.xy) button[data-xy-modebar-menu-item]:disabled{cursor:not-allowed;opacity:.45}
:where(.xy [data-xy-modebar-view-history]){display:grid;grid-template-columns:1fr 1fr;gap:2px}
:where(.xy [data-xy-modebar-view-history]) button[data-xy-modebar-menu-item]{display:inline-flex;justify-content:center;gap:6px}
:where(.xy [data-xy-modebar-menu-separator]){display:block;height:1px;margin:4px -4px;background:var(--xy-modebar-separator);transform:scaleY(.5);transform-origin:center}
:where(.xy [data-xy-modebar-menu-icon]){display:flex;width:14px;flex:0 0 auto}
:where(.xy [data-xy-modebar-menu-icon] svg){width:14px;height:14px}
:where(.xy) button[data-xy-slot="modebar_button"].xy-active{border-color:var(--xy-modebar-border);background:var(--chart-modebar-bg,var(--xy-modebar-bg));color:var(--xy-modebar-text-strong);box-shadow:var(--xy-modebar-button-shadow)}
:where(.xy [data-xy-slot="selection"]){border:1px solid var(--chart-selection,rgba(90,140,240,.9));background:var(--chart-selection-fill,rgba(90,140,240,.15))}
:where(.xy [data-xy-slot="selection"][data-xy-band="zoom"]){border-color:var(--chart-zoom-selection,rgba(120,120,120,.9));background:var(--chart-zoom-selection-fill,rgba(120,120,120,.12))}
:where(.xy [data-xy-selection-lasso]){fill:var(--chart-selection-fill,rgba(90,140,240,.15));stroke:var(--chart-selection,rgba(90,140,240,.9));stroke-width:1.5;stroke-linejoin:round;pointer-events:none}
:where(.xy [data-xy-selection-lasso-handle]){fill:var(--chart-bg,#fff);stroke:var(--chart-selection,rgba(90,140,240,.9));stroke-width:1.5;cursor:grab;pointer-events:all}
:where(.xy [data-xy-selection-lasso-handle][data-xy-active]){cursor:grabbing;fill:var(--chart-selection,rgba(90,140,240,.9))}
:where(.xy [data-xy-slot="crosshair_x"],.xy [data-xy-slot="crosshair_y"]){background:var(--chart-crosshair,rgba(15,23,42,.42))}
:where(.xy [data-xy-slot="tick_label"]){color:var(--chart-text,inherit)}
:where(.xy [data-xy-slot="axis_title"]){color:var(--chart-text,inherit);font-size:12px}
:where(.xy [data-xy-slot="annotation_label"]){font-size:11px;line-height:1.2;font-weight:500;color:var(--chart-annotation-text,var(--chart-text,inherit))}
:where(.xy [data-xy-slot="canvas"]){cursor:var(--chart-cursor,crosshair)}
:where(.xy [data-xy-slot="canvas"][data-xy-dragmode="pan"]){cursor:var(--chart-cursor-pan,grab)}
:where(.xy [data-xy-slot="canvas"][data-xy-dragmode="none"]){cursor:default}
:where(.xy [data-xy-slot="canvas"]:focus-visible){outline:2px solid var(--chart-focus,#aa99ec);outline-offset:2px}
:where(.xy) button[data-xy-slot="modebar_button"]:focus-visible{box-shadow:0 0 0 2px var(--chart-focus,#aa99ec),0 0 0 3px var(--chart-modebar-bg,var(--xy-modebar-bg));outline:none}
@media (prefers-reduced-motion:reduce){:where(.xy [data-xy-slot="modebar"]),:where(.xy) button[data-xy-slot="modebar_button"],:where(.xy [data-xy-modebar-menu-indicator]){transition-duration:0s!important}:where(.xy [data-xy-modebar-drag-handle]){transform:translate3d(calc(-100% - 5px),-50%,0);transition:opacity 120ms ease}:where(.xy [data-xy-slot="modebar"][data-xy-modebar-drag-peek-side="right"] [data-xy-modebar-drag-handle]){transform:translate3d(calc(100% + 5px),-50%,0)}}
@media (forced-colors:active){:where(.xy [data-xy-slot="modebar"],.xy [data-xy-slot="tooltip"]){border:1px solid CanvasText}:where(.xy) button[data-xy-slot="modebar_button"].xy-active{outline:2px solid Highlight}:where(.xy [data-xy-slot="canvas"]:focus){outline:2px solid Highlight}}
}
/* VS Code's Jupyter webview wraps ipywidget outputs in an opaque white card so
   widgets that assume a light page stay legible on dark editor themes — the
   same role as matplotlib's always-opaque white figure patch, so unthemed
   charts keep it. A chart that brings its own background (theme(background=),
   marked data-xy-own-bg) would sit in a white frame instead, so only those
   outputs drop the backdrop. !important because the host rule this overrides
   carries higher specificity; it stays outside the base layer because it
   overrides host CSS rather than providing an overridable default. */
.cell-output-ipywidget-background:has(.xy[data-xy-own-bg]){background:transparent!important}
`;

// Inject XY_CHROME_CSS once per DOM root (document head or shadow root), so
// multiple charts on one page share a single stylesheet.
export function ensureChromeStylesheet(node) {
  let root = node && node.getRootNode ? node.getRootNode() : document;
  const isShadow = typeof ShadowRoot !== "undefined" && root instanceof ShadowRoot;
  if (!isShadow && !(root instanceof Document)) root = document; // detached subtree
  const scope = isShadow ? root : (root.head || document.head || root.documentElement);
  if (!scope || !scope.querySelector) return;
  if (scope.querySelector("style[data-xy-chrome]")) return;
  const style = document.createElement("style");
  style.setAttribute("data-xy-chrome", "");
  style.textContent = XY_CHROME_CSS;
  scope.appendChild(style);
}

export function safeCssPaint(host, expr, fallback = [0.5, 0.5, 0.5, 1]) {
  const parsed = parseColor(host, expr, fallback);
  const color = Array.isArray(parsed) && parsed.length >= 4 && parsed.every(Number.isFinite)
    ? parsed
    : fallback;
  return cssColor(color);
}
