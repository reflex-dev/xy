# Style-compatibility migration

The staged path from "native exports silently drop `class_names`" to "no
renderer drops a declaration without saying so" — with the release each step
ships in named now, so none of them can quietly become permanent. The
programmatic foundation is `chart.style_compatibility_report()`
(`spec/api/export.md` §9) and the `compatibility=` export option.

## The modes

| Mode | Behavior | Cost on the unstyled path |
| --- | --- | --- |
| `legacy` | Exactly today's behavior: browser-only declarations drop silently from native exports. | One string comparison; the preflight machinery is not even imported. |
| `warn` | Every export that would drop a declaration emits one `StyleCompatibilityWarning` naming each loss. Bytes are still produced. | Zero for charts with no `class_names`/`styles`/`custom_css` (constant-time early-out). |
| `strict` | An export that would drop a declaration raises `StyleCompatibilityError` **before emission**, carrying the full preflight report and the ways out. | Same early-out as `warn`. |
| `lossless` | **Reserved, rejected today.** Arrives with the preflight-routing phase, where `Engine.auto` may choose a different lossless route on report evidence. Accepting the name before the routing exists would make it a lie. | — |

State-gated chrome never trips `warn`/`strict` in a clean static export: a
file with no tooltip has dropped nothing by not styling one (the
applicable-slot contract, `spec/api/export.md` §9).

## The engine contract

Engine selection and compatibility are orthogonal, and **an explicit engine
is a hard constraint — no compatibility mode may re-route it**:

| Request | Behavior |
| --- | --- |
| `compatibility="strict"`, explicit engine | Stay on the pinned engine; fail before emission on every unsupported declaration. |
| `compatibility="warn"` or `"legacy"`, explicit engine | Stay on the pinned engine; warn, or preserve legacy behavior, respectively. |
| any mode, `engine=Engine.chromium` (or resolved browser) | The live client renders the full cascade; nothing can drop, so the mode has nothing to do. |
| any mode, `custom_css` with a pinned native engine | Today's `ValueError` fires unchanged — resolution errors precede and outrank mode logic. |
| future `"lossless"`, `engine=Engine.auto` | Native only when preflight proves lossless; otherwise Chromium where the format supports it; otherwise raise. |
| future `"lossless"`, pinned engine | Never overridden: raise "cannot satisfy lossless natively; supply a snapshot/stylesheet or unpin the engine." |

`Engine.auto`'s current rule — native for every format, Chromium only when
`custom_css` needs a real CSS engine — is unchanged until the lossless phase,
and changing it then requires prominent release notes (speed, determinism,
dependency, and security posture all shift with an engine).

## The schedule

Pre-1.0, minor versions may break (README stability table); these are the
concrete releases each default flips in. Moving a step **later** needs only a
changelog note; moving one **earlier** is a breaking change and needs the
same notice a breaking release gets.

| Release | Change |
| --- | --- |
| 0.0.6 | `compatibility=` ships, default `legacy`. `warn`/`strict` are opt-in. Docs recommend `warn`. |
| 0.0.7 | Default flips to `warn`: silent drops end. `legacy` silences per call site. |
| 0.1.0 | Default flips to `strict` at the minor boundary. `warn` and `legacy` remain as opt-outs. |
| 0.2.0 | `legacy` is **removed** (per the Phase-0 rule that the removal release is named at announcement). `warn` remains indefinitely as the non-fatal mode. |
| lossless phase | `"lossless"` unreserved once preflight routing exists; `Engine.auto` may then take the lossless route by default, behind its own release note. |

## Out of scope here, tracked

- **Facet grids** keep `legacy` behavior regardless of the option until their
  per-panel preflight lands; `FacetGrid` export does not accept
  `compatibility=` yet rather than accepting and half-honoring it.
- The **resolved-style snapshot** (shared IR) makes the legend slot's
  declaration-level qualification property-exact; until then `strict` does
  not fail on legend box properties it cannot prove either way (§28: unsure
  is said out loud, not rounded to an error).
