import assert from "node:assert/strict";
import test from "node:test";

import { __testing, MARK_KINDS } from "../../python/xy/static/index.js";
import { executeRebinWorker } from "./helpers.mjs";

function workerMessages() {
  return [
    {
      type: "init",
      trace: "points",
      x: new Float64Array([0.1, 0.9, 1.1, 1.9, 9]).buffer,
      y: new Float64Array([0.1, 0.9, 0.1, 1.9, 9]).buffer,
    },
    {
      type: "rebin",
      trace: "points",
      seq: 17,
      x0: 0,
      x1: 2,
      y0: 0,
      y1: 2,
      w: 2,
      h: 2,
    },
  ];
}

function assertWorkerContract(source) {
  const sent = executeRebinWorker(source, workerMessages());
  assert.equal(sent.length, 1);
  const { message, transfers } = sent[0];
  assert.deepEqual(
    {
      type: message.type,
      seq: message.seq,
      trace: message.trace,
      w: message.w,
      h: message.h,
      max: message.max,
      x0: message.x0,
      x1: message.x1,
      y0: message.y0,
      y1: message.y1,
    },
    {
      type: "grid",
      seq: 17,
      trace: "points",
      w: 2,
      h: 2,
      max: 2,
      x0: 0,
      x1: 2,
      y0: 0,
      y1: 2,
    }
  );
  assert.deepEqual([...new Float32Array(message.grid)], [2, 1, 0, 1]);
  assert.equal(transfers.length, 1);
  assert.equal(transfers[0], message.grid);
}

test("standalone worker protocol initializes, bins, replies, and transfers", () => {
  assertWorkerContract(__testing.XY_REBIN_WORKER_SRC);
});

test("worker protocol ignores unknown messages and unknown traces", () => {
  const sent = executeRebinWorker(__testing.XY_REBIN_WORKER_SRC, [
    { type: "unknown", trace: "points" },
    { type: "rebin", trace: "missing", w: 2, h: 2, x0: 0, x1: 1, y0: 0, y1: 1 },
  ]);
  assert.deepEqual(sent, []);
});

test("malformed worker dimensions fail instead of emitting corrupt evidence", () => {
  const messages = workerMessages();
  messages[1].w = -1;
  assert.throws(
    () => executeRebinWorker(__testing.XY_REBIN_WORKER_SRC, messages),
    /Invalid typed array length/
  );
});

test("negative control: worker oracle rejects a real binning mutation", () => {
  const needle = "const v = ++grid[(cy | 0) * w + (cx | 0)];";
  const mutant = __testing.XY_REBIN_WORKER_SRC.replace(
    needle,
    "const v = (grid[(cy | 0) * w + (cx | 0)] += 2);"
  );
  assert.notEqual(mutant, __testing.XY_REBIN_WORKER_SRC, "mutation must apply");
  assert.throws(() => assertWorkerContract(mutant));
});

test("negative control: formatter and registry oracles reject broken doubles", () => {
  const formatterOracle = (format) => {
    assert.equal(format(0.125, ".1%"), "12.5%");
    assert.equal(format(1, ".999f"), null);
  };
  formatterOracle(__testing.fmtNumberSpec);
  assert.throws(() => formatterOracle(() => "12%"));

  const registryOracle = (registry) => {
    assert.equal(typeof registry.scatter?.build, "function");
    assert.equal(typeof registry.triangle_mesh?.draw, "function");
  };
  registryOracle(MARK_KINDS);
  assert.throws(() => registryOracle({ scatter: {} }));
});
