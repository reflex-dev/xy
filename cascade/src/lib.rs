//! Mount-free CSS cascade for xy (wire-protocol §8, migration doc "native
//! cascade"): Lightning CSS parses and normalizes author stylesheets; this
//! crate matches them against the synthetic chart DOM and cascades to
//! concrete per-node declarations — the values the ResolvedStyleSnapshot
//! carries and the native writers consume.
//!
//! Profile-scoped on purpose. The published profile is: style rules;
//! class / `[data-xy-slot=…]` attribute / universal / `:root` simple
//! selectors with descendant and child combinators; `@media
//! (prefers-color-scheme: …)`; custom properties with `var()` fallbacks;
//! `em`/`rem` lengths (resolved against the font-size cascade); the
//! inherited text properties. Everything else — other at-rules, pseudo
//! classes/elements, sibling combinators, percentage lengths — lands in the
//! reply's `unsupported` list with the reason, never in a guessed value
//! (§28). The Python side surfaces that list through the preflight.
//!
//! C ABI: JSON in, JSON out, one free function. The boundary stays this
//! narrow so the extension is loadable lazily and replaceable wholesale
//! (the plan's Stylo endgame swaps the resolver, not the contract).

mod resolve;

use std::panic::{catch_unwind, AssertUnwindSafe};

pub const CASCADE_ABI_VERSION: u32 = 1;

#[no_mangle]
pub extern "C" fn xy_cascade_abi_version() -> u32 {
    CASCADE_ABI_VERSION
}

/// Resolve `css` against the synthetic document `doc` (JSON; see
/// `resolve::Document`). Writes a malloc'd JSON reply to `out`/`out_len`;
/// returns 0 on success, 1 when the reply is `{"error": …}`, 2 on a caught
/// panic (reply is a static error JSON). The caller frees the reply with
/// `xy_cascade_free` in every case.
///
/// # Safety
/// `css_ptr`/`doc_ptr` must reference `css_len`/`doc_len` readable bytes;
/// `out`/`out_len` must be writable.
#[no_mangle]
pub unsafe extern "C" fn xy_cascade_resolve(
    css_ptr: *const u8,
    css_len: usize,
    doc_ptr: *const u8,
    doc_len: usize,
    out: *mut *mut u8,
    out_len: *mut usize,
) -> i32 {
    let css = std::slice::from_raw_parts(css_ptr, css_len);
    let doc = std::slice::from_raw_parts(doc_ptr, doc_len);
    let result = catch_unwind(AssertUnwindSafe(|| resolve::resolve_json(css, doc)));
    let (code, payload) = match result {
        Ok(Ok(json)) => (0, json),
        Ok(Err(message)) => (
            1,
            serde_json::to_string(&serde_json::json!({ "error": message }))
                .unwrap_or_else(|_| "{\"error\":\"unserializable error\"}".to_string()),
        ),
        Err(_) => (2, "{\"error\":\"panic in xy_cascade_resolve\"}".to_string()),
    };
    let boxed = payload.into_bytes().into_boxed_slice();
    let len = boxed.len();
    *out = Box::into_raw(boxed) as *mut u8;
    *out_len = len;
    code
}

/// Free a reply produced by `xy_cascade_resolve`.
///
/// # Safety
/// `ptr`/`len` must be exactly a pair returned through `out`/`out_len`.
#[no_mangle]
pub unsafe extern "C" fn xy_cascade_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() {
        drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)));
    }
}
