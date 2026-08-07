#!/usr/bin/env python3
"""Verify xy wheel artifacts before upload/install smoke tests.

The source checkout can pass every test while the wheel is still broken: missing
static JS, no `py.typed`, a native build tagged pure, or generated junk bundled
by accident. This script is intentionally stdlib-only so CI can run it before
installing the package.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path
from typing import Optional

try:
    from artifact_metadata import dependency_metadata_errors
    from js_exports import missing_esm_exports
except ModuleNotFoundError:  # imported by tests from the repository root
    from scripts.artifact_metadata import dependency_metadata_errors
    from scripts.js_exports import missing_esm_exports

# Mirrors verify_sdist's root-directory shape: a release version (`0.0.2`) plus
# whatever PEP 440 suffix a between-tags build appends (`0.0.3.dev4+g63c0697`).
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[A-Za-z0-9_.+!]*)?$")

REQUIRED_FILES = {
    "reflex_xy/__init__.py",
    "reflex_xy/app.py",
    "reflex_xy/assets/XYChart.jsx",
    "reflex_xy/assets/__init__.py",
    "reflex_xy/component.py",
    "reflex_xy/events.py",
    "reflex_xy/namespace.py",
    "reflex_xy/payload_asset.py",
    "reflex_xy/py.typed",
    "reflex_xy/registry.py",
    "reflex_xy/selections.py",
    "reflex_xy/state_bridge.py",
    "reflex_xy/tokens.py",
    "reflex_xy/vars.py",
    "xy/__init__.py",
    "xy/_native.py",
    "xy/_framing.py",
    "xy/channels.py",
    "xy/channel.py",
    "xy/columns.py",
    "xy/components.py",
    "xy/config.py",
    "xy/export.py",
    "xy/_figure.py",
    "xy/marks.py",
    "xy/interaction.py",
    "xy/kernels.py",
    "xy/lod.py",
    "xy/py.typed",
    "xy/static/index.js",
    "xy/static/standalone.js",
    "xy/widget.py",
}

NATIVE_LIB_RE = re.compile(r"^xy/_native_lib/(?:libxy_core\.(?:so|dylib)|xy_core\.dll)$")
NATIVE_ARTIFACT_SUFFIXES = (".dll", ".dylib", ".pyd", ".so")
FORBIDDEN_PARTS = {"__pycache__", "target", "node_modules", ".pytest_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


@dataclass(frozen=True)
class WheelInfo:
    root_is_purelib: bool
    tags: list[str]


@dataclass(frozen=True)
class NativeBinaryInfo:
    """Architecture facts read from a packaged native library header."""

    format: str
    machine: str
    bits: int
    exported_symbols: frozenset[str] = frozenset()


_ELF_MACHINES = {40: "arm", 62: "x86_64", 183: "aarch64"}
_PE_MACHINES = {0x14C: "x86", 0x8664: "x86_64", 0xAA64: "aarch64"}
_MACHO_CPU_TYPES = {0x01000007: "x86_64", 0x0100000C: "aarch64"}
_WHEEL_TARGETS = {
    "manylinux_2_17_x86_64": ("ELF", "x86_64", 64),
    "manylinux_2_17_aarch64": ("ELF", "aarch64", 64),
    "manylinux_2_17_armv7l": ("ELF", "arm", 32),
    "musllinux_1_2_x86_64": ("ELF", "x86_64", 64),
    "musllinux_1_2_aarch64": ("ELF", "aarch64", 64),
    "musllinux_1_2_armv7l": ("ELF", "arm", 32),
    "macosx_10_12_x86_64": ("Mach-O", "x86_64", 64),
    "macosx_11_0_arm64": ("Mach-O", "aarch64", 64),
    "win_amd64": ("PE", "x86_64", 64),
    "win32": ("PE", "x86", 32),
    "win_arm64": ("PE", "aarch64", 64),
}
_ELF_ALLOWED_GLIBC = {"libc.so.6", "libm.so.6", "libgcc_s.so.1", "ld-linux-x86-64.so.2"}
_ELF_ALLOWED_MUSL_PREFIXES = ("libc.musl-", "ld-musl-", "libgcc_s.so.")
_PE_ALLOWED_IMPORTS = {
    "api-ms-win-core",
    "api-ms-win-crt",
    "kernel32.dll",
    "msvcrt.dll",
    "ucrtbase.dll",
    "vcruntime140.dll",
}


def _inspect_native_binary(name: str, data: bytes) -> NativeBinaryInfo:
    """Read format, machine, and bitness without platform-specific tools."""
    if data[:4] == b"\x7fELF":
        if len(data) < 20:
            raise AssertionError(f"{name} has a truncated ELF header")
        elf_class, endian = data[4], data[5]
        if elf_class not in {1, 2} or endian not in {1, 2}:
            raise AssertionError(f"{name} has an invalid ELF class or byte order")
        prefix = "<" if endian == 1 else ">"
        machine = struct.unpack_from(prefix + "H", data, 18)[0]
        if machine not in _ELF_MACHINES:
            raise AssertionError(f"{name} has unsupported ELF machine {machine}")
        bits = 32 if elf_class == 1 else 64
        symbols = _elf_exported_symbols(name, data, prefix, bits)
        return NativeBinaryInfo("ELF", _ELF_MACHINES[machine], bits, symbols)

    if len(data) >= 8 and data[:4] in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
    }:
        prefix = ">" if data[:4] in {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf"} else "<"
        cputype = struct.unpack_from(prefix + "I", data, 4)[0]
        if cputype not in _MACHO_CPU_TYPES:
            raise AssertionError(f"{name} has unsupported Mach-O CPU type {cputype}")
        bits = 64 if data[:4] in {b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"} else 32
        symbols = _macho_exported_symbols(name, data, prefix, bits)
        return NativeBinaryInfo("Mach-O", _MACHO_CPU_TYPES[cputype], bits, symbols)

    if len(data) >= 0x40 and data[:2] == b"MZ":
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset + 26 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
            raise AssertionError(f"{name} has an invalid PE header")
        machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
        if machine not in _PE_MACHINES:
            raise AssertionError(f"{name} has unsupported PE machine {machine:#x}")
        optional_magic = struct.unpack_from("<H", data, pe_offset + 24)[0]
        if optional_magic not in {0x10B, 0x20B}:
            raise AssertionError(f"{name} has an invalid PE optional-header magic")
        bits = 32 if optional_magic == 0x10B else 64
        symbols = _pe_exported_symbols(name, data, pe_offset, optional_magic, bits)
        return NativeBinaryInfo("PE", _PE_MACHINES[machine], bits, symbols)

    raise AssertionError(f"{name} is not an ELF, Mach-O, or PE native library")


def _elf_exported_symbols(name: str, data: bytes, prefix: str, bits: int) -> frozenset[str]:
    """Read defined global/weak names from an ELF dynamic symbol table."""
    if len(data) < (64 if bits == 64 else 52):
        return frozenset()
    if bits == 64:
        section_offset, section_count = (
            struct.unpack_from(prefix + "QI", data, 40)[0],
            struct.unpack_from(prefix + "H", data, 60)[0],
        )
        section_size, _section_name_index = (
            struct.unpack_from(prefix + "H", data, 58)[0],
            struct.unpack_from(prefix + "H", data, 62)[0],
        )
        section_header_size = section_size
        section_fields = (24, 32, 40, 56)
    else:
        section_offset = struct.unpack_from(prefix + "I", data, 32)[0]
        section_count = struct.unpack_from(prefix + "H", data, 48)[0]
        section_header_size = struct.unpack_from(prefix + "H", data, 46)[0]
        _section_name_index = struct.unpack_from(prefix + "H", data, 50)[0]
        section_fields = (16, 20, 24, 36)
    if not section_offset or not section_count or not section_header_size:
        return frozenset()

    sections: list[tuple[int, int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * section_header_size
        if offset + section_header_size > len(data):
            raise AssertionError(f"{name} has a truncated ELF section table")
        section_type = struct.unpack_from(prefix + "I", data, offset + 4)[0]
        section_file_offset = struct.unpack_from(
            prefix + ("Q" if bits == 64 else "I"), data, offset + section_fields[0]
        )[0]
        section_length = struct.unpack_from(
            prefix + ("Q" if bits == 64 else "I"), data, offset + section_fields[1]
        )[0]
        section_link = struct.unpack_from(prefix + "I", data, offset + section_fields[2])[0]
        section_entry_size = struct.unpack_from(
            prefix + ("Q" if bits == 64 else "I"), data, offset + section_fields[3]
        )[0]
        sections.append(
            (
                section_type,
                section_file_offset,
                section_length,
                section_link,
                section_entry_size,
            )
        )

    dynamic_index = next((i for i, section in enumerate(sections) if section[0] == 11), None)
    if dynamic_index is None:
        return frozenset()
    _, symbol_offset, symbol_length, string_index, entry_size = sections[dynamic_index]
    if string_index >= len(sections):
        raise AssertionError(f"{name} has an invalid ELF dynamic string-table link")
    _, string_offset, string_length, _, _ = sections[string_index]
    symbol_size = 24 if bits == 64 else 16
    entry_size = entry_size or symbol_size
    if entry_size < symbol_size or symbol_offset + symbol_length > len(data):
        raise AssertionError(f"{name} has an invalid ELF dynamic symbol table")
    if string_offset + string_length > len(data):
        raise AssertionError(f"{name} has a truncated ELF dynamic string table")
    strings = data[string_offset : string_offset + string_length]
    exported: set[str] = set()
    symbol_end = symbol_offset + symbol_length - (symbol_length % entry_size)
    for offset in range(symbol_offset, symbol_end, entry_size):
        if bits == 64:
            string_name, info, section_index = (
                struct.unpack_from(prefix + "I", data, offset)[0],
                data[offset + 4],
                struct.unpack_from(prefix + "H", data, offset + 6)[0],
            )
        else:
            string_name = struct.unpack_from(prefix + "I", data, offset)[0]
            info = data[offset + 12]
            section_index = struct.unpack_from(prefix + "H", data, offset + 14)[0]
        if section_index == 0 or info >> 4 not in {1, 2} or string_name >= len(strings):
            continue
        end = strings.find(b"\0", string_name)
        if end > string_name:
            exported.add(strings[string_name:end].decode("utf-8", errors="replace"))
    return frozenset(exported)


def _macho_exported_symbols(name: str, data: bytes, prefix: str, bits: int) -> frozenset[str]:
    """Read externally defined names from a thin Mach-O symbol table."""
    header_size = 32 if bits == 64 else 28
    if len(data) < header_size:
        return frozenset()
    ncommands = struct.unpack_from(prefix + "I", data, 16)[0]
    command_offset = header_size
    symbol_table: tuple[int, int, int, int] | None = None
    for _ in range(ncommands):
        if command_offset + 8 > len(data):
            raise AssertionError(f"{name} has a truncated Mach-O load-command table")
        command, command_size = struct.unpack_from(prefix + "II", data, command_offset)
        if command_size < 8 or command_offset + command_size > len(data):
            raise AssertionError(f"{name} has an invalid Mach-O load command")
        if command == 2 and command_size >= 24:  # LC_SYMTAB
            symbol_table = struct.unpack_from(prefix + "IIII", data, command_offset + 8)
            break
        command_offset += command_size
    if symbol_table is None:
        return frozenset()
    symbol_offset, symbol_count, string_offset, string_size = symbol_table
    entry_size = 16 if bits == 64 else 12
    if string_offset + string_size > len(data):
        raise AssertionError(f"{name} has a truncated Mach-O string table")
    strings = data[string_offset : string_offset + string_size]
    exported: set[str] = set()
    for index in range(symbol_count):
        offset = symbol_offset + index * entry_size
        if offset + entry_size > len(data):
            raise AssertionError(f"{name} has a truncated Mach-O symbol table")
        string_name = struct.unpack_from(prefix + "I", data, offset)[0]
        symbol_type = data[offset + 4]
        if not symbol_type & 0x01 or symbol_type & 0x0E == 0x00 or string_name >= len(strings):
            continue
        end = strings.find(b"\0", string_name)
        if end > string_name:
            exported.add(strings[string_name:end].decode("utf-8", errors="replace").lstrip("_"))
    return frozenset(exported)


def _pe_exported_symbols(
    name: str, data: bytes, pe_offset: int, optional_magic: int, bits: int
) -> frozenset[str]:
    """Read names from the PE export directory."""
    optional_offset = pe_offset + 24
    data_directory_offset = optional_offset + (96 if optional_magic == 0x10B else 112)
    if data_directory_offset + 8 > len(data):
        return frozenset()
    export_rva, export_size = struct.unpack_from("<II", data, data_directory_offset)
    if not export_rva or not export_size:
        return frozenset()
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_offset = optional_offset + optional_size
    sections: list[tuple[int, int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        if offset + 40 > len(data):
            raise AssertionError(f"{name} has a truncated PE section table")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset, raw_size))

    def file_offset(rva: int) -> int:
        for virtual_address, size, raw_offset, _raw_size in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_offset + (rva - virtual_address)
        raise AssertionError(f"{name} has an export RVA outside its PE sections")

    export_offset = file_offset(export_rva)
    if export_offset + 40 > len(data):
        raise AssertionError(f"{name} has a truncated PE export directory")
    number_of_names = struct.unpack_from("<I", data, export_offset + 24)[0]
    names_rva = struct.unpack_from("<I", data, export_offset + 32)[0]
    names_offset = file_offset(names_rva)
    exported: set[str] = set()
    for index in range(number_of_names):
        offset = names_offset + index * 4
        if offset + 4 > len(data):
            raise AssertionError(f"{name} has a truncated PE export-name table")
        string_offset = file_offset(struct.unpack_from("<I", data, offset)[0])
        end = data.find(b"\0", string_offset)
        if end > string_offset:
            exported.add(data[string_offset:end].decode("ascii", errors="replace"))
    return frozenset(exported)


def _macho_linkage(
    name: str, data: bytes, prefix: str, bits: int
) -> tuple[tuple[str, ...], tuple[int, int] | None]:
    """Read loaded dylibs and the minimum macOS version from Mach-O commands."""
    header_size = 32 if bits == 64 else 28
    if len(data) < header_size:
        raise AssertionError(f"{name} has a truncated Mach-O header")
    ncommands = struct.unpack_from(prefix + "I", data, 16)[0]
    command_offset = header_size
    dependencies: list[str] = []
    minimum: tuple[int, int] | None = None
    dylib_commands = {0xC, 0x18 | 0x80000000, 0x1F | 0x80000000}
    for _ in range(ncommands):
        if command_offset + 8 > len(data):
            raise AssertionError(f"{name} has a truncated Mach-O load-command table")
        command, command_size = struct.unpack_from(prefix + "II", data, command_offset)
        if command_size < 8 or command_offset + command_size > len(data):
            raise AssertionError(f"{name} has an invalid Mach-O load command")
        if command in dylib_commands and command_size >= 24:
            name_offset = struct.unpack_from(prefix + "I", data, command_offset + 8)[0]
            start = command_offset + name_offset
            end = data.find(b"\0", start, command_offset + command_size)
            if end > start:
                dependencies.append(data[start:end].decode("utf-8", errors="replace"))
        elif command == 0x32 and command_size >= 16:  # LC_BUILD_VERSION
            version = struct.unpack_from(prefix + "I", data, command_offset + 12)[0]
            minimum = (version >> 16, (version >> 8) & 0xFF)
        elif command == 0x24 and command_size >= 16:  # LC_VERSION_MIN_MACOSX
            version = struct.unpack_from(prefix + "I", data, command_offset + 8)[0]
            minimum = (version >> 16, (version >> 8) & 0xFF)
        command_offset += command_size
    return tuple(dependencies), minimum


def _pe_imports(name: str, data: bytes, pe_offset: int, optional_magic: int) -> tuple[str, ...]:
    """Read DLL names from the PE import directory."""
    optional_offset = pe_offset + 24
    data_directory_offset = optional_offset + (104 if optional_magic == 0x10B else 120)
    if data_directory_offset + 8 > len(data):
        return ()
    import_rva, import_size = struct.unpack_from("<II", data, data_directory_offset)
    if not import_rva or not import_size:
        return ()
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_offset = optional_offset + optional_size
    sections: list[tuple[int, int, int]] = []
    for index in range(section_count):
        offset = section_offset + index * 40
        if offset + 40 > len(data):
            raise AssertionError(f"{name} has a truncated PE section table")
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def file_offset(rva: int) -> int:
        for virtual_address, size, raw_offset in sections:
            if virtual_address <= rva < virtual_address + size:
                return raw_offset + rva - virtual_address
        raise AssertionError(f"{name} has an import RVA outside its PE sections")

    import_offset = file_offset(import_rva)
    imports: list[str] = []
    for offset in range(import_offset, import_offset + import_size, 20):
        if offset + 20 > len(data):
            raise AssertionError(f"{name} has a truncated PE import directory")
        original_thunk, timestamp, forwarder, name_rva, first_thunk = struct.unpack_from(
            "<IIIII", data, offset
        )
        if not any((original_thunk, timestamp, forwarder, name_rva, first_thunk)):
            break
        string_offset = file_offset(name_rva)
        end = data.find(b"\0", string_offset)
        if end <= string_offset:
            raise AssertionError(f"{name} has an unterminated PE import name")
        imports.append(data[string_offset:end].decode("ascii", errors="replace"))
    return tuple(imports)


def _require_native_target(name: str, data: bytes, platform: str) -> None:
    expected = _WHEEL_TARGETS.get(platform)
    if expected is None:
        raise AssertionError(
            f"no native binary contract is defined for wheel platform {platform!r}"
        )
    actual = _inspect_native_binary(name, data)
    if (actual.format, actual.machine, actual.bits) != expected:
        raise AssertionError(
            f"{name} identifies as {actual.format}/{actual.machine}/{actual.bits}-bit, "
            f"expected {expected[0]}/{expected[1]}/{expected[2]}-bit for {platform}"
        )


def _require_exported_symbols(name: str, data: bytes, required: set[str]) -> None:
    """Require ABI symbols from the binary's export table."""
    info = _inspect_native_binary(name, data)
    missing = sorted(required - info.exported_symbols)
    if missing:
        raise AssertionError(f"{name} is missing exported ABI symbols: {missing}")


def _elf_linkage(name: str, data: bytes, prefix: str, bits: int) -> tuple[str, tuple[str, ...]]:
    """Return the ELF interpreter and DT_NEEDED names."""
    if bits == 64:
        if len(data) < 64:
            raise AssertionError(f"{name} has a truncated ELF header")
        program_offset = struct.unpack_from(prefix + "Q", data, 32)[0]
        program_entry_size = struct.unpack_from(prefix + "H", data, 54)[0]
        program_count = struct.unpack_from(prefix + "H", data, 56)[0]
        program_fields = (8, 16, 32)
        dynamic_entry_size = 16
    else:
        if len(data) < 52:
            raise AssertionError(f"{name} has a truncated ELF header")
        program_offset = struct.unpack_from(prefix + "I", data, 28)[0]
        program_entry_size = struct.unpack_from(prefix + "H", data, 42)[0]
        program_count = struct.unpack_from(prefix + "H", data, 44)[0]
        program_fields = (4, 8, 16)
        dynamic_entry_size = 8
    if not program_offset or not program_entry_size or not program_count:
        raise AssertionError(f"{name} has no ELF program headers")

    load_segments: list[tuple[int, int, int, int]] = []
    interpreter: str | None = None
    dynamic: tuple[int, int] | None = None
    number_size = "Q" if bits == 64 else "I"
    for index in range(program_count):
        offset = program_offset + index * program_entry_size
        if offset + program_entry_size > len(data):
            raise AssertionError(f"{name} has a truncated ELF program-header table")
        program_type = struct.unpack_from(prefix + "I", data, offset)[0]
        file_offset = struct.unpack_from(prefix + number_size, data, offset + program_fields[0])[0]
        virtual_address = struct.unpack_from(
            prefix + number_size, data, offset + program_fields[1]
        )[0]
        file_size = struct.unpack_from(prefix + number_size, data, offset + program_fields[2])[0]
        if program_type == 1:
            load_segments.append((virtual_address, file_offset, file_size, file_size))
        elif program_type == 3:
            raw = data[file_offset : file_offset + file_size]
            interpreter = raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        elif program_type == 2:
            dynamic = (file_offset, file_size)
    if dynamic is None:
        return interpreter or "", ()

    def virtual_to_file(address: int) -> int:
        for virtual_address, file_offset, file_size, _ in load_segments:
            if virtual_address <= address < virtual_address + file_size:
                return file_offset + address - virtual_address
        raise AssertionError(f"{name} has an ELF dynamic string table outside load segments")

    dynamic_offset, dynamic_size = dynamic
    needed: list[int] = []
    string_address = string_size = None
    for offset in range(dynamic_offset, dynamic_offset + dynamic_size, dynamic_entry_size):
        if offset + dynamic_entry_size > len(data):
            raise AssertionError(f"{name} has a truncated ELF dynamic section")
        tag = struct.unpack_from(prefix + number_size, data, offset)[0]
        value = struct.unpack_from(prefix + number_size, data, offset + (8 if bits == 64 else 4))[0]
        if tag == 0:
            break
        if tag == 1:
            needed.append(value)
        elif tag == 5:
            string_address = value
        elif tag == 10:
            string_size = value
    if string_address is None or string_size is None:
        raise AssertionError(f"{name} has DT_NEEDED entries but no complete dynamic string table")
    string_offset = virtual_to_file(string_address)
    strings = data[string_offset : string_offset + string_size]
    if len(strings) != string_size:
        raise AssertionError(f"{name} has a truncated ELF dynamic string table")
    dependencies = []
    for string_index in needed:
        if string_index >= len(strings):
            raise AssertionError(f"{name} has an invalid DT_NEEDED string index")
        end = strings.find(b"\0", string_index)
        if end < string_index:
            raise AssertionError(f"{name} has an unterminated DT_NEEDED name")
        dependencies.append(strings[string_index:end].decode("utf-8", errors="replace"))
    return interpreter or "", tuple(dependencies)


def _require_elf_linkage(name: str, data: bytes, platform: str) -> None:
    """Validate libc family and dependency policy for Linux wheel targets."""
    if data[:4] != b"\x7fELF":
        raise AssertionError(f"{name} is not an ELF binary for Linux linkage validation")
    endian = data[5]
    prefix = "<" if endian == 1 else ">" if endian == 2 else ""
    if not prefix:
        raise AssertionError(f"{name} has an invalid ELF byte order")
    bits = 32 if data[4] == 1 else 64 if data[4] == 2 else 0
    if not bits:
        raise AssertionError(f"{name} has an invalid ELF class")
    interpreter, dependencies = _elf_linkage(name, data, prefix, bits)
    if platform.startswith("manylinux_"):
        if interpreter and "ld-linux" not in interpreter:
            raise AssertionError(f"{name} is not linked against glibc: interpreter={interpreter!r}")
        if not interpreter and "libc.so.6" not in dependencies:
            raise AssertionError(f"{name} has no detectable glibc linkage")
        unexpected = sorted(set(dependencies) - _ELF_ALLOWED_GLIBC)
        if unexpected:
            raise AssertionError(f"{name} has unsupported glibc dependencies: {unexpected}")
        versions = {
            (int(match.group(1)), int(match.group(2)))
            for match in re.finditer(rb"GLIBC_(\d+)\.(\d+)", data)
        }
        if versions and max(versions) > (2, 17):
            version = ".".join(map(str, max(versions)))
            raise AssertionError(f"{name} requires glibc {version}, above manylinux_2_17")
    elif platform.startswith("musllinux_"):
        if "musl" not in interpreter:
            raise AssertionError(f"{name} is not linked against musl: interpreter={interpreter!r}")
        unexpected = sorted(
            dependency
            for dependency in dependencies
            if not dependency.startswith(_ELF_ALLOWED_MUSL_PREFIXES)
        )
        if unexpected:
            raise AssertionError(f"{name} has unsupported musl dependencies: {unexpected}")


def _require_macho_linkage(name: str, data: bytes, platform: str) -> None:
    magic = data[:4]
    if magic not in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
    }:
        raise AssertionError(f"{name} is not a Mach-O binary for macOS linkage validation")
    prefix = ">" if magic in {b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf"} else "<"
    bits = 64 if magic in {b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"} else 32
    dependencies, minimum = _macho_linkage(name, data, prefix, bits)
    unexpected = sorted(
        dependency
        for dependency in dependencies
        if not dependency.startswith(("/usr/lib/", "/System/Library/", "@rpath/", "@loader_path/"))
    )
    if unexpected:
        raise AssertionError(f"{name} has unsupported macOS dependencies: {unexpected}")
    expected_floor = (11, 0) if platform.endswith("arm64") else (10, 12)
    if minimum is None:
        raise AssertionError(f"{name} has no macOS deployment target")
    if minimum > expected_floor:
        raise AssertionError(
            f"{name} targets macOS {minimum[0]}.{minimum[1]}, above {expected_floor[0]}.{expected_floor[1]}"
        )


def _require_pe_linkage(name: str, data: bytes) -> None:
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise AssertionError(f"{name} is not a PE binary for Windows linkage validation")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 26 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise AssertionError(f"{name} has an invalid PE header")
    optional_magic = struct.unpack_from("<H", data, pe_offset + 24)[0]
    if optional_magic not in {0x10B, 0x20B}:
        raise AssertionError(f"{name} has an invalid PE optional-header magic")
    imports = _pe_imports(name, data, pe_offset, optional_magic)
    if not imports:
        raise AssertionError(f"{name} has no Windows import table")
    unexpected = sorted(
        dependency
        for dependency in imports
        if not any(dependency.casefold().startswith(prefix) for prefix in _PE_ALLOWED_IMPORTS)
    )
    if unexpected:
        raise AssertionError(f"{name} has unsupported Windows imports: {unexpected}")


def _dist_info_name(names: set[str], filename: str) -> str:
    matches = [n for n in names if n.endswith(f".dist-info/{filename}")]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {filename}, found {matches}")
    return matches[0]


def _require_dist_info_version(names: set[str], expected_version: str) -> None:
    """The `.dist-info` directory must be named for the same version as the file."""
    directory = _dist_info_name(names, "METADATA").split("/", 1)[0]
    if directory != f"xy-{expected_version}.dist-info":
        raise AssertionError(
            f"wheel has {directory!r} but its filename says version {expected_version!r}"
        )


def _require_unique_archive_members(infos: list[zipfile.ZipInfo]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for info in infos:
        if info.filename in seen:
            duplicates.add(info.filename)
        seen.add(info.filename)
    if duplicates:
        raise AssertionError(f"wheel contains duplicate archive entries: {sorted(duplicates)}")


def _require_only_shippable_roots(names: set[str]) -> None:
    unexpected = sorted(
        name
        for name in names
        if name.rstrip("/")
        and not (
            name.startswith(("reflex_xy/", "xy/")) or name.split("/", 1)[0].endswith(".dist-info")
        )
    )
    if unexpected:
        raise AssertionError(
            "wheel contains non-package source/example files that belong in the sdist only: "
            f"{unexpected}"
        )


def _parse_wheel(names: set[str], data: bytes) -> WheelInfo:
    root: Optional[bool] = None
    tags: list[str] = []
    for raw in data.decode("utf-8").splitlines():
        if raw.startswith("Root-Is-Purelib:"):
            value = raw.split(":", 1)[1].strip().lower()
            if value not in {"true", "false"}:
                raise AssertionError(f"invalid Root-Is-Purelib value {value!r}")
            root = value == "true"
        elif raw.startswith("Tag:"):
            tags.append(raw.split(":", 1)[1].strip())
    if root is None:
        raise AssertionError(f"{_dist_info_name(names, 'WHEEL')} missing Root-Is-Purelib")
    if not tags:
        raise AssertionError(f"{_dist_info_name(names, 'WHEEL')} missing Tag")
    return WheelInfo(root_is_purelib=root, tags=tags)


def _filename_tag(path: Path) -> str:
    if path.suffix != ".whl":
        raise AssertionError(f"wheel artifact must end in .whl: {path.name}")
    parts = path.name[:-4].split("-")
    if len(parts) not in {5, 6}:
        raise AssertionError(
            "wheel filename must follow "
            "{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl: "
            f"{path.name}"
        )
    return "-".join(parts[-3:])


def _require_filename_tag(path: Path, tags: list[str]) -> None:
    filename_tag = _filename_tag(path)
    if filename_tag not in tags:
        raise AssertionError(
            f"wheel filename tag {filename_tag!r} is not listed in WHEEL tags {tags}"
        )


def _require_metadata(names: set[str], data: bytes, expected_version: str) -> None:
    text = data.decode("utf-8")
    metadata = Parser().parsestr(text)
    missing: list[str] = []
    if metadata.get("Name", "").strip() != "xy":
        missing.append("Name: xy")
    if metadata.get("Version", "").strip() != expected_version:
        missing.append(f"Version: {expected_version}")
    if metadata.get("Requires-Python", "").strip() != ">=3.11":
        missing.append("Requires-Python: >=3.11")
    missing.extend(dependency_metadata_errors(metadata))
    if missing:
        raise AssertionError(f"missing or invalid METADATA lines: {missing}")
    _dist_info_name(names, "METADATA")


def _filename_version(path: Path) -> str:
    """The version the wheel *claims* to be, taken from its own filename.

    pyproject no longer carries a version to compare against — it is derived
    from the git tag at build time — so the invariant this can still enforce is
    internal consistency: the filename installers key off and the METADATA pip
    records must agree. A build that resolved the version twice and differently
    (say, a tagless CI checkout mid-way through) shows up as exactly that
    disagreement.
    """
    version = path.name[:-4].split("-")[1]
    if not VERSION_RE.match(version):
        raise AssertionError(f"wheel filename has an unexpected version segment: {path.name}")
    return version


def _decode_substantial_bundle(name: str, data: bytes) -> str:
    text = data.decode("utf-8")
    if len(text) < 1000:
        raise AssertionError(f"{name} is suspiciously small")
    return text


def _require_static_bundle(name: str, data: bytes, needles: set[str]) -> None:
    text = _decode_substantial_bundle(name, data)
    missing = sorted(needle for needle in needles if needle not in text)
    if missing:
        raise AssertionError(f"{name} missing expected JS markers: {missing}")


def _require_static_esm_exports(name: str, data: bytes, required: set[str]) -> None:
    text = _decode_substantial_bundle(name, data)
    missing = missing_esm_exports(text, required)
    if missing:
        raise AssertionError(f"{name} missing expected exports: {missing}")


def _require_text_markers(name: str, data: bytes, needles: set[str]) -> None:
    text = data.decode("utf-8")
    if len(text.strip()) < 20:
        raise AssertionError(f"{name} is suspiciously small")
    missing = sorted(needle for needle in needles if needle not in text)
    if missing:
        raise AssertionError(f"{name} missing expected markers: {missing}")


def _require_py_typed_marker(data: bytes, name: str = "xy/py.typed") -> None:
    if data != b"":
        raise AssertionError(f"{name} must be an empty full-package PEP 561 marker")


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _require_record(zf: zipfile.ZipFile, names: set[str]) -> None:
    record_name = _dist_info_name(names, "RECORD")
    text = zf.read(record_name).decode("utf-8")
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        raise AssertionError(f"{record_name} does not list archive files")

    record_paths: list[str] = []
    records: dict[str, tuple[str, str]] = {}
    for row in rows:
        if len(row) != 3:
            raise AssertionError(f"{record_name} rows must have exactly 3 fields")
        archive_name, digest, size = row
        if not archive_name:
            raise AssertionError(f"{record_name} contains an empty archive path")
        if archive_name.startswith("/") or "\\" in archive_name or ".." in Path(archive_name).parts:
            raise AssertionError(f"{record_name} contains unsafe archive path {archive_name!r}")
        if archive_name in records:
            raise AssertionError(f"{record_name} lists {archive_name!r} more than once")
        record_paths.append(archive_name)
        records[archive_name] = (digest, size)

    archive_files = {name for name in names if not name.endswith("/")}
    listed_files = set(record_paths)
    missing = sorted(archive_files - listed_files)
    extra = sorted(listed_files - archive_files)
    if missing or extra:
        raise AssertionError(
            f"{record_name} does not match archive files; missing={missing}, extra={extra}"
        )

    for archive_name in record_paths:
        digest, size = records[archive_name]
        if archive_name == record_name:
            if digest or size:
                raise AssertionError(f"{record_name} row must have empty hash and size")
            continue
        if not digest.startswith("sha256="):
            raise AssertionError(f"{record_name} row for {archive_name} missing sha256 hash")
        expected_digest = _record_hash(zf.read(archive_name))
        if digest != f"sha256={expected_digest}":
            raise AssertionError(f"{record_name} hash mismatch for {archive_name}")
        try:
            recorded_size = int(size)
        except ValueError as exc:
            raise AssertionError(
                f"{record_name} row for {archive_name} has invalid size {size!r}"
            ) from exc
        actual_size = zf.getinfo(archive_name).file_size
        if recorded_size != actual_size:
            raise AssertionError(
                f"{record_name} size mismatch for {archive_name}: "
                f"record={recorded_size}, archive={actual_size}"
            )


def verify_wheel(
    path: Path,
    *,
    expect_native: Optional[bool],
    expect_platform: Optional[str] = None,
    required_symbols: Optional[set[str]] = None,
    require_linkage: bool = False,
) -> None:
    if require_linkage and (expect_native is not True or expect_platform is None):
        raise AssertionError(
            "linkage validation requires an expected native wheel platform tag"
        )
    with zipfile.ZipFile(path) as zf:
        _require_unique_archive_members(zf.infolist())
        names = set(zf.namelist())
        _require_only_shippable_roots(names)
        wheel = _parse_wheel(names, zf.read(_dist_info_name(names, "WHEEL")))
        _require_filename_tag(path, wheel.tags)
        expected_version = _filename_version(path)
        _require_dist_info_version(names, expected_version)
        _require_metadata(names, zf.read(_dist_info_name(names, "METADATA")), expected_version)
        _require_record(zf, names)

    missing = sorted(REQUIRED_FILES - names)
    if missing:
        raise AssertionError(f"wheel missing required package files: {missing}")

    with zipfile.ZipFile(path) as zf:
        _require_text_markers(
            "xy/__init__.py",
            zf.read("xy/__init__.py"),
            {"__version__", "__all__", "_EXPORTS", "__getattr__"},
        )
        _require_text_markers(
            "reflex_xy/__init__.py",
            zf.read("reflex_xy/__init__.py"),
            {"XYPlugin", "chart", "figure", "__version__", '_distribution_version("xy")'},
        )
        _require_text_markers(
            "reflex_xy/assets/XYChart.jsx",
            zf.read("reflex_xy/assets/XYChart.jsx"),
            {"XYChart", "xy_client.js"},
        )
        _require_text_markers(
            "xy/_figure.py",
            zf.read("xy/_figure.py"),
            {
                "class Figure",
                "scatter = _marks.scatter",
                "line = _marks.line",
                "def to_html(",
                "def to_png(",
            },
        )
        _require_text_markers(
            "xy/marks.py",
            zf.read("xy/marks.py"),
            {"def scatter(", "def line(", "def heatmap("},
        )
        _require_text_markers(
            "xy/components.py",
            zf.read("xy/components.py"),
            {"class Chart", "def to_html(", "def to_png(", "dict[str, Any]"},
        )
        _require_text_markers(
            "xy/export.py",
            zf.read("xy/export.py"),
            {
                "_bundled_js",
                "_json_for_inline_script",
                "_javascript_for_inline_script",
                "def html_to_png(",
                "def to_png(",
                "XY_CHROMIUM",
            },
        )
        _require_text_markers(
            "xy/kernels.py",
            zf.read("xy/kernels.py"),
            {"BACKEND", "_native", "ImportError"},
        )
        _require_py_typed_marker(zf.read("xy/py.typed"))
        _require_py_typed_marker(zf.read("reflex_xy/py.typed"), "reflex_xy/py.typed")
        _require_static_esm_exports(
            "xy/static/index.js",
            zf.read("xy/static/index.js"),
            # Minified bundle: assert the exported public surface, not source lines.
            {"render", "renderStandalone", "decodeFrame", "ChartView"},
        )
        _require_static_bundle(
            "xy/static/standalone.js",
            zf.read("xy/static/standalone.js"),
            # Minified IIFE namespace: `var xy` is window.xy in a classic script.
            {"var xy=", ".renderStandalone=", ".decodeFrame=", ".ChartView="},
        )

    forbidden = sorted(
        n
        for n in names
        if any(part in FORBIDDEN_PARTS for part in Path(n).parts)
        or any(n.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
    )
    if forbidden:
        raise AssertionError(f"wheel contains generated/cache files: {forbidden}")

    native_libs = sorted(n for n in names if NATIVE_LIB_RE.match(n))
    unexpected_native = sorted(
        n for n in names if n.endswith(NATIVE_ARTIFACT_SUFFIXES) and not NATIVE_LIB_RE.match(n)
    )
    if unexpected_native:
        raise AssertionError(f"wheel contains unexpected native artifacts: {unexpected_native}")
    if expect_native is True:
        if len(native_libs) != 1:
            raise AssertionError(
                f"native wheel must contain exactly one native lib, got {native_libs}"
            )
        if wheel.root_is_purelib:
            raise AssertionError("native wheel must set Root-Is-Purelib: false")
        if any(tag == "py3-none-any" for tag in wheel.tags):
            raise AssertionError(f"native wheel must not use a pure tag: {wheel.tags}")
        if expect_platform is not None or required_symbols:
            with zipfile.ZipFile(path) as zf:
                native_data = zf.read(native_libs[0])
            if expect_platform is not None:
                _require_native_target(native_libs[0], native_data, expect_platform)
            if required_symbols:
                _require_exported_symbols(native_libs[0], native_data, required_symbols)
            if require_linkage:
                if expect_platform.startswith(("manylinux_", "musllinux_")):
                    _require_elf_linkage(native_libs[0], native_data, expect_platform)
                elif expect_platform.startswith("macosx_"):
                    _require_macho_linkage(native_libs[0], native_data, expect_platform)
                elif expect_platform.startswith("win_") or expect_platform == "win32":
                    _require_pe_linkage(native_libs[0], native_data)
                else:
                    raise AssertionError(
                        f"linkage inspection is not implemented for wheel platform {expect_platform!r}"
                    )
    elif expect_native is False:
        if native_libs:
            raise AssertionError(
                f"pure (no-native) wheel must not contain native libs: {native_libs}"
            )
        if not wheel.root_is_purelib:
            raise AssertionError("pure (no-native) wheel must set Root-Is-Purelib: true")
        if "py3-none-any" not in wheel.tags:
            raise AssertionError(
                f"pure (no-native) wheel must advertise py3-none-any, got {wheel.tags}"
            )
    elif native_libs and wheel.root_is_purelib:
        raise AssertionError("wheel contains a native lib but is tagged pure")
    elif not native_libs and not wheel.root_is_purelib:
        raise AssertionError("wheel is tagged non-pure but contains no native lib")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--expect-native", action="store_true")
    group.add_argument("--expect-pure", action="store_true")
    parser.add_argument(
        "--expect-platform",
        help="validate the native library header against this wheel platform tag",
    )
    parser.add_argument(
        "--require-symbol",
        action="append",
        default=[],
        help="require an exported native ABI symbol (repeatable)",
    )
    parser.add_argument(
        "--require-linkage",
        action="store_true",
        help="validate native dynamic linkage against --expect-platform",
    )
    args = parser.parse_args(argv)

    expect_native = True if args.expect_native else False if args.expect_pure else None
    try:
        verify_wheel(
            args.wheel,
            expect_native=expect_native,
            expect_platform=args.expect_platform,
            required_symbols=set(args.require_symbol),
            require_linkage=args.require_linkage,
        )
    except (AssertionError, KeyError, struct.error, zipfile.BadZipFile) as e:
        print(f"wheel verification failed for {args.wheel}: {e}", file=sys.stderr)
        return 1
    print(f"wheel verification OK: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
