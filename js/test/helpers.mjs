import vm from "node:vm";
import { readFileSync } from "node:fs";

import { ChartView } from "../../python/xy/static/index.js";

export function makeView({ axes, interaction = {} }) {
  const view = Object.create(ChartView.prototype);
  view.axes = Object.fromEntries(
    Object.entries(axes).map(([id, axis]) => [id, { id, ...axis }])
  );
  view.interaction = { navigation: true, pan: true, zoom: true, ...interaction };
  view.plot = { x: 10, y: 20, w: 200, h: 100 };
  view.dpr = 2;
  view.view0 = view._copyView({
    ranges: Object.fromEntries(
      Object.entries(view.axes).map(([id, axis]) => [id, [...axis.range]])
    ),
  });
  view.view = view._copyView(view.view0);
  view._destroyed = false;
  return view;
}

export function executeRebinWorker(source, messages) {
  const sent = [];
  const workerSelf = {
    postMessage(message, transfers) {
      sent.push({ message, transfers });
    },
  };
  const context = vm.createContext({
    Float32Array,
    Float64Array,
    Map,
    self: workerSelf,
  });
  vm.runInContext(source, context, { filename: "xy-rebin-worker.js" });
  for (const data of messages) workerSelf.onmessage({ data });
  return sent;
}

export function standaloneNamespace() {
  const context = vm.createContext({});
  const source = readFileSync(
    new URL("../../python/xy/static/standalone.js", import.meta.url),
    "utf8",
  );
  vm.runInContext(source, context, { filename: "python/xy/static/standalone.js" });
  return context.xy;
}

export function fakeStyleElement() {
  const values = new Map();
  return {
    values,
    style: {
      setProperty(property, value) {
        values.set(property, value);
      },
    },
  };
}
