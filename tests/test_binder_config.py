import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_binder_source_build_requires_native_core() -> None:
    environment_lines = (ROOT / ".binder" / "environment.yml").read_text().splitlines()
    post_build_path = ROOT / ".binder" / "postBuild"
    commands = [
        shlex.split(line)
        for line in post_build_path.read_text().splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("#!")
    ]

    dependencies = {
        line.removeprefix("  - ") for line in environment_lines if line.startswith("  - ")
    }
    assert dependencies == {
        "conda-forge",
        "python=3.13.5=h2b335a9_102_cp313",
        "nodejs=22.16.0=hb8e1007_0",
        "rust=1.88.0=h3a20983_0",
        "pip=25.1.1=pyh8b19718_0",
    }
    assert commands == [
        ["set", "-euxo", "pipefail"],
        ["export", "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1"],
        ["export", "XY_REQUIRE_CARGO=1"],
        ["python", "-m", "pip", "install", "--no-cache-dir", "."],
        ["rm", "-rf", "node_modules", "target"],
    ]
    assert post_build_path.stat().st_mode & 0o111
