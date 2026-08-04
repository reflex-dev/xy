//! The profile-scoped resolver: parse → match → cascade → concrete values.
//!
//! Correctness order inside one node's cascade, mirroring CSS: importance,
//! then specificity, then source order. No layers in the profile (an
//! `@layer` is reported). Custom properties resolve after the cascade with
//! inheritance; `em`/`rem` resolve after font-size does; the inherited text
//! properties flow parent-to-child last, so a child's own cascade always
//! outranks what it inherits.

use std::collections::BTreeMap;

use lightningcss::printer::PrinterOptions;
use lightningcss::properties::Property;
use lightningcss::rules::CssRule;
use lightningcss::selector::{Component, Selector};
use lightningcss::stylesheet::{ParserOptions, StyleSheet};
use lightningcss::traits::ToCss;
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
struct Document {
    env: Env,
    nodes: Vec<Node>,
}

#[derive(Deserialize)]
struct Env {
    #[serde(default = "default_scheme")]
    color_scheme: String,
    #[serde(default = "default_root_font")]
    root_font_size: f64,
}

fn default_scheme() -> String {
    "light".to_string()
}

fn default_root_font() -> f64 {
    16.0
}

#[derive(Deserialize)]
struct Node {
    slot: String,
    #[serde(default)]
    classes: Vec<String>,
    /// Index into `nodes`; parents precede children. `null` for the root.
    parent: Option<usize>,
}

#[derive(Serialize, Deserialize)]
struct Reply {
    nodes: Vec<NodeReply>,
    unsupported: Vec<String>,
}

#[derive(Serialize, Deserialize)]
struct NodeReply {
    slot: String,
    declarations: BTreeMap<String, String>,
}

/// Text properties that inherit down the synthetic tree — the CSS inherited
/// set restricted to the snapshot vocabulary the writers consume.
const INHERITED: &[&str] = &[
    "color",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "letter-spacing",
    "line-height",
    "text-align",
];

/// One matched declaration awaiting cascade.
struct Candidate {
    specificity: u32,
    order: u32,
    important: bool,
    value: String,
}

fn better(a: &Candidate, b: &Candidate) -> bool {
    (a.important, a.specificity, a.order) > (b.important, b.specificity, b.order)
}

/// A parsed profile selector: compounds right-to-left, combinator before
/// each non-subject compound (descendant or child only).
struct ProfileSelector {
    /// (compound, child_combinator_to_previous) — subject compound first.
    compounds: Vec<(Vec<Simple>, bool)>,
    specificity: u32,
}

enum Simple {
    Class(String),
    SlotAttr(String),
    Root,
    Universal,
}

pub fn resolve_json(css: &[u8], doc: &[u8]) -> Result<String, String> {
    let css = std::str::from_utf8(css).map_err(|e| format!("stylesheet is not UTF-8: {e}"))?;
    let doc: Document = serde_json::from_slice(doc).map_err(|e| format!("document JSON: {e}"))?;
    for (i, node) in doc.nodes.iter().enumerate() {
        if let Some(p) = node.parent {
            if p >= i {
                return Err(format!(
                    "node {i} ({}) references parent {p}; parents must precede children",
                    node.slot
                ));
            }
        }
    }

    let mut unsupported: Vec<String> = Vec::new();
    let sheet = StyleSheet::parse(css, ParserOptions::default())
        .map_err(|e| format!("stylesheet parse error: {e}"))?;

    // node -> property -> best candidate; custom properties cascade the
    // same way but resolve later.
    let n = doc.nodes.len();
    let mut winners: Vec<BTreeMap<String, Candidate>> = (0..n).map(|_| BTreeMap::new()).collect();
    let mut order: u32 = 0;
    collect_rules(
        &sheet.rules.0,
        &doc,
        &mut winners,
        &mut order,
        &mut unsupported,
        true,
    );

    // Custom-property chains: parent map extended by own winners.
    let mut custom: Vec<BTreeMap<String, String>> = Vec::with_capacity(n);
    for (i, node) in doc.nodes.iter().enumerate() {
        let mut map = node.parent.map(|p| custom[p].clone()).unwrap_or_default();
        for (name, cand) in winners[i].iter() {
            if name.starts_with("--") {
                map.insert(name.clone(), cand.value.trim().to_string());
            }
        }
        custom.push(map);
    }

    // Substitute var(), resolve font-size chain, then remaining lengths,
    // then inheritance.
    let mut resolved: Vec<BTreeMap<String, String>> = Vec::with_capacity(n);
    let mut font_sizes: Vec<f64> = Vec::with_capacity(n);
    for (i, node) in doc.nodes.iter().enumerate() {
        let parent_font = node
            .parent
            .map(|p| font_sizes[p])
            .unwrap_or(doc.env.root_font_size);
        let mut out: BTreeMap<String, String> = BTreeMap::new();
        // font-size first: em/rem lengths on this node resolve against it.
        let own_font = match winners[i].get("font-size") {
            Some(cand) => match substituted(&cand.value, &custom[i]) {
                Ok(value) => {
                    match resolve_length(&value, parent_font, doc.env.root_font_size, parent_font) {
                        Ok(px) => {
                            out.insert("font-size".into(), fmt_px(px));
                            px
                        }
                        Err(why) => {
                            unsupported.push(format!(
                                "{}: font-size: {} — {}",
                                node.slot, cand.value, why
                            ));
                            parent_font
                        }
                    }
                }
                Err(why) => {
                    unsupported.push(format!("{}: font-size — {}", node.slot, why));
                    parent_font
                }
            },
            None => parent_font,
        };
        font_sizes.push(own_font);

        for (name, cand) in winners[i].iter() {
            if name == "font-size" || name.starts_with("--") {
                continue;
            }
            let value = match substituted(&cand.value, &custom[i]) {
                Ok(v) => v,
                Err(why) => {
                    unsupported.push(format!("{}: {} — {}", node.slot, name, why));
                    continue;
                }
            };
            match concrete_value(&value, own_font, doc.env.root_font_size) {
                Ok(v) => {
                    out.insert(name.clone(), v);
                }
                Err(why) => {
                    unsupported.push(format!("{}: {}: {} — {}", node.slot, name, value, why));
                }
            }
        }
        resolved.push(out);
    }

    // Inheritance, top-down; a node's own cascade already sits in `resolved`.
    for i in 0..n {
        if let Some(p) = doc.nodes[i].parent {
            for &prop in INHERITED {
                if !resolved[i].contains_key(prop) {
                    if let Some(v) = resolved[p].get(prop).cloned() {
                        resolved[i].insert(prop.to_string(), v);
                    }
                }
            }
        }
    }

    let reply = Reply {
        nodes: doc
            .nodes
            .iter()
            .zip(resolved)
            .map(|(node, declarations)| NodeReply {
                slot: node.slot.clone(),
                declarations,
            })
            .collect(),
        unsupported,
    };
    serde_json::to_string(&reply).map_err(|e| format!("reply serialization: {e}"))
}

fn collect_rules(
    rules: &[CssRule],
    doc: &Document,
    winners: &mut [BTreeMap<String, Candidate>],
    order: &mut u32,
    unsupported: &mut Vec<String>,
    media_active: bool,
) {
    for rule in rules {
        match rule {
            CssRule::Style(style) => {
                let decls: Vec<(String, String, bool)> = declaration_texts(style, unsupported);
                for selector in &style.selectors.0 {
                    let profile = match profile_selector(selector) {
                        Ok(p) => p,
                        Err(why) => {
                            unsupported.push(format!(
                                "selector `{}` — {}",
                                selector_text(selector),
                                why
                            ));
                            continue;
                        }
                    };
                    if !media_active {
                        continue;
                    }
                    for (i, _node) in doc.nodes.iter().enumerate() {
                        if matches(&profile, doc, i) {
                            for (name, value, important) in &decls {
                                let cand = Candidate {
                                    specificity: profile.specificity,
                                    order: *order,
                                    important: *important,
                                    value: value.clone(),
                                };
                                match winners[i].get(name.as_str()) {
                                    Some(existing) if !better(&cand, existing) => {}
                                    _ => {
                                        winners[i].insert(name.clone(), cand);
                                    }
                                }
                            }
                        }
                    }
                }
                *order += 1;
            }
            CssRule::Media(media) => {
                let query = media
                    .query
                    .to_css_string(PrinterOptions::default())
                    .unwrap_or_default();
                match scheme_match(&query, &doc.env.color_scheme) {
                    Some(active) => collect_rules(
                        &media.rules.0,
                        doc,
                        winners,
                        order,
                        unsupported,
                        media_active && active,
                    ),
                    None => unsupported.push(format!(
                        "@media {query} — only (prefers-color-scheme: …) is in the profile"
                    )),
                }
            }
            other => {
                let text = other
                    .to_css_string(PrinterOptions::default())
                    .unwrap_or_else(|_| "<unprintable rule>".into());
                let head: String = text.chars().take(60).collect();
                unsupported.push(format!("rule `{head}` — outside the style/media profile"));
            }
        }
    }
}

fn declaration_texts(
    style: &lightningcss::rules::style::StyleRule,
    unsupported: &mut Vec<String>,
) -> Vec<(String, String, bool)> {
    let mut out = Vec::new();
    let mut push = |prop: &Property, important: bool, unsupported: &mut Vec<String>| {
        let name = prop.property_id().name().to_string();
        match prop.value_to_css_string(PrinterOptions::default()) {
            Ok(value) => out.push((name, value, important)),
            Err(e) => unsupported.push(format!("declaration {name} — unserializable: {e}")),
        }
    };
    for prop in &style.declarations.declarations {
        push(prop, false, unsupported);
    }
    for prop in &style.declarations.important_declarations {
        push(prop, true, unsupported);
    }
    out
}

fn selector_text(selector: &Selector) -> String {
    selector
        .to_css_string(PrinterOptions::default())
        .unwrap_or_else(|_| "<unprintable>".into())
}

/// Lower a parsed selector into the profile, or say exactly why not.
fn profile_selector(selector: &Selector) -> Result<ProfileSelector, String> {
    use lightningcss::selector::Combinator;

    let mut compounds: Vec<(Vec<Simple>, bool)> = Vec::new();
    let mut current: Vec<Simple> = Vec::new();
    let mut child_next = false;
    let mut iter = selector.iter();
    loop {
        for component in &mut iter {
            match component {
                Component::Class(name) => current.push(Simple::Class(name.to_string())),
                Component::AttributeInNoNamespace {
                    local_name,
                    operator,
                    value,
                    ..
                } => {
                    if local_name.as_ref() != "data-xy-slot" {
                        return Err(format!(
                            "attribute selector [{local_name}] — only [data-xy-slot=…] is in the profile"
                        ));
                    }
                    if !matches!(
                        operator,
                        parcel_selectors::attr::AttrSelectorOperator::Equal
                    ) {
                        return Err("only [data-xy-slot=\"…\"] equality is in the profile".into());
                    }
                    current.push(Simple::SlotAttr(value.to_string()));
                }
                Component::ExplicitUniversalType => current.push(Simple::Universal),
                Component::Root => current.push(Simple::Root),
                other => {
                    return Err(format!(
                        "component {:?} — outside the class/slot/universal/:root profile",
                        component_kind(other)
                    ));
                }
            }
        }
        compounds.push((std::mem::take(&mut current), child_next));
        match iter.next_sequence() {
            Some(Combinator::Descendant) => child_next = false,
            Some(Combinator::Child) => child_next = true,
            Some(other) => {
                return Err(format!(
                    "combinator {other:?} — only descendant and child are in the profile"
                ))
            }
            None => break,
        }
    }
    Ok(ProfileSelector {
        compounds,
        specificity: selector.specificity(),
    })
}

fn component_kind(component: &Component) -> &'static str {
    match component {
        Component::ID(..) => "#id",
        Component::LocalName(..) => "type selector",
        Component::NonTSPseudoClass(..) => "pseudo-class",
        Component::PseudoElement(..) => "pseudo-element",
        Component::Negation(..) => ":not()",
        Component::Is(..) => ":is()",
        Component::Where(..) => ":where()",
        _ => "unsupported selector component",
    }
}

fn compound_matches(compound: &[Simple], doc: &Document, index: usize) -> bool {
    let node = &doc.nodes[index];
    compound.iter().all(|simple| match simple {
        Simple::Class(name) => node.classes.iter().any(|c| c == name),
        Simple::SlotAttr(slot) => node.slot == *slot,
        Simple::Root => node.parent.is_none(),
        Simple::Universal => true,
    })
}

fn matches(profile: &ProfileSelector, doc: &Document, index: usize) -> bool {
    // Subject compound first, then walk ancestors per combinator.
    let mut compounds = profile.compounds.iter();
    let Some((subject, _)) = compounds.next() else {
        return false;
    };
    if !compound_matches(subject, doc, index) {
        return false;
    }
    let mut position = index;
    for (compound, child) in compounds {
        if *child {
            match doc.nodes[position].parent {
                Some(p) if compound_matches(compound, doc, p) => position = p,
                _ => return false,
            }
        } else {
            let mut cursor = doc.nodes[position].parent;
            loop {
                match cursor {
                    Some(p) => {
                        if compound_matches(compound, doc, p) {
                            position = p;
                            break;
                        }
                        cursor = doc.nodes[p].parent;
                    }
                    None => return false,
                }
            }
        }
    }
    true
}

/// `(prefers-color-scheme: X)` → Some(X == env); anything else → None.
fn scheme_match(query: &str, scheme: &str) -> Option<bool> {
    let q: String = query
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect::<String>()
        .to_ascii_lowercase();
    match q.as_str() {
        "(prefers-color-scheme:dark)" => Some(scheme == "dark"),
        "(prefers-color-scheme:light)" => Some(scheme == "light"),
        _ => None,
    }
}

/// Substitute var() with the node's custom-property chain, fallbacks
/// honored, to a fixpoint with a depth cap.
fn substituted(value: &str, custom: &BTreeMap<String, String>) -> Result<String, String> {
    let mut text = value.to_string();
    for _ in 0..8 {
        let Some(at) = text.find("var(") else {
            return Ok(text);
        };
        let body_start = at + 4;
        let mut depth = 1usize;
        let mut end = None;
        for (offset, ch) in text[body_start..].char_indices() {
            match ch {
                '(' => depth += 1,
                ')' => {
                    depth -= 1;
                    if depth == 0 {
                        end = Some(body_start + offset);
                        break;
                    }
                }
                _ => {}
            }
        }
        let end = end.ok_or_else(|| "unbalanced var(".to_string())?;
        let body = &text[body_start..end];
        let (name, fallback) = match body.find(',') {
            Some(comma) => (body[..comma].trim(), Some(body[comma + 1..].trim())),
            None => (body.trim(), None),
        };
        let replacement = match custom.get(name) {
            Some(v) => v.clone(),
            None => fallback
                .map(str::to_string)
                .ok_or_else(|| format!("var({name}) has no value and no fallback"))?,
        };
        text.replace_range(at..=end, &replacement);
    }
    Err("var() nesting exceeded the resolver's depth cap".into())
}

fn fmt_px(px: f64) -> String {
    if (px - px.round()).abs() < 1e-9 {
        format!("{}px", px.round() as i64)
    } else {
        format!("{px}px")
    }
}

/// Resolve one bare length. `own_font` is the em base (parent font for the
/// font-size property itself, own font for everything else).
fn resolve_length(
    value: &str,
    em_base: f64,
    rem_base: f64,
    _parent_font: f64,
) -> Result<f64, String> {
    let v = value.trim();
    if let Some(number) = v.strip_suffix("px") {
        return number
            .trim()
            .parse::<f64>()
            .map_err(|_| format!("unparseable px length `{v}`"));
    }
    if let Some(number) = v.strip_suffix("rem") {
        return number
            .trim()
            .parse::<f64>()
            .map(|n| n * rem_base)
            .map_err(|_| format!("unparseable rem length `{v}`"));
    }
    if let Some(number) = v.strip_suffix("em") {
        return number
            .trim()
            .parse::<f64>()
            .map(|n| n * em_base)
            .map_err(|_| format!("unparseable em length `{v}`"));
    }
    if let Ok(number) = v.parse::<f64>() {
        return Ok(number);
    }
    Err("not a px/em/rem length".into())
}

/// Make one declaration value concrete: resolve em/rem tokens against the
/// font-size cascade; refuse percentages outside color functions and
/// anything still cascade-dependent. Values with no length tokens pass
/// through as Lightning CSS normalized them.
fn concrete_value(value: &str, own_font: f64, rem_base: f64) -> Result<String, String> {
    let lowered = value.to_ascii_lowercase();
    if lowered.contains("calc(") || lowered.contains("env(") || lowered.contains("attr(") {
        return Err("still depends on a cascade/environment the writers do not have".into());
    }
    if lowered == "inherit" || lowered == "initial" || lowered == "unset" || lowered == "revert" {
        return Err("cascade keyword".into());
    }
    // Token-wise em/rem resolution; % outside color functions is refused.
    let masked = mask_color_functions(&lowered);
    if masked.contains('%') {
        return Err("percentage length — resolved lengths are px (percentages are accepted only as rgb()/hsl() color components)".into());
    }
    let mut out = String::with_capacity(value.len());
    let mut token = String::new();
    let flush = |token: &mut String, out: &mut String| -> Result<(), String> {
        if token.is_empty() {
            return Ok(());
        }
        let t = std::mem::take(token);
        let lower = t.to_ascii_lowercase();
        if lower.ends_with("em") && lower[..lower.len() - 2].parse::<f64>().is_ok()
            || lower.ends_with("rem") && lower[..lower.len() - 3].parse::<f64>().is_ok()
        {
            let px = resolve_length(&lower, own_font, rem_base, own_font)?;
            out.push_str(&fmt_px(px));
        } else {
            out.push_str(&t);
        }
        Ok(())
    };
    for ch in value.chars() {
        if ch.is_whitespace() || ch == ',' || ch == '(' || ch == ')' {
            flush(&mut token, &mut out)?;
            out.push(ch);
        } else {
            token.push(ch);
        }
    }
    flush(&mut token, &mut out)?;
    Ok(out)
}

/// Blank out rgb()/rgba()/hsl()/hsla() bodies so their % components do not
/// trip the percentage refusal — the same exemption the Python schema makes.
fn mask_color_functions(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let bytes = text.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let rest = &text[i..];
        let head = ["rgba(", "rgb(", "hsla(", "hsl("]
            .iter()
            .find(|h| rest.starts_with(**h));
        if let Some(h) = head {
            let start = i + h.len();
            if let Some(close) = text[start..].find(')') {
                out.push_str(h);
                out.push(')');
                i = start + close + 1;
                continue;
            }
        }
        out.push(text[i..].chars().next().unwrap());
        i += text[i..].chars().next().unwrap().len_utf8();
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn doc() -> String {
        serde_json::json!({
            "env": {"color_scheme": "dark", "root_font_size": 16.0},
            "nodes": [
                {"slot": "root", "classes": ["dark"], "parent": null},
                {"slot": "chrome", "classes": [], "parent": 0},
                {"slot": "tick_label", "classes": ["smoke-tick"], "parent": 1},
                {"slot": "legend", "classes": [], "parent": 1},
            ]
        })
        .to_string()
    }

    fn run(css: &str) -> Reply {
        let json = resolve_json(css.as_bytes(), doc().as_bytes()).unwrap();
        serde_json::from_str(&json).unwrap()
    }

    fn decls<'r>(reply: &'r Reply, slot: &str) -> &'r BTreeMap<String, String> {
        &reply
            .nodes
            .iter()
            .find(|n| n.slot == slot)
            .unwrap()
            .declarations
    }

    #[test]
    fn class_and_slot_selectors_cascade_by_specificity_and_order() {
        let reply = run(".smoke-tick { color: rgb(7, 89, 133); }\n\
             [data-xy-slot=\"tick_label\"] { color: red; font-weight: 600; }\n\
             .dark .smoke-tick { color: rgb(1, 2, 3); }");
        let d = decls(&reply, "tick_label");
        // Two class selectors (0,2,0) beat one attribute (0,1,0); later of
        // equal specificity wins. Lightning CSS normalizes color spellings
        // (rgb -> #hex); the differential smoke compares colors parsed, not
        // as strings, for exactly this reason.
        assert_eq!(d["color"], "#010203");
        assert_eq!(d["font-weight"], "600");
    }

    #[test]
    fn important_outranks_specificity() {
        let reply = run("[data-xy-slot=\"tick_label\"] { color: red !important; }\n\
             .dark .smoke-tick { color: blue; }");
        assert_eq!(decls(&reply, "tick_label")["color"], "red");
    }

    #[test]
    fn var_chain_inherits_and_falls_back() {
        let reply = run(":root { --fg: rgb(9, 9, 9); }\n\
             .smoke-tick { color: var(--fg); background: var(--missing, rgb(4, 5, 6)); }");
        let d = decls(&reply, "tick_label");
        assert_eq!(d["color"], "#090909");
        assert_eq!(d["background"], "#040506"); // fallbacks normalize like any color
    }

    #[test]
    fn em_resolves_against_the_font_size_cascade() {
        let reply = run(":root { font-size: 20px; }\n\
             [data-xy-slot=\"tick_label\"] { font-size: 0.5em; letter-spacing: 0.1em; }");
        let d = decls(&reply, "tick_label");
        // font-size em uses the PARENT size (root 20px -> 10px); other
        // lengths use the node's OWN resolved size (10px -> 1px).
        assert_eq!(d["font-size"], "10px");
        assert_eq!(d["letter-spacing"], "1px");
    }

    #[test]
    fn media_scheme_gates_and_inheritance_flows() {
        let reply = run(
            "@media (prefers-color-scheme: dark) { :root { color: rgb(8, 8, 8); } }\n\
             @media (prefers-color-scheme: light) { :root { color: rgb(7, 7, 7); } }",
        );
        // env is dark; color inherits to every descendant.
        assert_eq!(decls(&reply, "legend")["color"], "#080808");
    }

    #[test]
    fn out_of_profile_constructs_are_reported_not_guessed() {
        let reply = run(".smoke-tick:hover { color: red; }\n\
             @keyframes spin { from { opacity: 0; } }\n\
             .smoke-tick { width: 50%; }");
        assert!(decls(&reply, "tick_label").get("color").is_none());
        assert_eq!(reply.unsupported.len(), 3, "{:?}", reply.unsupported);
    }

    #[test]
    fn child_combinator_requires_direct_parent() {
        let reply = run(
            "[data-xy-slot=\"root\"] > [data-xy-slot=\"tick_label\"] { color: red; }\n\
             [data-xy-slot=\"chrome\"] > [data-xy-slot=\"tick_label\"] { font-weight: 700; }",
        );
        let d = decls(&reply, "tick_label");
        assert!(d.get("color").is_none(), "root is not the direct parent");
        assert_eq!(d["font-weight"], "700");
    }
}
