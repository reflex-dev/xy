from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_release_version.py"
    spec = importlib.util.spec_from_file_location("check_release_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_release_version = _load_module()


def test_gate_passes_a_release_tag() -> None:
    assert check_release_version.check_release("v0.2.0") == []


def test_gate_rejects_a_tag_that_is_not_a_release_tag() -> None:
    # The docs site deploys on CalVer tags (2026.WW.N) that the version
    # derivation deliberately ignores; one must never publish a release.
    errors = check_release_version.check_release("2026.30.1")

    assert any("is not a release tag" in e for e in errors)


def test_gate_rejects_a_derived_development_version_tag() -> None:
    errors = check_release_version.check_release("v0.0.3.dev4+g63c0697")

    assert any("is not a release tag" in e for e in errors)


def test_gate_passes_a_canonical_prerelease_tag() -> None:
    assert check_release_version.check_release("v0.0.1a1") == []


def test_gate_passes_prerelease_tags_for_the_core_too() -> None:
    assert check_release_version.check_release("v1.0.0rc2") == []


def test_gate_rejects_non_canonical_prerelease_spellings() -> None:
    # The derivation normalizes `alpha1` to `a1`, so a non-canonical tag can
    # never equal its own built version — refuse it before it builds anything.
    for tag in ("v0.0.1-alpha1", "v0.0.1alpha1", "v0.0.1a"):
        errors = check_release_version.check_release(tag)
        assert any("is not a release tag" in e for e in errors), tag


def test_gate_passes_a_post_release_tag() -> None:
    # `release-post` materializes 1.2.3.post1 for a packaging-only re-release of
    # an already-published version; uv-dynamic-versioning derives it from the
    # matching tag, so the gate must not stand in its way.
    assert check_release_version.check_release("v0.0.6.post1") == []


def test_gate_passes_a_post_release_of_a_prerelease() -> None:
    assert check_release_version.check_release("v1.0.0rc1.post2") == []


def test_gate_ignores_the_changelog() -> None:
    # The changelog decides *which* version ships (its newest untagged version
    # is the publish trigger); this gate only judges the shape of the tag that
    # records it, so it never reads CHANGELOG.md.
    assert check_release_version.check_release("v9.9.9") == []


def test_main_requires_a_tag(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)

    assert check_release_version.main([]) == 1


def test_main_reports_a_bad_tag_shape() -> None:
    assert check_release_version.main(["--tag", "v0.0.6+local"]) == 1


def test_main_accepts_a_release_tag() -> None:
    assert check_release_version.main(["--tag", "v0.0.6"]) == 0
