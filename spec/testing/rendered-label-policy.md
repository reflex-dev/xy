# Rendered Label and Value-Format Policy

This is the normative contract for browser-visible axis and tooltip values.
Accepted formats must render as specified; unsupported or kind-mismatched
formats raise `ValueError` at a Python boundary and throw for a raw browser
spec. Silent fallback is not permitted.

## Numeric grammar

A numeric format has this shape:

```text
[currency][,].N[f[unit]][%]
```

- `currency` is one optional literal prefix from `$`, `€`, `£`, or `¥`.
- `,` enables grouping and locale decimal/group separators through the host's
  `Intl.NumberFormat`. Without it, fixed output uses an ASCII decimal point.
- `N` is an integer precision from 0 through 20.
- `f` is optional for an unadorned fixed value. A literal unit requires `f`;
  the unit may contain ASCII letters, digits, spaces, `/`, `_`, or `-`.
- `%` multiplies by 100 and appends `%`. It may follow the precision directly
  or an otherwise suffix-free `f`; a unit and percent cannot be combined.

Examples include `.2f`, `,.0f`, `$,.2f`, `.1%`, `.0f%`, `.4f s`,
`.3f GiB`, `,.0fK`, and `$,.0fK`. Currency symbols are literal prefixes,
not ISO-code or exchange-rate semantics. Width, alignment, signs, scientific
notation, arbitrary prefixes, and d3/Python format features outside this
grammar are rejected.

Linear and log axes use the same numeric grammar. On a log axis, a positive
subunit value that `.0f` would collapse to `0` retains the automatic nonzero
label. Category labels are the category strings themselves and reject
`format=`; explicit `tick_labels` remain the way to author replacements.

## Time grammar

Time formats contain at least one token from `%Y`, `%m`, `%d`, `%H`, `%M`,
`%S`, `%b`, or `%B`; other text is literal. Unknown or incomplete `%` tokens,
including `%y`, `%Z`, and `%%`, are rejected.

Every token is evaluated in UTC. `%b` and `%B` use English month names. Output
therefore remains identical across host locales and host time zones; local-time
formatting is intentionally not part of this API.

Tooltip formats use the numeric grammar for numeric fields and the time grammar
for `time_ms` fields. Applying a format to a string, a non-finite value, or the
wrong field kind throws instead of falling back.

## Automatic and colorbar labels

Absent `format=`, linear/log, category, and time axes keep their automatic tick
formatters. Automatic time labels are also UTC. Colorbars do not expose a
custom format: automatic ticks use the domain-derived fixed formatter, while
explicit ticks use the six-significant-digit general formatter. The colorbar
title is literal text.

## Executable oracle

`npm run test:labels` (or `make check-labels`) runs package-owned Vite,
TypeScript source, Playwright `1.61.1`, and Chromium with no optional imports or
skip path. It combines formatter units with real shipped-bundle DOM assertions
for numeric, grouping, currency, percent, UTC time, log, category, named-axis,
tooltip, and colorbar labels in:

- `en-US` / `America/Los_Angeles`; and
- `de-DE` / `Asia/Tokyo`.

Both time zones are non-UTC, and the test requires the UTC labels to match
exactly. Independent negative controls inject malformed raw axis and tooltip
formats and corrupt a captured DOM label to prove both runtime rejection and
oracle sensitivity. The hard `test` CI job uploads
`rendered-label-evidence.json` as `rendered-label-evidence` even on failure.

The executable sources are `js/tests/rendered_labels.test.mjs`,
`tests/test_rendered_label_formats.py`, `js/src/30_ticks.ts`, and
`python/xy/_validate.py`.
