// ---------------------------------------------------------------------------
// Ticks (computed in f64 on the CPU — never through f32, §16)
// ---------------------------------------------------------------------------

function niceStep(rough) {
  rough = Math.abs(rough);
  if (!Number.isFinite(rough) || rough <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (rough <= m * mag * (1 + 1e-12)) return m * mag;
  }
  return 10 * mag;
}

function linearTicks(lo, hi, target = 6) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [], step: 1 };
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  if (a === b) return { ticks: [a], step: 1 };
  const step = niceStep((b - a) / target);
  const first = Math.ceil(a / step) * step;
  const out = [];
  for (let v = first; v <= b + step * 1e-9 && out.length < 200; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  }
  return { ticks: out, step };
}

function logTicks(lo, hi, target = 6) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [], step: 1 };
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  if (a <= 0 || b <= 0) return { ticks: [], step: 1 };
  const e0 = Math.floor(Math.log10(a));
  const e1 = Math.ceil(Math.log10(b));
  const span = Math.max(1, e1 - e0);
  const mults = span <= Math.max(2, target) ? [1, 2, 5] : [1];
  const out = [];
  const labels = [];
  const labelEvery = Math.max(1, Math.ceil((e1 - e0 + 1) / Math.max(1, target)));
  for (let e = e0; e <= e1 && out.length < 200; e++) {
    const base = Math.pow(10, e);
    for (const m of mults) {
      const v = m * base;
      if (v >= a * (1 - 1e-12) && v <= b * (1 + 1e-12)) {
        out.push(v);
        if (m === 1 && (e - e0) % labelEvery === 0) labels.push(v);
      }
      if (out.length >= 200) break;
    }
  }
  return { ticks: out, labels: labels.length ? labels : out, step: 1, log: true };
}

function categoryTicks(lo, hi, categories, target = 6) {
  if (!categories || !categories.length) return { ticks: [], step: 1 };
  const start = Math.max(0, Math.ceil(Math.min(lo, hi)));
  const stop = Math.min(categories.length - 1, Math.floor(Math.max(lo, hi)));
  if (stop < start) return { ticks: [], step: 1 };
  const visible = stop - start + 1;
  const step = Math.max(1, Math.ceil(visible / Math.max(1, target)));
  const out = [];
  for (let v = start; v <= stop && out.length < 200; v += step) out.push(v);
  return { ticks: out, step };
}

const MS = { s: 1e3, m: 6e4, h: 36e5, d: 864e5 };
const TIME_STEPS = [
  1, 2, 5, 10, 20, 50, 100, 200, 500,
  MS.s, 2 * MS.s, 5 * MS.s, 10 * MS.s, 15 * MS.s, 30 * MS.s,
  MS.m, 2 * MS.m, 5 * MS.m, 10 * MS.m, 15 * MS.m, 30 * MS.m,
  MS.h, 2 * MS.h, 3 * MS.h, 6 * MS.h, 12 * MS.h,
  MS.d, 2 * MS.d, 7 * MS.d, 14 * MS.d,
];

function timeTicks(lo, hi, target = 6) {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { ticks: [], step: MS.d };
  const a = Math.min(lo, hi);
  const b = Math.max(lo, hi);
  const span = b - a;
  const rough = span / target;
  if (rough > 14 * MS.d) return calendarTicks(a, b, rough);
  let step = TIME_STEPS[TIME_STEPS.length - 1];
  for (const s of TIME_STEPS) {
    if (s >= rough) { step = s; break; }
  }
  const first = Math.ceil(a / step) * step;
  const out = [];
  for (let v = first; v <= b && out.length < 200; v += step) out.push(v);
  return { ticks: out, step };
}

function calendarTicks(lo, hi, rough) {
  const monthsRough = rough / (30 * MS.d);
  const monthSteps = [1, 2, 3, 6, 12, 24, 60, 120];
  let stepM = monthSteps[monthSteps.length - 1];
  for (const s of monthSteps) {
    if (s >= monthsRough) { stepM = s; break; }
  }
  const d = new Date(lo);
  let y = d.getUTCFullYear();
  let m = d.getUTCMonth();
  m = Math.ceil(m / stepM) * stepM;
  const out = [];
  for (;;) {
    const t = Date.UTC(y + Math.floor(m / 12), m % 12, 1);
    if (t > hi) break;
    if (t >= lo) out.push(t);
    m += stepM;
    if (out.length > 1000) break;
  }
  return { ticks: out, step: stepM * 30 * MS.d };
}

function fmtTime(ms, step) {
  const d = new Date(ms);
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  if (step >= 28 * MS.d) {
    const mo = d.getUTCMonth();
    return mo === 0 ? String(d.getUTCFullYear())
      : `${d.toLocaleString("en", { month: "short", timeZone: "UTC" })} ${d.getUTCFullYear()}`;
  }
  if (step >= MS.d) return `${d.toLocaleString("en", { month: "short", timeZone: "UTC" })} ${pad(d.getUTCDate())}`;
  if (step >= MS.m) return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  if (step >= MS.s) return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
  return `${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.${pad(d.getUTCMilliseconds(), 3)}`;
}

function fmtLinear(v, step) {
  const av = Math.abs(v);
  if (av >= 1e6 || (av !== 0 && av < 1e-4)) return v.toExponential(1).replace("e+", "e");
  let dec = step ? Math.max(0, Math.ceil(-Math.log10(Math.abs(step)))) : 0;
  while (dec < 8 && Math.abs(Number(step.toFixed(dec)) - step) > Math.abs(step) / 1000) dec++;
  return v.toFixed(Math.min(dec, 8));
}

// Match Python's default ``:g`` formatting used by the SVG/native colorbar
// exporters. Explicit ticks are authored values, so their precision must not
// be inferred from the unrelated automatic tick step for the whole domain.
function fmtGeneral(v, precision = 6) {
  const value = Number(v);
  if (!Number.isFinite(value)) return String(v);
  if (value === 0) return Object.is(value, -0) ? "-0" : "0";
  // %g picks fixed vs exponential from the exponent AFTER rounding to
  // `precision` significant digits (999999.5 -> 1e+06, 0.00009999995 -> 0.0001).
  let [coefficient, exponentText] = value.toExponential(precision - 1).split("e");
  const exponent = Number(exponentText);
  if (exponent < -4 || exponent >= precision) {
    coefficient = coefficient.replace(/0+$/, "").replace(/\.$/, "");
    return `${coefficient}e${exponent >= 0 ? "+" : "-"}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  const decimals = Math.max(0, precision - exponent - 1);
  let text = Number(value.toPrecision(precision)).toFixed(decimals);
  if (text.includes(".")) text = text.replace(/0+$/, "").replace(/\.$/, "");
  return text;
}

function fmtCategory(v, categories) {
  const i = Math.round(v);
  return i >= 0 && i < categories.length ? String(categories[i]) : "";
}

function fmtNumberSpec(v, format) {
  if (typeof format !== "string" || !Number.isFinite(Number(v))) return null;
  const percent = format.endsWith("%");
  const raw = percent ? format.slice(0, -1) : format;
  const match = raw.match(/^(,)?\.([0-9]+)f?$/);
  if (!match) return null;
  const digits = Number(match[2]);
  const value = percent ? Number(v) * 100 : Number(v);
  const text = match[1]
    ? value.toLocaleString(undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
    : value.toFixed(digits);
  return percent ? `${text}%` : text;
}

function fmtTimeSpec(ms, format) {
  if (typeof format !== "string") return null;
  const d = new Date(ms);
  if (!Number.isFinite(d.getTime())) return null;
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  const shortMonth = d.toLocaleString("en", { month: "short", timeZone: "UTC" });
  const longMonth = d.toLocaleString("en", { month: "long", timeZone: "UTC" });
  return format.replace(/%[YmdHMSbB]/g, (token) => {
    switch (token) {
      case "%Y": return String(d.getUTCFullYear());
      case "%m": return pad(d.getUTCMonth() + 1);
      case "%d": return pad(d.getUTCDate());
      case "%H": return pad(d.getUTCHours());
      case "%M": return pad(d.getUTCMinutes());
      case "%S": return pad(d.getUTCSeconds());
      case "%b": return shortMonth;
      case "%B": return longMonth;
      default: return token;
    }
  });
}

function fmtAxis(axis, v, tickStep) {
  if (axis && axis.kind === "category") return fmtCategory(v, axis.categories || []);
  if (axis && axis.kind === "time") return fmtTimeSpec(v, axis.format) || fmtTime(v, tickStep);
  const formatted = fmtNumberSpec(v, axis && axis.format);
  if (axis && axis.scale === "log" && Number(v) > 0 && Number(v) < 1 && formatted === "0") {
    return fmtLinear(v, tickStep);
  }
  return formatted || fmtLinear(v, tickStep);
}

function fmtValue(v, kind) {
  if (kind === "time_ms") {
    const d = new Date(v);
    return d.toISOString().replace("T", " ").replace(".000Z", "Z");
  }
  if (typeof v === "string") return v;
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (n === 0) return "0";
  const av = Math.abs(n);
  if (av >= 1e6 || av < 1e-4) return n.toExponential(3);
  return (Math.round(n * 1e4) / 1e4).toString();
}
