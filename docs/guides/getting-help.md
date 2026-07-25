---
title: Getting Help
description: Report XY bugs, request features, disclose vulnerabilities, and provide useful environment details.
---

# Getting Help

A useful starting point is a small reproducible case with the installed XY
version and the output environment. XY is early alpha and does not publish a
general response-time or resolution SLA, so an issue is a project report rather
than a promise of a fix or delivery date.

## Choose the right route

| Need | Route |
| --- | --- |
| Installation, blank chart, validation, or export failure | Check [Troubleshooting](/docs/xy/guides/troubleshooting/) first, then open an [XY issue](https://github.com/reflex-dev/xy/issues/new) with a reproduction |
| Incorrect or missing documentation | Open an [XY issue](https://github.com/reflex-dev/xy/issues/new) and link the exact docs URL or source page |
| Feature or chart-family request | Search [existing XY issues](https://github.com/reflex-dev/xy/issues), then open one that explains the user outcome and required data/output contract |
| Reproducible regression | Open an [XY issue](https://github.com/reflex-dev/xy/issues/new) with the last working and first failing versions |
| Suspected vulnerability | Use [GitHub private vulnerability reporting](https://github.com/reflex-dev/xy/security/advisories/new); do not open a public issue |

The issue tracker is the repository's public, XY-specific project channel. Do
not send secrets, credentials, private datasets, or embargoed vulnerability
details through a public issue.

## Capture the installed environment

Run this with the same interpreter that builds the failing chart:

~~~bash
python - <<'PY'
import platform
import sys

import xy

print("xy:", xy.__version__)
print("python:", sys.version.replace("\n", " "))
print("platform:", platform.platform())
print("machine:", platform.machine())

try:
    import xy.kernels as kernels

    print("backend:", kernels.BACKEND)
except Exception as error:
    print("backend import failed:", repr(error))
PY

python -m pip show xy
python -m pip check
~~~

Include whether XY came from PyPI, a Git commit, a local editable checkout, or
an internal mirror. For a Git install, include the full commit SHA. “Latest” is
not a version and can refer to different code by the time someone investigates.

## Build a minimal reproduction

Remove application code until the failure still occurs with a small chart:

~~~python
import xy

chart = xy.scatter_chart(
    xy.scatter([1, 2, 3], [3, 5, 4]),
    width=640,
    height=360,
)

chart.to_html("repro.html")
~~~

Then add back only the option or data shape that triggers the problem. Synthetic
data is preferable to redacted production data because it preserves dtype,
length, missing-value, and ordering behavior without exposing sensitive rows.

A useful report includes:

- Expected behavior and actual behavior.
- The complete exception and traceback as text.
- A runnable chart constructor and the smallest synthetic input that fails.
- Data length, dtype, null count, category count, and whether x is sorted when
  those details are relevant.
- Output mode: notebook widget, standalone HTML, native PNG, Chromium PNG, SVG,
  or a framework adapter.
- Notebook host and version, or browser name and version, for display issues.
- Explicit chart width and height for blank or layout-related failures.
- `chart.memory_report()` for ingest-copy or large-memory reports.

Attach a screenshot when the problem is visual, but keep the code and observed
values in the issue body; an image alone cannot be executed or searched.

## Report version and docs mismatches

The source documentation can describe work that has not reached the installed
wheel. Before reporting an unknown argument or missing method:

1. Print `xy.__version__` from the failing environment.
2. Check the [Changelog](/docs/xy/api-reference/changelog/) and the release or
   commit from which the docs were built.
3. Reproduce against the version you actually intend to deploy.
4. Include both the docs URL and the installed version in the issue.

Do not work around a mismatch by importing a private module. Pin a compatible
public release or, when deliberately evaluating unreleased work, pin the exact
Git commit and treat it as a source-based test environment.

## Security reports

The repository's [security policy](https://github.com/reflex-dev/xy/blob/main/SECURITY.md)
is authoritative for supported versions, scope, and response expectations.
Use its private reporting link for injection, unsafe exported HTML, native-core
memory safety, dependency, or other vulnerability concerns. A crash or bad
validation result with no security impact belongs in the public issue tracker;
when uncertain, start privately and let the maintainers triage it.

## Roadmap and support expectations

XY does not promise a public release cadence, feature-delivery date, or general
support response time. Open issues and pull requests show active work, not a
commitment that a feature will ship in a particular release. The
[Changelog](/docs/xy/api-reference/changelog/) is the record of released and
unreleased changes; [Limitations and alpha status](/docs/xy/api-reference/limitations-and-alpha-status/)
is the current contract boundary.

For a feature request, explain what decision or workflow is blocked, the data
and output scale involved, and what an acceptable minimal contract would be.
That gives maintainers more useful information than a request for parity with
an entire competing library.

Contributors who want to implement a confirmed change should follow the
[contributing guide](/docs/xy/api-reference/contributing/) and discuss
contract changes in an issue before investing in a large patch.
