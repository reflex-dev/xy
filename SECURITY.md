# Security Policy

## Supported versions

xy is pre-1.0; only the latest released version receives security
fixes.

## Reporting a vulnerability

Please **do not** open a public issue for security reports. Instead, use
[GitHub private vulnerability reporting](https://github.com/reflex-dev/xy/security/advisories/new)
on this repository. Reports are acknowledged within a week.

## Standalone HTML Safety And CSP

`Chart.to_html()` produces one portable file with the client, spec, and data
inlined. Its Content-Security-Policy blocks network fetches, but portable HTML
requires inline scripts. A strict nonce/hash deployment needs an application
wrapper that serves the JavaScript bundle separately. It escapes titles, axis
labels, trace names, legends, series names, and categories, and non-finite JSON
metadata is rejected.

## Scope notes for triage

- **Standalone HTML export** (`Figure.to_html` / `Chart.to_html`) is the most
  security-sensitive surface: user strings (titles, labels, legends, series
  names, categories) are escaped before entering inline JSON or `<title>`, the
  export ships a defensive `Content-Security-Policy` meta tag, and non-finite
  JSON metadata is rejected. Escaping regressions here are in scope and
  treated as high severity — see `tests/test_static_client_security.py` and
  `make check-security`.
- `Figure.to_png` launches local Chromium with the browser sandbox enabled by
  default; `sandbox=False` is an explicit caller opt-out for trusted HTML.
- The native core is a local in-process C-ABI library; it processes only data
  already in the caller's process and performs no I/O or network access.
- The audit trail lives in `docs/engineering/security-audit-2026-07-06.md`.
