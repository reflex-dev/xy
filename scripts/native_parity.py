#!/usr/bin/env python3
"""Exercise one native core through scalar and architecture-selected paths.

The probe is intentionally stdlib-only so it can run against a source build,
an installed wheel, or a wheel extracted inside a manylinux/musllinux runtime.
It validates three seams through the public C ABI: a dispatched kernel, invalid
pointer handling, and an exact raster framebuffer. The parent process runs the
probe twice because ``XY_SIMD`` dispatch is cached within one loaded library.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import platform
import struct
import subprocess
import sys
import tempfile
import zipfile
from array import array
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ABI_VERSION = 38
CAP_SCALAR = 1 << 0
CAP_AVX2_AVAILABLE = 1 << 1
CAP_AVX2_SELECTED = 1 << 2
CAP_AARCH64 = 1 << 3
KNOWN_CAPABILITIES = CAP_SCALAR | CAP_AVX2_AVAILABLE | CAP_AVX2_SELECTED | CAP_AARCH64


def _library_name() -> str:
    if sys.platform == "win32":
        return "xy_core.dll"
    if sys.platform == "darwin":
        return "libxy_core.dylib"
    return "libxy_core.so"


def _normalized_architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        return "x86_64"
    if machine in {"arm64", "aarch64"}:
        return "aarch64"
    return machine


def _installed_library() -> Path | None:
    spec = importlib.util.find_spec("xy")
    if spec is None or not spec.submodule_search_locations:
        return None
    package = Path(next(iter(spec.submodule_search_locations)))
    candidate = package / "_native_lib" / _library_name()
    return candidate if candidate.is_file() else None


def _source_library() -> Path | None:
    root = Path(__file__).resolve().parents[1]
    name = _library_name()
    for profile in ("release", "debug"):
        candidate = root / "target" / profile / name
        if candidate.is_file():
            return candidate
    return None


@contextmanager
def _resolved_library(library: Path | None, wheel: Path | None) -> Iterator[Path]:
    if library is not None and wheel is not None:
        raise SystemExit("pass only one of --library and --wheel")
    if library is not None:
        resolved = library.resolve()
        if not resolved.is_file():
            raise SystemExit(f"native library does not exist: {resolved}")
        yield resolved
        return
    if wheel is not None:
        wheel = wheel.resolve()
        if not wheel.is_file():
            raise SystemExit(f"wheel does not exist: {wheel}")
        suffixes = ("/libxy_core.so", "/libxy_core.dylib", "/xy_core.dll")
        with zipfile.ZipFile(wheel) as archive:
            members = [name for name in archive.namelist() if name.endswith(suffixes)]
            if len(members) != 1:
                raise SystemExit(
                    f"expected exactly one native core in {wheel.name}, found {members}"
                )
            with tempfile.TemporaryDirectory(prefix="xy-native-parity-") as tmp:
                extracted = Path(tmp) / Path(members[0]).name
                extracted.write_bytes(archive.read(members[0]))
                yield extracted
        return
    discovered = _installed_library() or _source_library()
    if discovered is None:
        raise SystemExit(
            "native core not found; build it, install a native wheel, or pass --library/--wheel"
        )
    yield discovered.resolve()


def _pointer(buffer: array | bytearray, ctype: type[ctypes._SimpleCData]) -> object:  # type: ignore[name-defined]
    return ctypes.cast(ctypes.addressof(ctype.from_buffer(buffer)), ctypes.POINTER(ctype))


def _load(path: Path) -> ctypes.CDLL:
    library = ctypes.CDLL(str(path))
    library.xy_abi_version.restype = ctypes.c_uint32
    library.xy_abi_version.argtypes = []
    library.xy_runtime_capabilities.restype = ctypes.c_uint32
    library.xy_runtime_capabilities.argtypes = []
    library.xy_min_max.restype = ctypes.c_int32
    library.xy_min_max.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    library.xy_rasterize.restype = ctypes.c_int32
    library.xy_rasterize.argtypes = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
        ctypes.c_size_t,
    ]
    return library


def _capability_report(capabilities: int) -> dict[str, bool]:
    unknown = capabilities & ~KNOWN_CAPABILITIES
    if unknown:
        raise AssertionError(f"native core reported unknown capability bits: {unknown:#x}")
    report = {
        "scalar": bool(capabilities & CAP_SCALAR),
        "avx2_available": bool(capabilities & CAP_AVX2_AVAILABLE),
        "avx2_selected": bool(capabilities & CAP_AVX2_SELECTED),
        "aarch64_baseline": bool(capabilities & CAP_AARCH64),
    }
    if not report["scalar"]:
        raise AssertionError("native core did not report the mandatory scalar path")
    if report["avx2_selected"] and not report["avx2_available"]:
        raise AssertionError("native core selected AVX2 without reporting it available")
    return report


def _raster_command() -> bytearray:
    command = bytearray([1])  # OP_FILL_POLY
    command.extend(struct.pack("<I", 4))
    for point in ((1.0, 1.0), (6.0, 1.0), (6.0, 6.0), (1.0, 6.0)):
        command.extend(struct.pack("<ff", *point))
    command.extend((37, 99, 235, 255))
    return command


def _expected_raster() -> bytearray:
    expected = bytearray(8 * 8 * 4)
    for y in range(1, 6):
        for x in range(1, 6):
            offset = (y * 8 + x) * 4
            expected[offset : offset + 4] = bytes((37, 99, 235, 255))
    return expected


def _probe(path: Path) -> dict[str, object]:
    library = _load(path)
    abi = library.xy_abi_version()
    if abi != ABI_VERSION:
        raise AssertionError(f"ABI mismatch: probe expects {ABI_VERSION}, library reports {abi}")

    capabilities = _capability_report(library.xy_runtime_capabilities())

    values = array("d", (-4.5, float("nan"), 12.25, float("inf")))
    out_min = ctypes.c_double()
    out_max = ctypes.c_double()
    result = library.xy_min_max(
        _pointer(values, ctypes.c_double),
        len(values),
        ctypes.byref(out_min),
        ctypes.byref(out_max),
    )
    if result != 1 or (out_min.value, out_max.value) != (-4.5, 12.25):
        raise AssertionError(
            f"min/max kernel mismatch: result={result}, values={(out_min.value, out_max.value)}"
        )

    null_result = library.xy_min_max(
        None,
        len(values),
        ctypes.byref(out_min),
        ctypes.byref(out_max),
    )
    if null_result != 0:
        raise AssertionError(f"invalid pointer/length pair returned {null_result}, expected 0")

    command = _raster_command()
    framebuffer = bytearray(8 * 8 * 4)
    raster_result = library.xy_rasterize(
        _pointer(command, ctypes.c_uint8),
        len(command),
        _pointer(framebuffer, ctypes.c_uint8),
        8,
        8,
    )
    expected = _expected_raster()
    if raster_result != 1 or framebuffer != expected:
        raise AssertionError(
            "raster parity mismatch: "
            f"result={raster_result}, actual={hashlib.sha256(framebuffer).hexdigest()}, "
            f"expected={hashlib.sha256(expected).hexdigest()}"
        )
    null_raster = library.xy_rasterize(None, len(command), None, 8, 8)
    if null_raster != 0:
        raise AssertionError(f"invalid raster pointers returned {null_raster}, expected 0")

    return {
        "abi_version": abi,
        "capabilities": capabilities,
        "kernel": {"min": out_min.value, "max": out_max.value},
        "ffi": {"null_min_max": null_result, "null_raster": null_raster},
        "raster": {
            "sha256": hashlib.sha256(framebuffer).hexdigest(),
            "painted_pixels": sum(
                framebuffer[offset + 3] != 0 for offset in range(0, len(framebuffer), 4)
            ),
        },
    }


def _child_probe(path: Path, *, scalar: bool) -> dict[str, object]:
    env = os.environ.copy()
    if scalar:
        env["XY_SIMD"] = "0"
    else:
        env.pop("XY_SIMD", None)
    command = [sys.executable, str(Path(__file__).resolve()), "--probe", "--library", str(path)]
    completed = subprocess.run(command, env=env, text=True, capture_output=True, check=False)
    if completed.returncode:
        raise SystemExit(
            f"native {'scalar' if scalar else 'default'} probe failed\n{completed.stdout}{completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"native probe emitted invalid JSON: {completed.stdout!r}") from exc


def _validate_architecture(
    architecture: str,
    expected_architecture: str,
    expected_default: str,
    default: dict[str, object],
    scalar: dict[str, object],
) -> None:
    if architecture != expected_architecture:
        raise AssertionError(
            f"runtime architecture is {architecture!r}, expected {expected_architecture!r}"
        )
    default_caps = default["capabilities"]
    scalar_caps = scalar["capabilities"]
    assert isinstance(default_caps, dict) and isinstance(scalar_caps, dict)
    if scalar_caps["avx2_selected"]:
        raise AssertionError("XY_SIMD=0 did not force the scalar dispatch path")
    if default_caps["avx2_available"] != scalar_caps["avx2_available"]:
        raise AssertionError("AVX2 hardware availability changed between child probes")

    if expected_default == "avx2":
        if architecture != "x86_64":
            raise AssertionError("AVX2 dispatch can only be required on x86_64")
        if not default_caps["avx2_available"] or not default_caps["avx2_selected"]:
            raise AssertionError(f"required AVX2 path was not exercised: {default_caps}")
        if default_caps["aarch64_baseline"]:
            raise AssertionError("x86_64 runtime incorrectly reported the aarch64 baseline")
    elif expected_default == "aarch64":
        if architecture != "aarch64" or not default_caps["aarch64_baseline"]:
            raise AssertionError(f"required aarch64 baseline was not exercised: {default_caps}")
        if default_caps["avx2_available"] or default_caps["avx2_selected"]:
            raise AssertionError(f"aarch64 runtime incorrectly reported AVX2: {default_caps}")
    elif default_caps["avx2_selected"] or default_caps["aarch64_baseline"]:
        raise AssertionError(f"required scalar-only default was not exercised: {default_caps}")


def _parity_payload(report: dict[str, object]) -> dict[str, object]:
    return {key: report[key] for key in ("abi_version", "kernel", "ffi", "raster")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--expect-arch", choices=("x86_64", "aarch64"))
    parser.add_argument("--expect-default", choices=("scalar", "avx2", "aarch64"))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    with _resolved_library(args.library, args.wheel) as library:
        if args.probe:
            print(json.dumps(_probe(library), sort_keys=True))
            return
        if args.expect_arch is None or args.expect_default is None:
            parser.error("--expect-arch and --expect-default are required for a parity run")

        default = _child_probe(library, scalar=False)
        scalar = _child_probe(library, scalar=True)
        architecture = _normalized_architecture()
        _validate_architecture(
            architecture,
            args.expect_arch,
            args.expect_default,
            default,
            scalar,
        )
        if _parity_payload(default) != _parity_payload(scalar):
            raise AssertionError(
                "default/scalar native outputs differ: "
                f"default={_parity_payload(default)}, scalar={_parity_payload(scalar)}"
            )

        payload = {
            "schema": 1,
            "architecture": architecture,
            "platform": platform.platform(),
            "artifact": args.wheel.name if args.wheel else library.name,
            "expected_default": args.expect_default,
            "default": default,
            "forced_scalar": scalar,
            "parity": True,
        }
        rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.report is not None:
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")


if __name__ == "__main__":
    main()
