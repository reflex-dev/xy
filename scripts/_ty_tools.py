"""Shared resolution helpers for the ``ty`` command-line executable."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def ty_executable_name(os_name: str | None = None) -> str:
    """Return ty's platform-specific executable name."""
    return "ty.exe" if (os.name if os_name is None else os_name) == "nt" else "ty"


def absolute_executable(value: str | os.PathLike[str]) -> Path:
    """Return an absolute executable path, resolving bare commands through PATH."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        resolved = shutil.which(str(path))
        path = Path(resolved) if resolved is not None else Path.cwd() / path
    return path.absolute()


def resolve_ty_executable(
    python: str | os.PathLike[str],
    *,
    required: bool = True,
    os_name: str | None = None,
) -> Path:
    """Resolve the ty executable beside Python first, then through PATH."""
    executable = ty_executable_name(os_name)
    sibling = Path(python).expanduser().with_name(executable)
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return sibling.absolute()
    found = shutil.which(executable)
    if found is not None:
        return Path(found).absolute()
    if required:
        raise FileNotFoundError("cannot find ty beside Python or on PATH")
    return Path(executable)
