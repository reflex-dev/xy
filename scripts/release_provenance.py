#!/usr/bin/env python3
"""Create and verify SHA-256 provenance for immutable release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "xy-release-provenance-v1"
SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
RUN_ID_RE = re.compile(r"[1-9][0-9]*")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def create_manifest(
    artifact_root: Path,
    *,
    source_sha: str,
    repository: str,
    workflow_run_id: str,
    tag: str,
    created_at: str | None = None,
) -> dict[str, Any]:
    if SHA_RE.fullmatch(source_sha) is None:
        raise ValueError("source_sha must be a 40-character lowercase commit SHA")
    if REPOSITORY_RE.fullmatch(repository) is None:
        raise ValueError("repository must be owner/name")
    if RUN_ID_RE.fullmatch(str(workflow_run_id)) is None:
        raise ValueError("workflow_run_id must be a positive integer")
    if TAG_RE.fullmatch(tag) is None:
        raise ValueError("tag contains unsupported characters")
    timestamp = created_at or datetime.now(UTC).isoformat()
    _parse_timestamp(timestamp)
    files = sorted(path for path in artifact_root.rglob("*") if path.is_file())
    if not files:
        raise ValueError(f"no artifacts found under {artifact_root}")
    names = [path.name for path in files]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"artifact basenames must be unique: {duplicates}")
    return {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "repository": repository,
        "workflow_run_id": str(workflow_run_id),
        "tag": tag,
        "created_at": timestamp,
        "artifacts": [
            {
                "name": path.name,
                "path": path.relative_to(artifact_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _digest(path),
            }
            for path in files
        ],
    }


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("created_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("created_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    return parsed


def verify_manifest(
    manifest: dict[str, Any],
    artifacts: list[Path],
    *,
    source_sha: str | None = None,
    repository: str | None = None,
    workflow_run_id: str | None = None,
    tag: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != SCHEMA:
        errors.append(f"unsupported provenance schema {manifest.get('schema')!r}")
    manifest_sha = manifest.get("source_sha")
    if not isinstance(manifest_sha, str) or SHA_RE.fullmatch(manifest_sha) is None:
        errors.append("provenance source_sha is not a lowercase 40-character commit SHA")
    if source_sha is not None and manifest.get("source_sha") != source_sha:
        errors.append(
            f"provenance source SHA {manifest.get('source_sha')!r} does not match {source_sha!r}"
        )
    manifest_repository = manifest.get("repository")
    if (
        not isinstance(manifest_repository, str)
        or REPOSITORY_RE.fullmatch(manifest_repository) is None
    ):
        errors.append("provenance repository is not owner/name")
    if repository is not None and manifest_repository != repository:
        errors.append(
            f"provenance repository {manifest_repository!r} does not match {repository!r}"
        )
    manifest_run_id = manifest.get("workflow_run_id")
    if not isinstance(manifest_run_id, str) or RUN_ID_RE.fullmatch(manifest_run_id) is None:
        errors.append("provenance workflow_run_id is not a positive integer")
    if workflow_run_id is not None and manifest_run_id != str(workflow_run_id):
        errors.append(
            f"provenance workflow run {manifest_run_id!r} does not match {str(workflow_run_id)!r}"
        )
    manifest_tag = manifest.get("tag")
    if not isinstance(manifest_tag, str) or TAG_RE.fullmatch(manifest_tag) is None:
        errors.append("provenance tag contains unsupported characters")
    if tag is not None and manifest_tag != tag:
        errors.append(f"provenance tag {manifest_tag!r} does not match {tag!r}")
    try:
        _parse_timestamp(manifest.get("created_at"))
    except ValueError as exc:
        errors.append(str(exc))
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        return [*errors, "provenance artifacts must be a list"]
    valid_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict) or not isinstance(record.get("name"), str):
            errors.append(f"provenance artifact record {index} has no valid name")
            continue
        name = record["name"]
        record_path = record.get("path")
        if not isinstance(record_path, str):
            errors.append(f"provenance artifact {name!r} has no valid path")
        else:
            pure_path = PurePosixPath(record_path)
            if pure_path.is_absolute() or ".." in pure_path.parts or pure_path.name != name:
                errors.append(f"provenance artifact {name!r} has unsafe path {record_path!r}")
        size = record.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f"provenance artifact {name!r} has invalid size {size!r}")
        digest = record.get("sha256")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            errors.append(f"provenance artifact {name!r} has invalid SHA-256")
        valid_records.append(record)
    record_names = [record["name"] for record in valid_records]
    duplicate_records = sorted({name for name in record_names if record_names.count(name) > 1})
    if duplicate_records:
        errors.append(f"provenance contains duplicate artifact records: {duplicate_records}")
    artifact_names = [path.name for path in artifacts]
    duplicate_artifacts = sorted(
        {name for name in artifact_names if artifact_names.count(name) > 1}
    )
    if duplicate_artifacts:
        errors.append(f"supplied artifacts have duplicate basenames: {duplicate_artifacts}")

    record_set = set(record_names)
    artifact_set = set(artifact_names)
    for name in sorted(record_set - artifact_set):
        errors.append(f"provenance artifact {name!r} was not supplied for verification")
    for name in sorted(artifact_set - record_set):
        errors.append(f"artifact {name!r} is absent from provenance")

    by_name = {record["name"]: record for record in valid_records}
    for path in artifacts:
        record = by_name.get(path.name)
        if record is None:
            continue
        if not path.is_file():
            errors.append(f"artifact {path} does not exist")
            continue
        actual_size = path.stat().st_size
        if record.get("size") != actual_size:
            errors.append(
                f"artifact {path.name!r} size is {actual_size}, expected {record.get('size')!r}"
            )
        actual_digest = _digest(path)
        if record.get("sha256") != actual_digest:
            errors.append(f"artifact {path.name!r} SHA-256 does not match provenance")
    return errors


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provenance manifest must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("artifact_root", type=Path)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--source-sha", required=True)
    create.add_argument("--repository", required=True)
    create.add_argument("--workflow-run-id", required=True)
    create.add_argument("--tag", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("artifacts", nargs="+", type=Path)
    verify.add_argument("--source-sha")
    verify.add_argument("--repository")
    verify.add_argument("--workflow-run-id")
    verify.add_argument("--tag")
    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            payload = create_manifest(
                args.artifact_root,
                source_sha=args.source_sha,
                repository=args.repository,
                workflow_run_id=args.workflow_run_id,
                tag=args.tag,
            )
            args.output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(
                f"release provenance created: {args.output} ({len(payload['artifacts'])} artifacts)"
            )
            return 0
        payload = _load_manifest(args.manifest)
        errors = verify_manifest(
            payload,
            args.artifacts,
            source_sha=args.source_sha,
            repository=args.repository,
            workflow_run_id=args.workflow_run_id,
            tag=args.tag,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"release provenance failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("release provenance verification failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"release provenance verified: {len(args.artifacts)} artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
