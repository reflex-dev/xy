# Dependency Vulnerability Auditing

The repository has one hard vulnerability policy for every active committed
dependency environment. The `dependency_audit` CI job runs on every pull
request, is a dependency of `required_ci`, and cannot be made advisory without
failing the workflow contract tests.

## Audited environments

[`dependency-audit-policy.json`](dependency-audit-policy.json) is the
machine-readable inventory. [`scripts/dependency_audit.py`](../../scripts/dependency_audit.py)
requires this exact set and also discovers supported lockfile names so a newly
committed lock cannot remain unaudited silently.

| Subsystem | Lock | OSV-Scanner format |
|---|---|---|
| Root Python package and development environment | `uv.lock` | `uv.lock` |
| Documentation Python application | `docs/app/uv.lock` | `uv.lock` |
| Documentation generated frontend | `docs/app/reflex.lock/bun.lock` | `bun.lock` |
| Reflex adapter | `python/reflex-xy/uv.lock` | `uv.lock` |
| CI benchmark environment | `benchmarks/requirements-ci.lock` | `requirements.txt` |
| Native Rust core | `Cargo.lock` | `Cargo.lock` |
| Root browser tooling | `package-lock.json` | `package-lock.json` |

The sole inventory exclusion is
`benchmarks/launch_baselines/xy-0.1.0/macos-arm64-m5-pro/uv.lock`. It is an
immutable historical measurement fixture and is not installed or executed by a
current subsystem. Its exact path, owner, and reason are fixed in the policy;
adding another exclusion requires changing and reviewing the validator.

## Hard policy

CI downloads OSV-Scanner 2.4.0 from its versioned release URL and verifies the
reviewed Linux x86-64 SHA-256 before execution. The runner verifies the binary
again, validates its reported version, commit, and build timestamp, downloads
fresh offline advisory archives, and submits every lock explicitly. A scan is
invalid if any inventoried source is missing, repeated, unrequested, or yields
zero packages.

Every severity class is blocking: `CRITICAL`, `HIGH`, `MODERATE`, `LOW`, and
`UNKNOWN`. This deliberately makes a vulnerability without a published CVSS
score fail closed. The job succeeds only when every finding has been removed or
has one valid exact exception.

An exception has this shape:

```json
{
  "id": "GHSA-1234-5678-9abc",
  "package": {"ecosystem": "PyPI", "name": "example"},
  "environment": "root-python",
  "owner": "@reflex-dev/xy",
  "reason": "Why this exact affected path is temporarily acceptable.",
  "expires": "2026-08-20"
}
```

IDs, ecosystems, package names, and audited subsystem names match exactly;
wildcards are forbidden. Owners must be a GitHub user/team or email address,
reasons must be substantive, and expiration must be in the future and no more
than 180 days from validation. Expired, duplicate, malformed, and no-longer-used
exceptions fail the job.

## Retained evidence

The `dependency-audit` artifact is retained for 30 days and contains:

- `osv-results.json`, the scanner's full machine-readable findings;
- `dependency-audit.json`, the normalized policy outcome, package counts,
  exception decisions, scanner identity, and per-ecosystem database retrieval
  timestamp, latest archive-entry timestamp, entry count, size, and SHA-256;
- `scanner-version.txt`, the scanner, engine, commit, and build timestamp; and
- `scanner-output.txt`, the execution log.

The advisory database archives are used during the job but are not uploaded;
their recorded hashes and timestamps identify the exact snapshots used. This
gate detects vulnerabilities represented in the OSV databases. It does not
replace source code scanning, artifact provenance, or review of malicious or
compromised packages that have no advisory.

Run policy and lock-inventory validation locally with:

```console
python3 scripts/dependency_audit.py validate
```

The full scan additionally requires a reviewed OSV-Scanner binary and is the
command executed by the hard CI job.
