"""Explicit coverage for the 22 gallery sources that do not import pyplot."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
GALLERY = ROOT / "gallery" / "matplotlib-3.11.1"
COMPANIONS = GALLERY / "companions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _document(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_companion(name: str) -> ModuleType:
    path = COMPANIONS / "xy_native" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_xy_companion_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_classifies_all_non_pyplot_sources_without_counting_them() -> None:
    gallery_manifest = _document(GALLERY / "manifest.json")
    companion_manifest = _document(COMPANIONS / "manifest.json")

    canonical = {
        entry["path"]: entry
        for entry in gallery_manifest["examples"]
        if not entry["pyplot_eligible"]
    }
    records = {entry["upstream_path"]: entry for entry in companion_manifest["records"]}
    assert len(canonical) == len(records) == companion_manifest["non_pyplot_count"] == 22
    assert set(records) == set(canonical)
    assert companion_manifest["pyplot_eligible_count"] == 0
    assert companion_manifest["xy_native_companion_count"] == 4

    dispositions = [record["disposition"] for record in records.values()]
    assert dispositions.count("headless_xy_native_companion") == 4
    assert dispositions.count("gui_toolkit_embedding") == 16
    assert dispositions.count("live_server_embedding") == 2

    for path, record in records.items():
        source = GALLERY / "examples" / path
        assert canonical[path]["profile"] == "non_pyplot"
        assert record["upstream_sha256"] == canonical[path]["sha256"] == _sha256(source)


def test_companions_are_hash_locked_and_never_import_pyplot_or_matplotlib() -> None:
    manifest = _document(COMPANIONS / "manifest.json")
    companion_records = [
        record for record in manifest["records"] if record["companion_path"] is not None
    ]
    assert {record["upstream_path"] for record in companion_records} == {
        "misc/font_indexing.py",
        "misc/ftface_props.py",
        "units/basic_units.py",
        "user_interfaces/canvasagg.py",
    }

    for record in companion_records:
        path = COMPANIONS / record["companion_path"]
        assert _sha256(path) == record["companion_sha256"]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
        assert "xy.pyplot" not in imported
        assert not any(name == "matplotlib" or name.startswith("matplotlib.") for name in imported)


def test_native_font_companions_report_the_embedded_atlas(capsys) -> None:
    indexing = _load_companion("font_indexing")
    properties = _load_companion("ftface_props")

    assert indexing.atlas_row("A") == ord("A") - 32
    with pytest.raises(ValueError, match="exactly one"):
        indexing.atlas_row("not one character")
    assert indexing.glyph_record("A") == {
        "codepoint": 65,
        "atlas_row": 33,
        "advance_px": 11.0,
    }
    space_row = indexing.atlas_row(" ")
    assert indexing.glyph_record("\u00a0") == {
        "codepoint": 0x00A0,
        "atlas_row": space_row,
        "advance_px": 5.0,
    }
    assert indexing.glyph_record("\u202f") == {
        "codepoint": 0x202F,
        "atlas_row": space_row,
        "advance_px": 5.0,
    }
    for character in ("\n", "\u200b", "\ufeff"):
        assert indexing.glyph_record(character) == {
            "codepoint": ord(character),
            "atlas_row": None,
            "advance_px": 0.0,
        }
    assert indexing.glyph_record("東") == {
        "codepoint": ord("東"),
        "atlas_row": indexing.atlas_row("\ufffd"),
        "advance_px": 16.0,
    }
    atlas = properties.atlas_properties()
    assert atlas["family"] == "DejaVu Sans"
    assert atlas["runtime_font_engine"] == "embedded coverage atlas"
    assert atlas["cell_height"] == atlas["ascent"] + atlas["descent"]
    assert atlas["glyph_count"] > 95

    indexing.main()
    properties.main()
    output = capsys.readouterr().out
    assert "AV 22.0 kerning=0" in output
    assert "runtime_font_engine" in output


def test_basic_units_companion_converts_before_native_charting(tmp_path: Path) -> None:
    basic_units = _load_companion("basic_units")

    assert basic_units.inch(2).convert_to(basic_units.cm).numbers() == [5.08]
    assert basic_units.degrees(180).convert_to(basic_units.radians).numbers() == [
        basic_units.math.pi
    ]
    assert basic_units.rad_fn(basic_units.math.pi) == r"$\pi$"

    output = tmp_path / "units.svg"
    basic_units.main(["--output", str(output)])
    svg = output.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "Explicit units at the native XY boundary" in svg
    assert "radians" in svg


def test_canvas_companion_exports_native_png_and_decoded_rgba(tmp_path: Path) -> None:
    canvas = _load_companion("canvasagg")
    png = tmp_path / "canvas.png"
    bmp = tmp_path / "canvas-output"

    canvas.main(["--png", str(png), "--bmp", str(bmp)])

    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(png) as image:
        assert image.size == (500, 400)
        assert image.mode in {"RGB", "RGBA"}
    with Image.open(bmp) as image:
        assert image.format == "BMP"
        assert image.size == (500, 400)
        assert image.mode in {"RGB", "RGBA"}
    _encoded, rgba = canvas.render_native()
    assert rgba.size == (500, 400)
    assert rgba.mode == "RGBA"


def test_all_four_companions_run_as_real_scripts(tmp_path: Path) -> None:
    commands = [
        ["font_indexing.py"],
        ["ftface_props.py"],
        ["basic_units.py", "--output", str(tmp_path / "subprocess-units.svg")],
        [
            "canvasagg.py",
            "--png",
            str(tmp_path / "subprocess-canvas.png"),
            "--bmp",
            str(tmp_path / "subprocess-canvas.bmp"),
        ],
    ]
    for command in commands:
        result = subprocess.run(
            [sys.executable, str(COMPANIONS / "xy_native" / command[0]), *command[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr

    assert (tmp_path / "subprocess-units.svg").is_file()
    assert (tmp_path / "subprocess-canvas.png").is_file()
    assert (tmp_path / "subprocess-canvas.bmp").is_file()
