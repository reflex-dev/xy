# Testing Specification

This directory is the canonical inventory of XY test evidence. It records what
the repository tests today, how that evidence is enforced, and what additional
coverage is still required. It complements the release bar in
[`production-readiness.md`](../process/production-readiness.md); it does not
silently strengthen or weaken that bar.

The testing specification has three responsibilities:

1. distinguish an existing test from an enforced gate;
2. connect every material product claim to executable evidence; and
3. label missing coverage honestly until it is implemented.

## Documents

- [`current.md`](current.md) inventories the current unit, integration,
  browser, benchmark, packaging, workflow, and release evidence.
- [`gaps.md`](gaps.md) is the stable, prioritized implementation register for
  coverage and enforcement. IDs remain in place after completion; incomplete
  entries are explicitly `NOT IMPLEMENTED`, while closed entries cite their
  evidence and are marked `IMPLEMENTED`.
- [`dependency-auditing.md`](dependency-auditing.md) defines the hard
  multi-ecosystem lock inventory, severity and exception policy, and retained
  vulnerability evidence.

## Status vocabulary

Use only these status values in this directory:

| Status | Meaning |
|---|---|
| `IMPLEMENTED` | The stated scope has executable evidence, runs in its documented environment, and enforces the documented outcome. |
| `PARTIALLY IMPLEMENTED` | Useful evidence exists, but the stated scope is incomplete, can skip unexpectedly, is not wired into the intended gate, or has an oracle that can accept a known failure. |
| `NOT IMPLEMENTED` | The desired protection does not yet exist as reliable automated evidence. A supporting script or dormant test does not change this status. |
| `OUT OF SCOPE` | The product does not claim the behavior. Use this only when the corresponding product specification also excludes it. |

Status applies to the exact capability in a row. For example, the focused
three-engine browser fixture is `IMPLEMENTED`, while a full cross-engine chart
catalog is `NOT IMPLEMENTED`. The stronger planned capability must not inherit
the status of the narrower existing one.

`PARTIALLY IMPLEMENTED` and `NOT IMPLEMENTED` do not provide release evidence.
Another specification may define either as an intended hard gate only when it
also says that current automation does not yet satisfy the contract and links
the corresponding gap.

## Promotion rule

A gap may move from `NOT IMPLEMENTED` only when the same change provides all of
the following:

- executable positive and negative evidence for the stated requirement;
- a stable local command or workflow job;
- the dependencies, platforms, browsers, and skip policy needed by that job;
- failure semantics that reject the defect the test is intended to catch;
- durable failure output, such as JUnit, structured JSON, screenshots, traces,
  or package artifacts where appropriate;
- an update to [`current.md`](current.md) and the relevant product spec; and
- required-check or release wiring when the item is meant to block a merge or
  release.

Merely adding a test file, smoke script, workflow step, or report row is not
enough if the intended environment can omit it or the verifier accepts failure.

## Evidence layers

XY uses complementary layers. A product claim should use the lowest-cost layer
that can independently observe the behavior, with a higher layer for seams that
cannot be proved in isolation.

| Layer | Purpose | Typical evidence |
|---|---|---|
| Static contract | API inventory, generated-file freshness, forbidden constructs, workflow shape | Ruff, public API checker, bundle check, workflow verifier |
| Unit | Pure validation, transforms, kernels, encoders, state transitions | Python, Rust, and planned JavaScript unit tests |
| Property and mutation | Broad input domains, rollback, malformed bytes, oracle strength | Hypothesis, deterministic randomized tests, planned mutation tests |
| Integration | Python/native, Python/JavaScript, host adapters, artifact install | ABI smoke, golden frames, adapter tests, wheel/sdist probes |
| Browser | Pixels, DOM semantics, interaction, lifecycle, accessibility | Chromium smokes and Playwright conformance |
| End to end | Real host, socket, package, release, and deployment paths | FastAPI/Reflex app smokes, package installs, exact-SHA qualification |
| Measurement | Performance, memory, payload, dashboard pressure | Benchmark reports with separate integrity and timing policy |

Source-substring assertions are appropriate only for narrow static contracts,
such as forbidden parser sinks or generated bundle freshness. They are not a
substitute for runtime semantics, rendered output, or workflow dependency
behavior.

## Gate tiers

| Tier | Required outcome |
|---|---|
| PR required | Runs for every relevant pull request and contributes to the stable required aggregate. Unexpected failure, cancellation, or skip is blocking. |
| Release required | Qualifies the exact artifact SHA before publication or deployment. |
| Advisory | The job may remain non-blocking, but its inputs and report integrity must still be valid. Ordinary shared-runner timing belongs here. |
| Scheduled | Longer cross-platform, fuzz, sanitizer, visual, and soak evidence that is too costly for every pull request. |
| Local | Developer feedback that is useful but is not evidence that automation ran. |

The target tier and the current enforcement are separate facts. A row is not a
PR or release gate merely because a product spec says it should be one.

## Audits

Point-in-time reconciliations of this catalog against the repository live in
[`audits/`](audits/). They record observed numbers on a date and are expected to
go stale; this document and [`current.md`](current.md) hold the durable rules.

- [`audits/2026-07-21.md`](audits/2026-07-21.md) — the reconciliation this
  catalog was first written against, including the failed 50-chart dashboard row
  that a green verifier accepted.

## Maintenance rules

- Update this section in the same pull request as a material test, workflow,
  platform-support, release, or product-contract change.
- Run `make check-testing-spec` after editing this directory. It validates links
  and anchors, the status vocabulary, gap-ID uniqueness and reachability, and
  every referenced `make` target, repository path, and workflow job. The root
  test suite runs the same checker, so a renamed script or retired target fails
  a normal pull request rather than rotting here unnoticed.
- Prefer file, symbol, command, and workflow-job references over volatile line
  numbers or collected-test counts.
- A skip counts as evidence only when the job declares and enforces that skip as
  allowed. A missing required dependency or configured browser is a failure.
- A retry may handle a classified infrastructure failure; it must not turn a
  semantic assertion failure green.
- Benchmark schema validity, expected scenario availability, and deterministic
  correctness are integrity checks. Ordinary comparative timing may remain
  advisory.
- Keep good existing foundations while closing gaps. Do not replace malformed
  framing tests, API parity, native parity, focused cross-engine conformance,
  packaging verification, or visual-health smokes with a narrower new lane.
