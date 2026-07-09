"""Install-footprint and cold-import benchmark (methodology §1 rows
`install size`, `cold import`), stdlib only — no numpy, no PyPI at runtime.

Two numbers a `pip install` costs you before a single chart is drawn:

- **cold import**: best-of-N `python -c "import lib"` in *fresh* interpreters
  (module cache empty each time — the honest first-import latency, not a warm
  re-import). This is the §33 import-budget concern made comparative.
- **distribution size**: on-disk bytes of the distribution's own installed
  files via `importlib.metadata`, explicitly labeled as a lower bound.
- **fresh environment** (`--fresh-venv`): isolated install time, total
  site-packages bytes/files, transitive distribution count, and cold import.

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
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from categories import BENCHMARK_CATEGORIES, categories_for  # noqa: E402
from environment import SCHEMA_VERSION, collect_environment_metadata  # noqa: E402

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
ROOT = Path(__file__).resolve().parent.parent
INSTALL_CATEGORY_IDS = (
    "install_footprint_import_budget",
    "small_data_startup",
    "payload_export_size",
)


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


def fresh_venv_footprint(module: str, dist: str) -> dict[str, int | float | str | None]:
    """Install one target into an isolated uv venv and measure all dependencies."""
    with tempfile.TemporaryDirectory() as td:
        env_dir = Path(td) / "venv"
        created = subprocess.run(
            ["uv", "venv", "--python", sys.executable, str(env_dir)],
            capture_output=True,
            text=True,
        )
        if created.returncode != 0:
            return {"fresh_note": (created.stderr or created.stdout).strip()[-160:]}
        python = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        target = str(ROOT) if dist == "fastcharts" else dist
        t0 = time.perf_counter()
        installed = subprocess.run(
            ["uv", "pip", "install", "--python", str(python), target],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )
        install_ms = (time.perf_counter() - t0) * 1e3
        if installed.returncode != 0:
            return {
                "fresh_install_ms": install_ms,
                "fresh_note": (installed.stderr or installed.stdout).strip()[-160:],
            }
        import_values = []
        import_code = (
            "import importlib,time;"
            "t=time.perf_counter();"
            f"importlib.import_module({module!r});"
            "print((time.perf_counter()-t)*1000)"
        )
        for _ in range(3):
            imported = subprocess.run(
                [str(python), "-c", import_code], capture_output=True, text=True
            )
            if imported.returncode == 0:
                import_values.append(float(imported.stdout.strip()))
        probe = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import json,pathlib,sysconfig,importlib.metadata as m;"
                    "p=pathlib.Path(sysconfig.get_paths()['purelib']);"
                    "fs=[x for x in p.rglob('*') if x.is_file()];"
                    "print(json.dumps({'bytes':sum(x.stat().st_size for x in fs),"
                    "'files':len(fs),'dists':len(list(m.distributions()))}))"
                ),
            ],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            return {"fresh_install_ms": install_ms, "fresh_note": "footprint probe failed"}
        measured = json.loads(probe.stdout)
        return {
            "fresh_install_ms": install_ms,
            "fresh_cold_import_ms": min(import_values) if import_values else None,
            "fresh_site_bytes": int(measured["bytes"]),
            "fresh_site_files": int(measured["files"]),
            "fresh_dist_count": int(measured["dists"]),
            "fresh_note": None,
        }


def run(targets: list[tuple[str, str]], repeat: int, *, fresh_venv: bool = False) -> dict:
    rows = []
    for module, dist in targets:
        version = None
        with contextlib.suppress(im.PackageNotFoundError):
            version = im.version(dist)
        ms, imp_reason = cold_import_ms(module, repeat)
        size, nfiles, size_reason = dist_size_bytes(dist)
        status = "ok"
        if ms is None and size is None:
            status = f"unavailable({imp_reason or size_reason})"
        row = {
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
        if fresh_venv:
            row.update(fresh_venv_footprint(module, dist))
            if row.get("fresh_site_bytes") is None:
                row["status"] = f"failed({row.get('fresh_note') or 'fresh install failed'})"
        rows.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "environment": collect_environment_metadata(),
        "benchmark_categories": list(BENCHMARK_CATEGORIES),
        "tracked_categories": categories_for(INSTALL_CATEGORY_IDS),
        "repeat": repeat,
        "fresh_venv": fresh_venv,
        "python": sys.version.split()[0],
        "results": rows,
    }


def to_markdown(report: dict) -> str:
    out = [
        "### Install footprint & cold import",
        "",
        f"Best-of-{report['repeat']} fresh-interpreter import; distribution "
        "files only (excludes transitive deps — a lower bound on real install "
        f"cost). Python {report['python']}.",
        "",
        "| library | version | cold import | dist size | files | fresh env | deps | fresh import |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]

    # fastest importer first, unavailable last
    def sort_key(r):
        return (r["cold_import_ms"] is None, r["cold_import_ms"] or 0.0)

    for r in sorted(report["results"], key=sort_key):
        if r["status"] != "ok":
            out.append(f"| {r['module']} | — | {r['status']} | — | — | — | — | — |")
            continue
        imp = f"{r['cold_import_ms']:.1f} ms" if r["cold_import_ms"] is not None else "—"
        fresh_import = (
            f"{r['fresh_cold_import_ms']:.1f} ms"
            if r.get("fresh_cold_import_ms") is not None
            else "—"
        )
        out.append(
            f"| {r['module']} | {r['version'] or '—'} | {imp} "
            f"| {_fmt_bytes(r['dist_bytes'])} | {r['dist_files'] or '—'} "
            f"| {_fmt_bytes(r.get('fresh_site_bytes'))} | {r.get('fresh_dist_count') or '—'} "
            f"| {fresh_import} |"
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
    ap.add_argument(
        "--fresh-venv",
        action="store_true",
        help="install each target into an isolated uv venv and include transitive footprint",
    )
    ap.add_argument("--json", default=None, help="write JSON results here")
    args = ap.parse_args()

    if args.packages:
        targets = [(m.strip(), m.strip()) for m in args.packages.split(",") if m.strip()]
    else:
        targets = DEFAULT_TARGETS

    report = run(targets, args.repeat, fresh_venv=args.fresh_venv)
    print(to_markdown(report))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
