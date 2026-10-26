"""Real Socket.IO regression gate for Reflex's shared-manager connection order.

Runs independently of the optional Python Reflex/native core dependencies.
Install the repo's pinned npm development dependencies with ``npm ci`` first.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_reflex_socket_connection():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js unavailable")
    result = subprocess.run(
        [node, "--test", "tests/reflex_socket_connection.cjs"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
