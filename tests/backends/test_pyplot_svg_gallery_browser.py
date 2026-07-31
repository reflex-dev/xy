from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.pyplot_gallery.rewrite import rewrite_pyplot_imports

matplotlib = pytest.importorskip("matplotlib")

ROOT = Path(__file__).resolve().parents[2]
GALLERY = ROOT / "gallery" / "matplotlib-3.11.1" / "examples"
PROBE = Path(__file__).with_name("pyplot_svg_gallery_probe.mjs")
SOURCES = {
    "histogram": GALLERY / "user_interfaces" / "svg_histogram_sgskip.py",
    "tooltip": GALLERY / "user_interfaces" / "svg_tooltip_sgskip.py",
    "hyperlinks": GALLERY / "misc" / "hyperlinks_sgskip.py",
}
OUTPUTS = {
    "histogram": ("svg_histogram.svg",),
    "tooltip": ("svg_tooltip.svg",),
    "hyperlinks": ("scatter.svg", "image.svg"),
}


def _require_browser_toolchain() -> tuple[str, str]:
    required = bool(os.environ.get("XY_REQUIRE_BROWSER"))
    chromium: str | None = None
    try:
        from xy.export import find_chromium

        chromium = find_chromium()
    except ImportError:
        pass
    node = shutil.which("node")
    if chromium is None or node is None:
        message = f"browser SVG gate requires Chromium and Node (chromium={chromium}, node={node})"
        if required:
            pytest.fail(message)
        pytest.skip(message)
    playwright = subprocess.run(
        [node, "-e", "require.resolve('playwright')"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if playwright.returncode != 0:
        message = f"browser SVG gate requires Playwright: {playwright.stderr.strip()}"
        if required:
            pytest.fail(message)
        pytest.skip(message)
    return node, chromium


def _execute_source(engine: str, source_path: Path, output_dir: Path) -> None:
    source = source_path.read_text(encoding="utf-8")
    if engine == "xy":
        rewritten = rewrite_pyplot_imports(source, filename=str(source_path))
        assert rewritten.import_count == 1
        source = rewritten.source

    output_dir.mkdir(parents=True)
    executable = output_dir / source_path.name
    executable.write_text(source, encoding="utf-8")
    environment = os.environ.copy()
    environment["MPLCONFIGDIR"] = str(output_dir / "mplconfig")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(ROOT / "python"), environment.get("PYTHONPATH", "")) if part
    )
    if engine == "xy":
        environment["MPLBACKEND"] = "module://xy.backends.backend_xy"
        environment["XY_PYPLOT_MODE"] = "compat"
    else:
        environment["MPLBACKEND"] = "Agg"
        environment.pop("XY_PYPLOT_MODE", None)

    result = subprocess.run(
        [sys.executable, str(executable)],
        cwd=output_dir,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"{engine} failed {source_path.relative_to(GALLERY)}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_exact_svg_gallery_sources_keep_browser_interactions(tmp_path: Path) -> None:
    required = bool(os.environ.get("XY_REQUIRE_BROWSER"))
    if required:
        assert matplotlib.__version__ == "3.11.0"
    node, chromium = _require_browser_toolchain()
    artifacts: list[dict[str, str]] = []

    for engine in ("matplotlib", "xy"):
        engine_dir = tmp_path / engine
        artifact: dict[str, str] = {"engine": engine}
        for role, source_path in SOURCES.items():
            output_dir = engine_dir / role
            _execute_source(engine, source_path, output_dir)
            for output_name in OUTPUTS[role]:
                output = output_dir / output_name
                assert output.is_file() and output.stat().st_size > 1_000
            if role == "histogram":
                artifact["histogram"] = str(output_dir / "svg_histogram.svg")
            elif role == "tooltip":
                artifact["tooltip"] = str(output_dir / "svg_tooltip.svg")
            else:
                artifact["scatter"] = str(output_dir / "scatter.svg")
                artifact["image"] = str(output_dir / "image.svg")
        artifacts.append(artifact)

    manifest = tmp_path / "svg-artifacts.json"
    manifest.write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    result = subprocess.run(
        [node, str(PROBE), str(manifest), chromium],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert json.loads(result.stdout) == {
        "results": [
            {"engine": "matplotlib", "passed": True},
            {"engine": "xy", "passed": True},
        ]
    }
