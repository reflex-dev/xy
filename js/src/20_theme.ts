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
// low-priority `base` cascade layer and use :where(...) for ZERO specificity.
// Unlayered author CSS, later utility layers (including Tailwind), and inline
// `styles[slot]` therefore beat them without !important. The elements carry
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
:where(.xy){--xy-badge-text:#0f172a;--xy-badge-bg:rgba(255,255,255,.82);--xy-badge-shadow:0 1px 4px rgba(15,23,42,.14);--xy-modebar-bg:rgba(255,255,255,.78);--xy-modebar-menu-bg:rgba(255,255,255,.94);--xy-modebar-border:rgba(128,128,128,.18);--xy-modebar-menu-border:rgba(128,128,128,.22);--xy-modebar-active:rgba(128,128,128,.2);--xy-modebar-shadow:0 1px 4px rgba(0,0,0,.08);--xy-modebar-menu-shadow:0 5px 18px rgba(15,23,42,.18)}
:where(.dark .xy,.xy.dark){--xy-badge-text:#f8fafc;--xy-badge-bg:rgba(30,35,44,.88);--xy-badge-shadow:0 1px 4px rgba(0,0,0,.5);--xy-modebar-bg:rgba(37,42,52,.9);--xy-modebar-menu-bg:rgba(30,35,44,.97);--xy-modebar-border:rgba(255,255,255,.14);--xy-modebar-menu-border:rgba(255,255,255,.16);--xy-modebar-active:rgba(255,255,255,.16);--xy-modebar-shadow:0 1px 4px rgba(0,0,0,.5);--xy-modebar-menu-shadow:0 8px 24px rgba(0,0,0,.6)}
:where(.xy [data-xy-slot="modebar"]){gap:1px;background:var(--chart-modebar-bg,var(--xy-modebar-bg));border:1px solid var(--xy-modebar-border);border-radius:4px;padding:1px;box-shadow:var(--xy-modebar-shadow)}
:where(.xy [data-xy-slot="modebar_button"]){width:24px;height:24px;padding:0;border:none;background:transparent;border-radius:3px;color:var(--chart-text,currentColor);cursor:pointer}
:where(.xy [data-xy-modebar-drag-handle]){position:relative;width:22px;margin-right:4px;cursor:move}
:where(.xy [data-xy-modebar-drag-handle])::after{content:"";position:absolute;top:4px;right:-3px;bottom:4px;width:1px;background:rgba(128,128,128,.28);pointer-events:none}
:where(.xy [data-xy-modebar-menu-trigger]){width:auto;min-width:48px;gap:1px;padding:0 4px;font-size:11px;font-variant-numeric:tabular-nums}
:where(.xy [data-xy-modebar-select-trigger]){width:auto;min-width:42px;gap:2px;padding:0 4px}
:where(.xy [data-xy-modebar-select-icon]){display:flex;flex:0 0 auto}
:where(.xy [data-xy-modebar-menu-indicator]){display:flex;flex:0 0 auto;transition:transform .15s}
:where(.xy [data-xy-modebar-menu-indicator] svg){width:11px;height:11px}
:where(.xy [data-xy-modebar-menu]){min-width:148px;gap:1px;padding:4px;background:var(--chart-modebar-bg,var(--xy-modebar-menu-bg));border:1px solid var(--xy-modebar-menu-border);border-radius:7px;box-shadow:var(--xy-modebar-menu-shadow);backdrop-filter:blur(8px)}
:where(.xy [data-xy-modebar-menu-item]){width:100%;height:28px;justify-content:flex-start;padding:0 9px;border-radius:4px;text-align:left;white-space:nowrap}
:where(.xy [data-xy-modebar-menu-item]:hover,.xy [data-xy-modebar-menu-item]:focus-visible){background:var(--chart-modebar-active,var(--xy-modebar-active));outline:none}
:where(.xy [data-xy-modebar-menu-item][data-xy-separator]){margin-top:3px;border-top:1px solid rgba(128,128,128,.2);border-radius:0 0 4px 4px}
:where(.xy [data-xy-modebar-menu-icon]){display:flex;width:16px;margin-right:7px}
:where(.xy [data-xy-modebar-menu-icon] svg){width:14px;height:14px}
:where(.xy [data-xy-slot="modebar_button"].xy-active){background:var(--chart-modebar-active,var(--xy-modebar-active))}
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
:where(.xy [data-xy-slot="canvas"]:focus-visible,.xy [data-xy-slot="modebar_button"]:focus-visible){outline:2px solid var(--chart-focus,#2563eb);outline-offset:2px}
@media (prefers-reduced-motion:reduce){:where(.xy [data-xy-slot="modebar"]){transition-duration:0s!important}}
@media (forced-colors:active){:where(.xy [data-xy-slot="modebar"],.xy [data-xy-slot="tooltip"]){border:1px solid CanvasText}:where(.xy [data-xy-slot="modebar_button"].xy-active){outline:2px solid Highlight}:where(.xy [data-xy-slot="canvas"]:focus){outline:2px solid Highlight}}
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
