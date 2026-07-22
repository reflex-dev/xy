#!/usr/bin/env python3
"""Fail unless every hard CI dependency completed successfully.

GitHub's branch protection needs one stable check name, while the hard suite is
split across platform and package jobs.  The ``required_ci`` workflow job passes
its complete ``needs`` context here.  Keeping the policy in a tested script
avoids a shell expression that accidentally treats ``skipped`` or ``cancelled``
as success.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from typing import Any

HARD_JOBS = (
    "browser_conformance",
    "dependency_audit",
    "host_integration",
    "install_without_rust",
    "javascript_semantics",
    "matplotlib_reference",
    "native_parity",
    "python_coverage",
    "python_floor",
    "reflex_adapter",
    "rust_release",
    "sdist",
    "test",
    "wheels",
)


def evaluate_required_jobs(needs: Mapping[str, Any]) -> list[str]:
    """Return policy failures for a decoded GitHub ``needs`` context."""
    errors: list[str] = []
    expected = set(HARD_JOBS)
    actual = set(needs)
    for name in sorted(expected - actual):
        errors.append(f"hard job {name!r} is missing from the aggregate needs context")
    for name in sorted(actual - expected):
        errors.append(f"unexpected job {name!r} is wired into the hard aggregate")

    for name in HARD_JOBS:
        record = needs.get(name)
        if not isinstance(record, Mapping):
            if name in actual:
                errors.append(f"hard job {name!r} has a malformed result record")
            continue
        result = record.get("result")
        if result != "success":
            errors.append(f"hard job {name!r} concluded {result!r}, expected 'success'")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--needs-json",
        default=os.environ.get("NEEDS_JSON", ""),
        help="JSON needs context (defaults to $NEEDS_JSON)",
    )
    args = parser.parse_args(argv)
    if not args.needs_json:
        print("required CI aggregate: no needs JSON provided", file=sys.stderr)
        return 2
    try:
        needs = json.loads(args.needs_json)
    except json.JSONDecodeError as exc:
        print(f"required CI aggregate: invalid needs JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(needs, dict):
        print("required CI aggregate: needs JSON must be an object", file=sys.stderr)
        return 2

    errors = evaluate_required_jobs(needs)
    if errors:
        print("required CI aggregate failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("required CI aggregate OK: " + ", ".join(HARD_JOBS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
