#!/usr/bin/env python3
"""Load the built Pyodide wheel in a real Pyodide runtime (node) and call a
native kernel through the ctypes seam.

The wasm job builds a structurally valid Emscripten side-module, but "builds"
is not "loads": Pyodide's dynamic linker must instantiate the module and the
`fc_*` C-ABI symbols must be callable. As of 2026-07-08 this FAILS — the Rust
core's default `panic=unwind` emits a `__cpp_exception` tag import Pyodide's
runtime does not provide (LinkError at WebAssembly.instantiate). This smoke is
the regression probe for that: it prints a clear PASS/FAIL and exits non-zero
on failure, but the wasm CI job runs it non-gating (continue-on-error) so the
experimental wheel never blocks a release — it just keeps the status honest and
visible until the exception-handling build is fixed.

Usage: python scripts/pyodide_load_smoke.py path/to/xy-...-pyodide_....whl
Requires: node with the `pyodide` npm package resolvable from CWD.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_DRIVER = r"""
import { loadPyodide } from "pyodide";
import fs from "node:fs";
const wheelPath = process.argv[2];
const name = wheelPath.split("/").pop();
const out = (o) => console.log("RESULT " + JSON.stringify(o));
try {
  const py = await loadPyodide();
  await py.loadPackage(["numpy", "micropip"]);
  const micropip = py.pyimport("micropip");
  py.FS.mkdirTree("/wheels");
  py.FS.writeFile("/wheels/" + name, fs.readFileSync(wheelPath));
  await micropip.install("emfs:/wheels/" + name);
  const r = await py.runPythonAsync(`
import xy.kernels as k
import numpy as np
mn, mx = k.min_max(np.array([3.0, 1.0, 2.0]))
from xy import _native
abi = _native._lib.fc_abi_version()
f"{k.BACKEND}|{abi}|{mn}|{mx}"
`);
  const [backend, abi, mn, mx] = r.split("|");
  out({ ok: true, backend, abi: Number(abi), min: Number(mn), max: Number(mx) });
} catch (e) {
  out({ ok: false, error: String(e.message || e).split("\n").slice(-4).join(" ") });
}
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: pyodide_load_smoke.py <wheel>", file=sys.stderr)
        return 2
    wheel = Path(sys.argv[1]).resolve()
    if not wheel.exists():
        print(f"wheel not found: {wheel}", file=sys.stderr)
        return 2

    # Write the driver into CWD so its `import "pyodide"` resolves against the
    # node_modules of the directory where `npm install pyodide` was run (node
    # resolves ESM imports relative to the importing file's location).
    driver = Path.cwd() / "_pyodide_load_driver.mjs"
    driver.write_text(_DRIVER, encoding="utf-8")
    try:
        proc = subprocess.run(
            ["node", str(driver), str(wheel)],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        driver.unlink(missing_ok=True)

    result = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[len("RESULT ") :])
    if result is None:
        print("no result from pyodide driver", file=sys.stderr)
        print(proc.stdout[-2000:], file=sys.stderr)
        print(proc.stderr[-2000:], file=sys.stderr)
        return 1

    if result.get("ok"):
        print(
            f"PASS: pyodide loaded xy, backend={result['backend']} "
            f"abi={result['abi']} min_max=({result['min']},{result['max']})"
        )
        return 0
    print(f"FAIL: pyodide could not load/run the wheel: {result.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
