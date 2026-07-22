#!/usr/bin/env python3
"""Check public docs for broad, unqualified performance claims.

This is intentionally a small guardrail, not a full natural-language judge. It
flags phrases that are easy to post publicly and hard to defend, while allowing
measured benchmark rows and policy text that names mode/data/backend context.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCS = (
    "pyproject.toml",
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "spec/api/api-examples.md",
    "spec/benchmarks/results.md",
    "spec/api/chart-roadmap.md",
    "spec/process/contributing.md",
    "spec/process/production-readiness.md",
    "examples/reflex/README.md",
    "examples/fastapi/README.md",
)

BROAD_SUPERLATIVE_RE = re.compile(
    r"\b("
    r"faster\s+charting\s+engine|"
    r"fastest(?:\s+charting\s+library)?|"
    r"best\s+(?:python\s+)?(?:charting|plotting|graphing|data)\s+(?:library|engine)|"
    r"best\s+(?:at|for)\s+rendering|"
    r"most\s+performant(?:\s+(?:python\s+)?(?:charting|plotting|graphing|data)\s+"
    r"(?:library|engine))?|"
    r"better\s+than\s+(?:all|every|any)|"
    r"faster\s+than\s+(?:all|every|any)|"
    r"faster\s+than\s+everything|"
    r"more\s+performant\s+than\s+(?:all|every|any|everything)|"
    r"blow\s+(?:them|it|everyone)\s+away"
    r")\b",
    re.IGNORECASE,
)
COMPARATIVE_RE = re.compile(
    r"\b(?:faster\s+than|beats?|outperforms?)\s+"
    r"(?:plotly|matplotlib|bokeh|altair|datashader|holoviews|hvplot|seaborn)\b",
    re.IGNORECASE,
)
LARGE_RENDER_RE = re.compile(
    r"\brenders?\s+(?:\d[\d,]*(?:\.\d+)?\s*)?(?:k|m|b|million|billion)?[- ]?points\b",
    re.IGNORECASE,
)
NUMERIC_PERFORMANCE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*x\s+(?:faster|slower|smaller|larger|less|more)\b",
    re.IGNORECASE,
)
# The project has lived under earlier names (charts-exp, personal forks).
# Public docs must point at the canonical repository — a stale URL here means
# security reports, clones, and badges land on the wrong repo.
STALE_REPO_RE = re.compile(r"github\.com/Alek99|app\.codspeed\.io/Alek99|charts-exp", re.IGNORECASE)

POLICY_WORDS = re.compile(
    r"\b(do not|don't|must|should|guardrail|policy|claim|goal|planned|target|"
    r"blurry|rather than|not\s+(?:a|the|safe|same|one)|without naming|"
    r"needs qualification)\b",
    re.IGNORECASE,
)
QUALIFIER_GROUPS = (
    re.compile(r"\b(?:\d[\d,]*(?:\.\d+)?\s*)?(?:k|m|b|million|billion|points|rows|n=)\b", re.I),
    re.compile(
        r"\b(?:direct|density|decimated|adaptive|sampled|screen-bounded|exact markers?)\b", re.I
    ),
    re.compile(
        r"\b(?:native|numpy|backend|browser|chromium|swiftshader|render target|"
        r"webgl|svg|png|to pixels)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:benchmark|measured|documented|ttfr|payload|memory|ms|mb|gb|artifact)\b", re.I
    ),
    re.compile(r"\b(?:chart type|data size|mode|row|table|spec/benchmarks/results\.md)\b", re.I),
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str
    text: str

    def format(self) -> str:
        rel = self.path.relative_to(ROOT) if self.path.is_relative_to(ROOT) else self.path
        return f"{rel}:{self.line}: {self.message}: {self.text.strip()}"


def _line_window(lines: list[str], index: int, radius: int = 2) -> str:
    start = max(0, index - radius)
    end = min(len(lines), index + radius + 1)
    return "\n".join(lines[start:end])


def _is_policy_or_negative_context(text: str) -> bool:
    return bool(POLICY_WORDS.search(text))


def _has_claim_qualifiers(text: str) -> bool:
    return sum(1 for pattern in QUALIFIER_GROUPS if pattern.search(text)) >= 3


def _findings_for_file(path: Path) -> list[Finding]:
    lines = path.read_text(encoding="utf-8").splitlines()
    findings: list[Finding] = []
    for index, line in enumerate(lines):
        window = _line_window(lines, index)
        if STALE_REPO_RE.search(line):
            # No policy-context exemption: a stale repo identity is always wrong.
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "stale repository identity; use github.com/reflex-dev/xy",
                    line,
                )
            )
        if BROAD_SUPERLATIVE_RE.search(line) and not _is_policy_or_negative_context(window):
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "broad superlative needs measured scope or policy framing",
                    line,
                )
            )
        if COMPARATIVE_RE.search(line) and not (
            _is_policy_or_negative_context(window) or _has_claim_qualifiers(window)
        ):
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "comparative performance claim needs chart/data/backend/render context",
                    line,
                )
            )
        if LARGE_RENDER_RE.search(line) and not (
            _is_policy_or_negative_context(window) or _has_claim_qualifiers(window)
        ):
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "large-point rendering claim needs mode context",
                    line,
                )
            )
        if NUMERIC_PERFORMANCE_RE.search(line):
            # Benchmark tables often carry the measurement context a few lines
            # above the rows; give this rule a wider view than sentence-level
            # comparative claims while still catching slogan-style multipliers.
            metric_window = _line_window(lines, index, radius=10)
            if not (
                _is_policy_or_negative_context(metric_window)
                or _has_claim_qualifiers(metric_window)
            ):
                findings.append(
                    Finding(
                        path,
                        index + 1,
                        "numeric performance multiplier needs measured benchmark context",
                        line,
                    )
                )
    return findings


def check_claims(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if not path.exists():
            findings.append(Finding(path, 0, "document does not exist", ""))
            continue
        findings.extend(_findings_for_file(path))
    return findings


def _default_paths() -> list[Path]:
    paths = [ROOT / item for item in DEFAULT_DOCS]
    public_docs = (
        path
        for path in sorted((ROOT / "docs").rglob("*.md"))
        if "app" not in path.relative_to(ROOT / "docs").parts
    )
    return list(dict.fromkeys((*paths, *public_docs)))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="docs to scan")
    args = parser.parse_args(argv)

    paths = args.paths or _default_paths()
    findings = check_claims([path if path.is_absolute() else ROOT / path for path in paths])
    if findings:
        print("performance claim guardrail failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.format()}", file=sys.stderr)
        return 1
    print(f"performance claim guardrail OK: {len(paths)} document(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
