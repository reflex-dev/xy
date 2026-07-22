#!/usr/bin/env python3
"""Run a focused pytest lane and fail when any item is skipped.

Package-specific integration suites own their complete test environment. This
runner makes that contract explicit: an import failure, version incompatibility,
or any test skip cannot become a green host-integration lane.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

import pytest


@dataclass
class _NoSkips:
    skipped: list[str] = field(default_factory=list)

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.skipped:
            reason = getattr(report, "longreprtext", "skipped")
            self.skipped.append(f"{report.nodeid}: {reason}")

    def pytest_collectreport(self, report: Any) -> None:
        if report.skipped:
            reason = getattr(report, "longreprtext", "skipped during collection")
            self.skipped.append(f"{report.nodeid}: {reason}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: run_pytest_no_skips.py PYTEST_ARG ...", file=sys.stderr)
        return 2

    plugin = _NoSkips()
    code = int(pytest.main(args, plugins=[plugin]))
    if plugin.skipped:
        print("\nDedicated integration lane collected skips:", file=sys.stderr)
        for item in plugin.skipped:
            print(f"  - {item}", file=sys.stderr)
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
