"""The ESM export parser behind every built-bundle public-surface check."""

from __future__ import annotations

from scripts.js_exports import esm_exported_names, missing_esm_exports

# The real vite lib-mode tail, verbatim: aliased locals, no spaces, `default`
# exported from a renamed local.
MINIFIED = (
    "export{$ as ChartView,It as MARK_KINDS,p as decodeFrame,fn as default,"
    "X as markOf,un as render,dn as renderStandalone}"
)


def test_reads_through_minifier_aliases() -> None:
    assert esm_exported_names(MINIFIED) == {
        "ChartView",
        "MARK_KINDS",
        "decodeFrame",
        "default",
        "markOf",
        "render",
        "renderStandalone",
    }


def test_accepts_a_name_preserving_build() -> None:
    """A build that skips minification exports the names directly. The old
    substring markers (`"as decodeFrame" in text`) rejected exactly this."""
    assert esm_exported_names("export { decodeFrame, renderStandalone };") == {
        "decodeFrame",
        "renderStandalone",
    }


def test_substring_of_a_longer_export_is_not_a_match() -> None:
    """`render` must not be satisfied by `renderStandalone` — the flaw that made
    the old `"as render"` marker vacuous."""
    assert missing_esm_exports("export{d as renderStandalone}", ("render",)) == ["render"]


def test_reports_every_missing_name_sorted() -> None:
    assert missing_esm_exports(MINIFIED, ("decodeFrame", "gone", "alsoGone")) == [
        "alsoGone",
        "gone",
    ]
    assert missing_esm_exports(MINIFIED, ("render", "ChartView")) == []


def test_ignores_declaration_exports_and_trailing_commas() -> None:
    # Declaration-form exports are out of scope by design (the bundles never
    # emit them); a trailing comma must not fabricate an empty name.
    assert esm_exported_names("export function render() {}") == set()
    assert esm_exported_names("export{a as b,}") == {"b"}


def test_a_bundle_without_an_export_block_reports_everything_missing() -> None:
    assert missing_esm_exports("not the client", ("decodeFrame",)) == ["decodeFrame"]
