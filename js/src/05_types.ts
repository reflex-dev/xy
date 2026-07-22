// Shared types for the render client.
//
// The client consumes a *data-less spec* plus raw f32 buffers (§29): the spec
// is authored by the Python kernel (`python/xy/_figure.py` and friends) and
// arrives as parsed JSON, so these declarations describe a wire contract, not
// classes we construct. They are deliberately permissive where the wire is
// permissive — optional members are optional here too, and open-ended maps
// (per-axis styles, mark styles, per-kind trace extras) keep index signatures
// rather than pretending to an exhaustive union that the kernel could widen at
// any time. Tightening one of these is a real compatibility decision; make it
// deliberately, alongside the Python side that emits it.
//
// Naming mirrors the wire: snake_case members are exactly the JSON keys.

/** A JSON-ish value as it arrives from the kernel. */
export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };

/** Style bags are open maps: the kernel may add keys the client ignores. */
export type StyleBag = Record<string, any>;

/** RGBA in 0..1, the form every GL uniform and colormap LUT expects. */
export type Rgba = [number, number, number, number];

/** One shipped column's metadata: f32 values are offset-encoded (§4/§16), so
 * decoding is `value / scale + offset` in f64 on the CPU. */
export interface ColumnMeta {
  len: number;
  offset: number;
  scale?: number;
  dtype?: string;
  kind?: string;
  categories?: string[];
  [key: string]: any;
}

/** Axis descriptor (`spec.axes[id]`, plus the x/y shorthands). */
export interface AxisSpec {
  id?: string;
  kind?: string;
  side?: string;
  label?: string;
  range?: [number, number] | number[];
  categories?: string[];
  log?: boolean;
  format?: string;
  style?: StyleBag;
  [key: string]: any;
}

/** A per-point channel encoding (color/size/stroke). `buf` indexes
 * `spec.columns`; `mode` selects constant / continuous / categorical. */
export interface ChannelSpec {
  buf?: number;
  mode?: string;
  domain?: [number, number] | number[];
  colormap?: string;
  palette?: string[];
  categories?: string[];
  color?: string;
  size?: number;
  range?: number[];
  [key: string]: any;
}

/** One trace as the kernel emits it. Chart-kind-specific members (density
 * grids, hexbin deltas, mesh indices…) stay open — `MARK_KINDS` dispatches on
 * `kind` and reads what its own renderer needs. */
export interface TraceSpec {
  id?: string | number;
  kind: string;
  name?: string;
  tier?: string;
  x?: number;
  y?: number;
  x_axis?: string;
  y_axis?: string;
  color?: ChannelSpec;
  size?: ChannelSpec;
  stroke?: ChannelSpec;
  style?: StyleBag;
  channels?: Record<string, ChannelSpec>;
  [key: string]: any;
}

/** The first-paint spec (§29). */
export interface ChartSpec {
  protocol?: number;
  title?: string;
  columns: ColumnMeta[];
  traces: TraceSpec[];
  axes?: Record<string, AxisSpec>;
  x_axis?: AxisSpec;
  y_axis?: AxisSpec;
  buffer_layout?: string;
  interaction?: Record<string, any>;
  mark_style?: Record<string, StyleBag>;
  dom?: Record<string, any>;
  padding?: number[];
  show_legend?: boolean;
  show_tooltip?: boolean;
  [key: string]: any;
}

/** The kernel channel. `null` in standalone (`to_html`) pages, which is the
 * signal to take every kernel-less path (§37). */
export interface Comm {
  send(msg: Record<string, any>): void;
  onMessage?(cb: (content: any, buffers?: any) => void): () => void;
  wantsViewChange?(): boolean;
}

/** Payload buffers: one blob (packed) or one span per column (split). */
export type PayloadBuffers = Uint8Array | Uint8Array[];

/** Tick generation result. `labels` may differ from `ticks` (log axes draw
 * fewer labels than gridlines). */
export interface TickResult {
  ticks: number[];
  labels?: number[];
  step: number;
  log?: boolean;
  [key: string]: any;
}

/** Resolved canvas theme (§36): CSS tokens resolved to GL-ready RGBA. */
export interface Theme {
  bg: Rgba;
  grid: Rgba;
  axis: Rgba;
  label: Rgba;
  [key: string]: any;
}

/** Plot box in CSS pixels. */
export interface PlotBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A GPU-resident trace: the spec plus its uploaded buffers, decode metadata,
 * and tier caches. Every member beyond `trace` is a rebuildable cache (§27),
 * created lazily per mark kind, so this stays open by design. */
export interface GpuTrace {
  trace: TraceSpec;
  tier?: string;
  n?: number;
  xAxis?: string;
  yAxis?: string;
  xMeta?: ColumnMeta;
  yMeta?: ColumnMeta;
  color?: Rgba;
  drill?: any;
  density?: any;
  [key: string]: any;
}

/** A pick result: which trace and vertex the pointer is over. */
export interface Hit {
  trace: number;
  index: number;
  g?: GpuTrace;
  [key: string]: any;
}

/** A tooltip/event row, denormalized to display values. */
export type Row = Record<string, any>;

/** One entry in `MARK_KINDS`: build uploads GPU state for a kind, draw renders
 * it. The registry is the dispatch seam that keeps ChartView chart-agnostic. */
export interface MarkKind {
  build(view: any, g: GpuTrace, trace: TraceSpec, buffer: PayloadBuffers): void;
  draw(view: any, g: GpuTrace, x0: number, x1: number, y0: number, y1: number): void;
  retainCpu?: boolean;
  pointPick?: boolean;
  [key: string]: any;
}
