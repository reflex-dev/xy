// Keep the standalone IIFE's window.xy namespace limited to the public API.
// The ESM entry additionally exports a frozen exact-bundle semantic-test seam.
export {
  ChartView,
  MARK_KINDS,
  decodeFrame,
  default,
  markOf,
  render,
  renderStandalone,
} from "./60_entries";
