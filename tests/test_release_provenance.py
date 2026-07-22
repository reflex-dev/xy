from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "release_provenance.py"
    spec = importlib.util.spec_from_file_location("release_provenance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


provenance = _load_module()


def _manifest(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    wheel = artifacts / "xy-1.2.3-py3-none-any.whl"
    sdist = artifacts / "xy-1.2.3.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    manifest = provenance.create_manifest(
        artifacts,
        source_sha="a" * 40,
        repository="reflex-dev/xy",
        workflow_run_id="1234",
        tag="v1.2.3",
        created_at="2026-07-21T00:00:00+00:00",
    )
    return manifest, wheel, sdist


def test_release_provenance_round_trip(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)

    assert (
        provenance.verify_manifest(
            manifest,
            [wheel, sdist],
            source_sha="a" * 40,
            repository="reflex-dev/xy",
            workflow_run_id="1234",
            tag="v1.2.3",
        )
        == []
    )
    assert manifest["schema"] == provenance.SCHEMA
    assert {record["name"] for record in manifest["artifacts"]} == {wheel.name, sdist.name}


def test_release_provenance_rejects_tampered_artifact(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)
    wheel.write_bytes(b"mutated wheel")

    errors = provenance.verify_manifest(manifest, [wheel, sdist], source_sha="a" * 40)

    assert any("SHA-256 does not match" in error for error in errors)
    assert any("size is" in error for error in errors)


def test_release_provenance_rejects_wrong_source_sha(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)

    errors = provenance.verify_manifest(manifest, [wheel, sdist], source_sha="b" * 40)

    assert any("source SHA" in error for error in errors)


def test_release_provenance_rejects_wrong_identity_metadata(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)

    errors = provenance.verify_manifest(
        manifest,
        [wheel, sdist],
        repository="reflex-dev/not-xy",
        workflow_run_id="9999",
        tag="v9.9.9",
    )

    assert any("repository" in error and "does not match" in error for error in errors)
    assert any("workflow run" in error and "does not match" in error for error in errors)
    assert any("tag" in error and "does not match" in error for error in errors)


def test_release_provenance_rejects_malformed_record_metadata(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)
    manifest["created_at"] = "2026-07-21"
    manifest["artifacts"][0]["path"] = "../escaped.whl"
    manifest["artifacts"][0]["size"] = -1
    manifest["artifacts"][0]["sha256"] = "not-a-digest"

    errors = provenance.verify_manifest(manifest, [wheel, sdist])

    assert any("timezone" in error for error in errors)
    assert any("unsafe path" in error for error in errors)
    assert any("invalid size" in error for error in errors)
    assert any("invalid SHA-256" in error for error in errors)


def test_release_provenance_cli_verifies_downloaded_file(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)
    manifest_path = tmp_path / "release-provenance.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert (
        provenance.main(
            [
                "verify",
                str(manifest_path),
                str(wheel),
                str(sdist),
                "--source-sha",
                "a" * 40,
                "--repository",
                "reflex-dev/xy",
                "--workflow-run-id",
                "1234",
                "--tag",
                "v1.2.3",
            ]
        )
        == 0
    )


def test_release_provenance_rejects_omitted_or_extra_artifacts(tmp_path: Path) -> None:
    manifest, wheel, _ = _manifest(tmp_path)
    extra = tmp_path / "unrecorded.whl"
    extra.write_bytes(b"extra")

    errors = provenance.verify_manifest(manifest, [wheel, extra], source_sha="a" * 40)

    assert any("was not supplied" in error for error in errors)
    assert any("absent from provenance" in error for error in errors)


def test_release_provenance_rejects_duplicate_manifest_records(tmp_path: Path) -> None:
    manifest, wheel, sdist = _manifest(tmp_path)
    manifest["artifacts"].append(dict(manifest["artifacts"][0]))

    errors = provenance.verify_manifest(manifest, [wheel, sdist], source_sha="a" * 40)

    assert any("duplicate artifact records" in error for error in errors)
