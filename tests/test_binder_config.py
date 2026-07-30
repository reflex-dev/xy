from __future__ import annotations

import os
from pathlib import Path

import yaml

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
}


def test_environment_provisions_toolchain_and_notebook_stack() -> None:
    config = yaml.safe_load((BINDER / "environment.yml").read_text())
    assert config["channels"] == ["conda-forge"]
    dependencies = config["dependencies"]
    assert all(isinstance(spec, str) for spec in dependencies)
    names = {spec.split("=", 1)[0] for spec in dependencies}

    # The source build in postBuild needs cargo and node.
    assert {"rust", "nodejs"} <= names
    assert names >= NOTEBOOK_STACK

    # Exact conda build strings (name=version=build) are arch-specific and
    # retired by conda-forge rebuilds — they rot into an unsolvable image.
    assert not any(spec.count("=") > 1 for spec in dependencies)

    # repo2docker's frozen base environment owns the interpreter; the wheel is
    # ABI-agnostic (py3-none, ctypes C ABI), so re-pinning python or pip only
    # forces a downgrade that churns the preinstalled Jupyter stack.
    assert not {"python", "pip"} & names


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

    install_index = lines.index("python -m pip install --no-cache-dir .")

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
