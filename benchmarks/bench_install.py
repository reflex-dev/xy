"""Install-footprint and cold-import benchmark (methodology §1 rows
`install size`, `cold import`), stdlib only — no numpy, no PyPI at runtime.

Two numbers a `pip install` costs you before a single chart is drawn:

- **cold import**: best-of-N `python -c "import lib"` in *fresh* interpreters
  (module cache empty each time — the honest first-import latency, not a warm
  re-import). This is the §33 import-budget concern made comparative.
- **distribution size**: on-disk bytes of the distribution's own installed
  files via `importlib.metadata`. This is a *lower bound* on real install cost
  — it excludes transitive dependencies (plotly→kaleido→…); the fresh-venv
  total-footprint measure is the methodology's gold standard and stays a CI
  runbook item. Labeled as such so the number is never oversold.

Libraries that aren't installed are reported `unavailable`, never silently
dropped (harness policy shared with bench_vs.py). Run whatever is present:

    python benchmarks/bench_install.py
    python benchmarks/bench_install.py --packages json,html --repeat 7
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata as im
import json
import subprocess
import sys
from pathlib import Path

# import-name -> distribution name (they differ often enough to be explicit).
# The import name is what `import X` costs; the distribution name is what
# `importlib.metadata` sizes.
DEFAULT_TARGETS: list[tuple[str, str]] = [
    ("fastcharts", "fastcharts"),
    ("plotly", "plotly"),
    ("matplotlib", "matplotlib"),
    ("seaborn", "seaborn"),
    ("bokeh", "bokeh"),
    ("altair", "altair"),
    ("datashader", "datashader"),
    ("hvplot", "hvplot"),
    ("holoviews", "holoviews"),
    ("plotly_resampler", "plotly-resampler"),
]


def cold_import_ms(module: str, repeat: int) -> tuple[float | None, str | None]:
    """Best-of-`repeat` fresh-interpreter import time in ms, or (None, reason)."""
    # perf_counter inside the child so we time only the import, not spawn.
    code = (
        "import time,importlib,sys\n"
        "t=time.perf_counter()\n"
        f"importlib.import_module({module!r})\n"
        "sys.stdout.write(repr(time.perf_counter()-t))\n"
    )
    best = None
    for _ in range(repeat):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()
            reason = err[-1][:80] if err else f"exit {proc.returncode}"
            return None, reason
        try:
            dt = float(proc.stdout.strip()) * 1e3
        except ValueError:
            return None, "unparseable timing"
        best = dt if best is None else min(best, dt)
    return best, None


def dist_size_bytes(dist: str) -> tuple[int | None, int | None, str | None]:
    """(total_bytes, file_count, reason) for a distribution's own files."""
    try:
        meta = im.distribution(dist)
    except im.PackageNotFoundError:
        return None, None, "not installed"
    files = meta.files or []
    total = 0
    counted = 0
    for f in files:
        try:
            p = Path(meta.locate_file(f))
            total += p.stat().st_size
            counted += 1
        except OSError:
            continue  # listed-but-absent (e.g. pyc not yet built) — skip
    if counted == 0:
        return None, None, "no locatable files"
    return total, counted, None


def _fmt_bytes(b: int | None) -> str:
    if b is None:
        return "—"
    size = float(b)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def run(targets: list[tuple[str, str]], repeat: int) -> dict:
    rows = []
    for module, dist in targets:
        version = None
        with contextlib.suppress(im.PackageNotFoundError):
            version = im.version(dist)
        ms, imp_reason = cold_import_ms(module, repeat)
        size, nfiles, size_reason = dist_size_bytes(dist)
        status = "ok"
        if ms is None and size is None:
            status = f"unavailable ({imp_reason or size_reason})"
        rows.append(
            {
                "module": module,
                "distribution": dist,
                "version": version,
                "cold_import_ms": ms,
                "import_note": imp_reason,
                "dist_bytes": size,
                "dist_files": nfiles,
                "size_note": size_reason,
                "status": status,
            }
        )
    return {"repeat": repeat, "python": sys.version.split()[0], "results": rows}


def to_markdown(report: dict) -> str:
    out = [
        "### Install footprint & cold import",
        "",
        f"Best-of-{report['repeat']} fresh-interpreter import; distribution "
        "files only (excludes transitive deps — a lower bound on real install "
        f"cost). Python {report['python']}.",
        "",
        "| library | version | cold import | dist size | files |",
        "|---|---|---:|---:|---:|",
    ]

    # fastest importer first, unavailable last
    def sort_key(r):
        return (r["cold_import_ms"] is None, r["cold_import_ms"] or 0.0)

    for r in sorted(report["results"], key=sort_key):
        if r["status"] != "ok":
            out.append(f"| {r['module']} | — | {r['status']} | — | — |")
            continue
        imp = f"{r['cold_import_ms']:.1f} ms" if r["cold_import_ms"] is not None else "—"
        out.append(
            f"| {r['module']} | {r['version'] or '—'} | {imp} "
            f"| {_fmt_bytes(r['dist_bytes'])} | {r['dist_files'] or '—'} |"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--packages",
        default=None,
        help="comma-separated import names to override the default competitor set",
    )
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--json", default=None, help="write JSON results here")
    args = ap.parse_args()

    if args.packages:
        targets = [(m.strip(), m.strip()) for m in args.packages.split(",") if m.strip()]
    else:
        targets = DEFAULT_TARGETS

    report = run(targets, args.repeat)
    print(to_markdown(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
