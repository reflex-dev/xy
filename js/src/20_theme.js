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

function hexColor(hex) {
  const h = hex.replace("#", "");
  if (!/^(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/.test(h)) {
    return null;
  }
  const full = h.length === 3 || h.length === 4 ? [...h].map((c) => c + c).join("") : h;
  const n = parseInt(full.slice(0, 6), 16);
  const a = full.length === 8 ? parseInt(full.slice(6, 8), 16) / 255 : 1;
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255, a];
}

function parseColor(host, c, fallback) {
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

function readTheme(root) {
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

function cssColor([r, g, b, a]) {
  return `rgba(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)},${a})`;
}

// Chrome *visual* defaults, one stylesheet per document. Every rule is wrapped
// in :where(...) so it carries ZERO specificity — any user utility class
// (`class_names[slot]`, specificity ≥ 0,1,0) or inline `styles[slot]` beats it
// without needing !important, regardless of stylesheet source order. This is
// what makes Tailwind actually win on the chrome: the elements now carry only
// *structural* inline styles (position/size/z-index/state), while background,
// color, padding, border, font, box-shadow live here as overridable defaults.
// All colors flow through --chart-* tokens so container theming still cascades.
const FC_CHROME_CSS = `
:where(.xy [data-fc-slot="title"]){text-align:center;font-size:14px;font-weight:600;color:var(--chart-text,inherit)}
:where(.xy [data-fc-slot="tooltip"]){background:var(--chart-tooltip-bg,rgba(20,24,33,.92));color:var(--chart-tooltip-text,#fff);padding:5px 8px;border-radius:4px;font-size:11px;line-height:1.35;box-shadow:0 2px 8px rgba(0,0,0,.3)}
:where(.xy [data-fc-slot="legend"]){gap:2px;font-size:11px;background:var(--chart-legend-bg,rgba(128,128,128,.08));border-radius:4px;padding:4px 8px;color:var(--chart-text,inherit)}
:where(.xy [data-fc-slot="legend_swatch"]){width:12px;height:10px;border-radius:2px;margin-right:5px}
:where(.xy [data-fc-slot="colorbar"]){color:var(--chart-text,inherit);font-size:10px}
:where(.xy [data-fc-slot="colorbar_bar"]){background:var(--xy-colorbar-gradient);border:1px solid currentColor;box-sizing:border-box}
:where(.xy [data-fc-slot="colorbar_title"]){font-weight:500}
:where(.xy [data-fc-slot="badge"]){gap:3px;font-size:11px;line-height:1.2}
:where(.xy [data-fc-slot="badge_item"]){padding:3px 6px;border-radius:4px;color:var(--chart-badge-text,#0f172a);background:var(--chart-badge-bg,rgba(255,255,255,.82));box-shadow:0 1px 4px rgba(15,23,42,.14)}
:where(.xy [data-fc-slot="modebar"]){gap:1px;background:var(--chart-modebar-bg,rgba(255,255,255,.78));border:1px solid rgba(128,128,128,.18);border-radius:4px;padding:1px;box-shadow:0 1px 4px rgba(0,0,0,.08)}
:where(.xy [data-fc-slot="modebar_button"]){width:26px;height:24px;padding:0;border:none;background:transparent;border-radius:3px;color:var(--chart-text,currentColor);cursor:pointer}
:where(.xy [data-fc-modebar-drag-handle]){cursor:move}
:where(.xy [data-fc-modebar-menu-trigger]){width:auto;min-width:58px;gap:2px;padding:0 6px;font-size:11px;font-variant-numeric:tabular-nums}
:where(.xy [data-fc-modebar-menu-indicator]){display:flex;transition:transform .15s}
:where(.xy [data-fc-modebar-menu-indicator] svg){width:11px;height:11px}
:where(.xy [data-fc-modebar-menu]){min-width:148px;gap:1px;padding:4px;background:var(--chart-modebar-bg,rgba(255,255,255,.94));border:1px solid rgba(128,128,128,.22);border-radius:7px;box-shadow:0 5px 18px rgba(15,23,42,.18);backdrop-filter:blur(8px)}
:where(.xy [data-fc-modebar-menu-item]){width:100%;height:28px;justify-content:flex-start;padding:0 9px;border-radius:4px;text-align:left;white-space:nowrap}
:where(.xy [data-fc-modebar-menu-item]:hover,.xy [data-fc-modebar-menu-item]:focus-visible){background:var(--chart-modebar-active,rgba(128,128,128,.18));outline:none}
:where(.xy [data-fc-modebar-menu-item][data-fc-separator]){margin-top:3px;border-top:1px solid rgba(128,128,128,.2);border-radius:0 0 4px 4px}
:where(.xy [data-fc-modebar-menu-icon]){display:flex;width:16px;margin-right:7px}
:where(.xy [data-fc-modebar-menu-icon] svg){width:14px;height:14px}
:where(.xy [data-fc-modebar-menu-shortcut]){margin-left:auto;padding-left:20px;color:var(--chart-axis,currentColor);font-size:10px;opacity:.72}
:where(.xy [data-fc-slot="modebar_button"].fc-active){background:var(--chart-modebar-active,rgba(128,128,128,.22))}
:where(.xy [data-fc-slot="selection"]){border:1px solid var(--chart-selection,rgba(90,140,240,.9));background:var(--chart-selection-fill,rgba(90,140,240,.15))}
:where(.xy [data-fc-slot="selection"][data-fc-band="zoom"]){border-color:var(--chart-zoom-selection,rgba(120,120,120,.9));background:var(--chart-zoom-selection-fill,rgba(120,120,120,.12))}
:where(.xy [data-fc-slot="crosshair_x"],.xy [data-fc-slot="crosshair_y"]){background:var(--chart-crosshair,rgba(15,23,42,.42))}
:where(.xy [data-fc-slot="tick_label"]){color:var(--chart-text,inherit)}
:where(.xy [data-fc-slot="axis_title"]){color:var(--chart-text,inherit);font-size:12px}
:where(.xy [data-fc-slot="annotation_label"]){font-size:11px;line-height:1.2;font-weight:500;color:var(--chart-annotation-text,var(--chart-text,inherit))}
:where(.xy [data-fc-slot="canvas"]){cursor:var(--chart-cursor,crosshair)}
:where(.xy [data-fc-slot="canvas"][data-fc-dragmode="pan"]){cursor:var(--chart-cursor-pan,grab)}
`;

// Inject FC_CHROME_CSS once per DOM root (document head or shadow root), so
// multiple charts on one page share a single stylesheet.
function ensureChromeStylesheet(node) {
  let root = node && node.getRootNode ? node.getRootNode() : document;
  const isShadow = typeof ShadowRoot !== "undefined" && root instanceof ShadowRoot;
  if (!isShadow && !(root instanceof Document)) root = document; // detached subtree
  const scope = isShadow ? root : (root.head || document.head || root.documentElement);
  if (!scope || !scope.querySelector) return;
  if (scope.querySelector("style[data-xy-chrome]")) return;
  const style = document.createElement("style");
  style.setAttribute("data-xy-chrome", "");
  style.textContent = FC_CHROME_CSS;
  scope.appendChild(style);
}

function safeCssPaint(host, expr, fallback = [0.5, 0.5, 0.5, 1]) {
  const parsed = parseColor(host, expr, fallback);
  const color = Array.isArray(parsed) && parsed.length >= 4 && parsed.every(Number.isFinite)
    ? parsed
    : fallback;
  return cssColor(color);
}
