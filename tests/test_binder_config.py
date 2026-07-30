from __future__ import annotations

import os
from pathlib import Path

import pytest

# Dev-group-only dependency: the python-floor CI job installs the bare
# package + pytest, so these config tests skip there and run everywhere the
# dev environment exists.
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
BINDER = ROOT / ".binder"

# The scientific stack imported across examples/**/*.ipynb; the checkout
# install itself brings only numpy + anywidget, and repo2docker's frozen base
# environment carries none of these.
NOTEBOOK_STACK = {
    "matplotlib",
    "pandas",
    "scipy",
    "scikit-learn",
    "seaborn",
    "h5py",
    "requests",
    "pysam",
    "gwosc",
}


def test_environment_provisions_toolchain_and_notebook_stack() -> None:
    config = yaml.safe_load((BINDER / "environment.yml").read_text())
    assert config["channels"] == ["conda-forge"]
    dependencies = config["dependencies"]
    assert all(isinstance(spec, str) for spec in dependencies)
    names = {spec.split("=", 1)[0] for spec in dependencies}

    # The source build in postBuild needs cargo and node at the versions the
    # dossier's Binder contract names; everything else rides pip's manylinux
    # wheels in postBuild (smaller solve, and mamba extraction on mybinder
    # builder nodes has proven flaky).
    specs = dict(spec.split("=", 1) for spec in dependencies if "=" in spec)
    assert specs.get("rust") == "1.88.*"
    assert specs.get("nodejs") == "22.*"
    assert not names - {"rust", "nodejs", "python"}

    # Exact conda build strings (name=version=build) are arch-specific and
    # retired by conda-forge rebuilds — they rot into an unsolvable image.
    assert not any(spec.count("=") > 1 for spec in dependencies)

    # repo2docker's default kernel env is Python 3.10, below xy's
    # requires-python floor — the interpreter must be pinned, loosely, to a
    # version the package supports. pip stays unpinned.
    python_specs = [spec for spec in dependencies if spec.split("=", 1)[0] == "python"]
    assert len(python_specs) == 1
    version = python_specs[0].split("=", 1)[1]
    major, minor = version.rstrip(".*").split(".")[:2]
    assert (int(major), int(minor)) >= (3, 11)
    assert "pip" not in names


def test_post_build_requires_the_native_core() -> None:
    post_build = BINDER / "postBuild"
    lines = [
        line.strip()
        for line in post_build.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    # Fail-fast before any command runs, so a broken step fails the image
    # build instead of launching a half-provisioned notebook server.
    assert lines[0] == "set -euxo pipefail"

    install_line = next(line for line in lines if line.startswith("python -m pip install"))
    install_index = lines.index(install_line)
    install_args = install_line.split()

    # The checkout itself, plus the notebook stack from manylinux wheels.
    assert "--no-cache-dir" in install_args
    assert "." in install_args
    assert set(install_args) >= NOTEBOOK_STACK

    # The point of the source install: a missing cargo must fail the image
    # build, never ship a coreless wheel (the hatch hook honors this flag).
    assert lines.index("export XY_REQUIRE_CARGO=1") < install_index

    # npm ci during the hatch build must not pull Playwright's browsers
    # (several hundred MB, devDependencies-only) into the image.
    assert lines.index("export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1") < install_index

    # Build-only caches go after install: the wheel already carries the
    # native core and render client.
    assert any(
        line.startswith("rm -rf") and "node_modules" in line and "target" in line
        for line in lines[install_index + 1 :]
    )

    if os.name != "nt":
        assert post_build.stat().st_mode & 0o111
