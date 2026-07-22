#!/usr/bin/env python3
"""Check the testing catalog in spec/testing for internal and repository truth.

The catalog claims what the repository tests and what it does not. Those claims
decay silently when a script is renamed, a Make target is retired, or a workflow
job disappears, so this checker validates the mechanical parts:

- status values come from the documented vocabulary;
- gap IDs are unique, sequentially numbered, and defined exactly once;
- every referenced gap ID resolves, and every defined gap is reachable from the
  current inventory;
- relative Markdown links resolve, including heading anchors; and
- referenced `make` targets, repository paths, and workflow jobs exist.

It is deliberately mechanical. Whether a row's status is *honest* stays a review
question; this only rejects claims that are checkably false.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTING_DIR = ROOT / "spec" / "testing"
MAKEFILE = ROOT / "Makefile"
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# Documents that may link into the testing catalog and reference its gap IDs.
EXTERNAL_REFERENCES = (
    ROOT / "spec" / "README.md",
    ROOT / "spec" / "process" / "production-readiness.md",
)

STATUS_VOCABULARY = frozenset(
    {
        "IMPLEMENTED",
        "PARTIALLY IMPLEMENTED",
        "NOT IMPLEMENTED",
        "OUT OF SCOPE",
    }
)

GAP_ID_RE = re.compile(r"TST-NI-(\d{3})")
GAP_HEADING_RE = re.compile(r"^### (TST-NI-\d{3}) — (.+)$")
# Backticked ALL-CAPS spans in this tree are status claims; anything else in
# caps (an acronym such as `JSON`) is not, so require at least two words or a
# known single-word status.
STATUS_CLAIM_RE = re.compile(r"`([A-Z][A-Z ]{4,})`")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
MAKE_TARGET_RE = re.compile(r"`(make [a-z0-9-]+)")
REPO_PATH_RE = re.compile(r"`((?:scripts|benchmarks|tests|python|js|src|docs)/[^`\s]+)`")
WORKFLOW_FILE_RE = re.compile(r"`(_?[a-z0-9-]+\.yml)`")


class Findings:
    """Collects failures so one run reports every problem, not just the first."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, path: Path, message: str) -> None:
        self.errors.append(f"{path.relative_to(ROOT)}: {message}")

    def ok(self) -> bool:
        return not self.errors


def _slug(heading: str) -> str:
    """Reproduce GitHub's heading-anchor slug for a Markdown heading's text."""
    text = heading.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    # GitHub replaces each space individually; a removed em dash leaves two.
    return re.sub(r"\s", "-", text.strip())


def _headings(text: str) -> set[str]:
    anchors: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#"):
            anchors.add(_slug(line.lstrip("#")))
    return anchors


def _strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _make_targets() -> set[str]:
    if not MAKEFILE.is_file():
        return set()
    return {
        match.group(1)
        for match in re.finditer(r"^([a-z][a-z0-9-]*):", MAKEFILE.read_text(encoding="utf-8"), re.M)
    }


def _workflow_jobs(path: Path) -> set[str]:
    """Read top-level job names without a YAML dependency (stdlib-only tool)."""
    jobs: set[str] = set()
    in_jobs = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if re.match(r"^jobs:\s*$", line):
            in_jobs = True
            continue
        if in_jobs:
            if line and not line[0].isspace():
                in_jobs = False
                continue
            match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if match:
                jobs.add(match.group(1))
    return jobs


def check_status_vocabulary(path: Path, text: str, findings: Findings) -> None:
    for match in STATUS_CLAIM_RE.finditer(text):
        claim = match.group(1).strip()
        # Judge any span that reads as a status claim — including near misses
        # such as `MOSTLY IMPLEMENTED` — while ignoring caps acronyms.
        if not any(word in claim for word in ("IMPLEMENTED", "SCOPE")):
            continue
        if claim not in STATUS_VOCABULARY:
            findings.add(path, f"unknown status value `{claim}`")


def check_links(path: Path, text: str, findings: Findings) -> None:
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        anchor = ""
        if "#" in target:
            target, _, anchor = target.partition("#")
        if not target:
            resolved = path
        else:
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                findings.add(path, f"broken link target {target}")
                continue
        if (
            anchor
            and resolved.suffix == ".md"
            and anchor not in _headings(resolved.read_text(encoding="utf-8"))
        ):
            findings.add(path, f"broken link anchor #{anchor} in {target or path.name}")


def check_repository_references(path: Path, text: str, findings: Findings) -> None:
    targets = _make_targets()
    for match in MAKE_TARGET_RE.finditer(text):
        target = match.group(1).removeprefix("make ")
        if target not in targets:
            findings.add(path, f"`make {target}` is not a Makefile target")

    for match in REPO_PATH_RE.finditer(text):
        candidate = match.group(1)
        # Trailing punctuation and pytest node ids are not part of the path.
        candidate = candidate.rstrip(".,;").split("::", 1)[0]
        # `python/reflex-xy[dev]` is an install target, not a path on disk.
        candidate = re.sub(r"\[[^\]]*\]$", "", candidate)
        if "*" in candidate:
            continue
        if not (ROOT / candidate).exists():
            findings.add(path, f"referenced path {candidate} does not exist")

    for match in WORKFLOW_FILE_RE.finditer(text):
        workflow = match.group(1)
        if not (WORKFLOW_DIR / workflow).is_file():
            findings.add(path, f"referenced workflow {workflow} does not exist")


def check_workflow_registry(path: Path, text: str, findings: Findings) -> None:
    """Validate the `| workflow.yml | job, job | role |` rows in current.md."""
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        workflow_match = re.fullmatch(r"`(_?[a-z0-9-]+\.yml)`", cells[0])
        if not workflow_match:
            continue
        workflow_path = WORKFLOW_DIR / workflow_match.group(1)
        if not workflow_path.is_file():
            continue  # Reported by check_repository_references.
        actual = _workflow_jobs(workflow_path)
        claimed = {match.strip("`") for match in re.findall(r"`([A-Za-z0-9_-]+)`", cells[1])}
        for job in sorted(claimed - actual):
            findings.add(path, f"{workflow_match.group(1)} has no job `{job}`")


def check_gap_register(findings: Findings) -> None:
    gaps_path = TESTING_DIR / "gaps.md"
    if not gaps_path.is_file():
        findings.add(TESTING_DIR, "gaps.md is missing")
        return
    gaps_text = gaps_path.read_text(encoding="utf-8")

    defined: list[str] = []
    for line in gaps_text.splitlines():
        match = GAP_HEADING_RE.match(line)
        if match:
            defined.append(match.group(1))

    seen: set[str] = set()
    for gap_id in defined:
        if gap_id in seen:
            findings.add(gaps_path, f"duplicate definition of {gap_id}")
        seen.add(gap_id)

    for index, gap_id in enumerate(defined, 1):
        expected = f"TST-NI-{index:03d}"
        if gap_id != expected:
            findings.add(
                gaps_path, f"gap IDs are not sequential: expected {expected}, got {gap_id}"
            )
            break

    # Every entry must state its status; P0 entries must also name an owner so
    # release-blocking work cannot sit in the register anonymously.
    p0_ids = _p0_gap_ids(gaps_text)
    for gap_id, body in _gap_bodies(gaps_text).items():
        if "- Status: `NOT IMPLEMENTED`" not in body:
            findings.add(gaps_path, f"{gap_id} does not declare `NOT IMPLEMENTED` status")
        if "- Implemented when:" not in body:
            findings.add(gaps_path, f"{gap_id} has no completion criteria")
        if gap_id in p0_ids and "- Owner:" not in body:
            findings.add(gaps_path, f"{gap_id} is P0 and must name an owner")

    referenced: dict[str, set[Path]] = {}
    for path in sorted(TESTING_DIR.rglob("*.md")) + list(EXTERNAL_REFERENCES):
        if path == gaps_path or not path.is_file():
            continue
        for match in GAP_ID_RE.finditer(path.read_text(encoding="utf-8")):
            referenced.setdefault(match.group(0), set()).add(path)

    for gap_id, sources in sorted(referenced.items()):
        if gap_id not in seen:
            for source in sorted(sources):
                findings.add(source, f"references undefined gap {gap_id}")

    current_path = TESTING_DIR / "current.md"
    current_refs = {
        match.group(0)
        for match in GAP_ID_RE.finditer(current_path.read_text(encoding="utf-8"))
        if current_path.is_file()
    }
    for gap_id in sorted(seen - current_refs):
        findings.add(
            gaps_path,
            f"{gap_id} is unreachable from current.md; add the surface row that motivates it",
        )


def _p0_gap_ids(text: str) -> set[str]:
    """Gap IDs defined under the P0 section heading."""
    match = re.search(r"^## P0[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        return set()
    return {found.group(0) for found in GAP_ID_RE.finditer(match.group(1))}


def _gap_bodies(text: str) -> dict[str, str]:
    bodies: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        match = GAP_HEADING_RE.match(line)
        if match:
            if current:
                bodies[current] = "\n".join(lines)
            current = match.group(1)
            lines = []
        elif current:
            if line.startswith("## "):
                bodies[current] = "\n".join(lines)
                current = None
            else:
                lines.append(line)
    if current:
        bodies[current] = "\n".join(lines)
    return bodies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    if not TESTING_DIR.is_dir():
        print(f"error: {TESTING_DIR} is missing", file=sys.stderr)
        return 2

    findings = Findings()
    documents = sorted(TESTING_DIR.rglob("*.md"))
    for path in documents:
        text = _strip_code_blocks(path.read_text(encoding="utf-8"))
        check_status_vocabulary(path, text, findings)
        check_links(path, text, findings)
        check_repository_references(path, text, findings)
        check_workflow_registry(path, text, findings)

    for path in EXTERNAL_REFERENCES:
        if path.is_file():
            check_links(path, _strip_code_blocks(path.read_text(encoding="utf-8")), findings)

    check_gap_register(findings)

    if not findings.ok():
        print("testing specification check failed:", file=sys.stderr)
        for error in findings.errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    print(f"testing specification OK ({len(documents)} documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
