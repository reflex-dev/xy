from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_binder_source_build_requires_native_core() -> None:
    environment = (ROOT / ".binder" / "environment.yml").read_text()
    post_build_path = ROOT / ".binder" / "postBuild"
    post_build = post_build_path.read_text()

    assert "rust=" in environment
    assert "nodejs=" in environment
    assert "XY_REQUIRE_CARGO=1" in post_build
    assert "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1" in post_build
    assert "python -m pip install --no-cache-dir ." in post_build
    assert post_build_path.stat().st_mode & 0o111
