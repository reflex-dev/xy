# Coverage ratchet

`python_coverage` is a hard pull-request job and a dependency of the stable
`Required CI` result. It installs the package-owned, locked
`python/reflex-xy[dev]` environment, measures the full root suite plus the
zero-skip Reflex adapter suite with branch tracing, and retains raw coverage,
Coverage.py JSON/XML, and `coverage/python/ratchet.json` for 30 days.

The reviewed policy is `coverage-policy.json`; `scripts/coverage_ratchet.py`
owns its schema and enforcement. At the policy's 2026-07-21 review point, the
measured package values and blocking floors were:

| Package | Measured line | Floor | Measured branch | Floor |
|---|---:|---:|---:|---:|
| Core `python/xy` excluding pyplot | 88.27% | 87.5% | 79.09% | 78.5% |
| `python/xy/pyplot` | 81.07% | 80.5% | 68.98% | 68.0% |
| `python/reflex-xy/reflex_xy` | 92.22% | 91.5% | 81.41% | 80.5% |

Critical module floors separately protect `channel.py`, `widget.py`, pyplot's
`_axes.py`, and the Reflex component boundary. Every shipped Python file must
appear in the branch-aware report and map to exactly one package group, so a
new unmeasured module fails rather than diluting or evading the aggregate.

Changed-line policy is 90%. The verifier compares the immutable pull-request
base/head SHAs with a zero-context Git diff, intersects added production lines
with Coverage.py's executable-line inventory, and reports every covered and
missing line. A production file absent from coverage fails closed. A change
with no executable Python lines is recorded as not requiring diff coverage;
package and module floors still run.

Exclusions are exact patterns with substantive rationales in the policy. They
cover generated JavaScript, tests, automation, benchmarks, and examples—not
shipped Python modules. Lowering a floor or adding an exclusion is a policy
change requiring normal review; generated evidence never rewrites the policy.

JavaScript is measured separately by the hard `javascript_semantics` job,
which retains raw V8/text/JUnit evidence and enforces line, branch, and function
floors. Rust has no coverage ratchet yet and must first gain a retained,
toolchain-pinned coverage report before any Rust percentage can become policy;
the Python ratchet deliberately cannot manufacture or imply one.

To re-check an existing report locally:

```bash
make check-coverage COVERAGE_JSON=coverage/python/coverage.json \
  COVERAGE_BASE=origin/main COVERAGE_HEAD=HEAD
```
