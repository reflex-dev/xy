//! Focused native SVG serialization helpers.
//!
//! SVG and PNG share screen-space geometry.  Keeping the high-cardinality
//! coordinate serialization here avoids creating one Python string per point;
//! broader scene construction can migrate behind the same private boundary.

use std::fmt::Write;

#[inline]
fn push_num(out: &mut String, value: f64) {
    let start = out.len();
    write!(out, "{value:.2}").expect("writing to String cannot fail");
    while out.as_bytes().last() == Some(&b'0') {
        out.pop();
    }
    if out.as_bytes().last() == Some(&b'.') {
        out.pop();
    }
    // Match Python's fixed-point formatter for negative values rounding to 0.
    if &out[start..] == "-0" {
        out.truncate(start);
        out.push_str("-0");
    }
}

/// Serialize parallel screen-space coordinates as an SVG path data string.
pub fn poly_path(x: &[f64], y: &[f64]) -> Option<String> {
    if x.len() != y.len() || x.is_empty() || x.iter().chain(y).any(|v| !v.is_finite()) {
        return None;
    }
    let mut out = String::with_capacity(x.len().saturating_mul(24));
    for (i, (&x, &y)) in x.iter().zip(y).enumerate() {
        if i != 0 {
            out.push(' ');
        }
        out.push(if i == 0 { 'M' } else { 'L' });
        out.push(' ');
        push_num(&mut out, x);
        out.push(' ');
        push_num(&mut out, y);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn poly_path_matches_public_svg_number_format() {
        assert_eq!(
            poly_path(&[1.0, 2.345, -0.001], &[4.5, 6.789, -0.0]).as_deref(),
            Some("M 1 4.5 L 2.35 6.79 L -0 -0")
        );
        assert!(poly_path(&[], &[]).is_none());
        assert!(poly_path(&[1.0], &[f64::NAN]).is_none());
    }
}
