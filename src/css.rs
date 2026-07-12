//! CSS value validation and color parsing (styling contract; dossier §36).
//!
//! The styling surface promises "any CSS color the browser can resolve", so a
//! native validator cannot be a binary accept/reject: it is **tiered**.
//!
//! - **Closed grammars parse strictly**: hex colors (3/4/6/8 digits, no
//!   prefix-parsing), `rgb()`/`rgba()`/`hsl()`/`hsla()`, the CSS named-color
//!   table, lengths (number + unit), and bare numbers. A malformed value is a
//!   loud error naming the reason — never a silently-black mark (§28: no
//!   silent decisions).
//! - **Browser-only constructs pass through**: `var()`, `oklch()`,
//!   `color-mix()`, `calc()`, … are shape-checked (known head, balanced
//!   parens) and left for the client's probe element to resolve (§36).
//! - **Every value gets a declaration-context safety check**: balanced
//!   quotes/parens, no `;`/`{`/`}` outside quotes, no `</`, no control
//!   characters — so a style value can never escape its declaration when
//!   serialized (the HTML-export safety contract, applied to styles).
//!
//! One grammar serves the Python API gate (`fc_css_check` over the C ABI) and
//! the native raster's color resolution, so validation and rendering cannot
//! drift.

/// Why a value was rejected. Discriminants are the C-ABI error codes
/// (returned negated by `fc_css_check`); keep them stable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CssErr {
    Empty = 1,
    UnsafeChar = 2,
    Unbalanced = 3,
    BadHex = 4,
    BadColor = 5,
    UnknownColorName = 6,
    BadNumber = 7,
    BadUnit = 8,
    BadFunction = 9,
    BadProperty = 10,
}

/// A validated value: statically parsed here, or valid-but-browser-resolved.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Checked {
    /// Fully parsed; for colors the RGBA (premultiplied nothing, plain
    /// 0..1 channels) is available.
    Parsed(Option<[f32; 4]>),
    /// Syntactically valid, but only a live browser (or the mark's own
    /// color, for `currentColor`) can resolve it.
    Passthrough,
}

/// Color functions the browser resolves that we only shape-check.
const PASSTHROUGH_COLOR_FNS: &[&str] = &[
    "color",
    "color-mix",
    "hwb",
    "lab",
    "lch",
    "light-dark",
    "oklab",
    "oklch",
    "var",
];

/// Value functions valid wherever a length/number token is expected.
const PASSTHROUGH_VALUE_FNS: &[&str] = &["calc", "clamp", "max", "min", "var"];

/// CSS-wide keywords, valid for any property.
const GLOBAL_KEYWORDS: &[&str] = &["inherit", "initial", "revert", "unset"];

/// Keywords accepted where a length token is expected.
const LENGTH_KEYWORDS: &[&str] = &[
    "auto",
    "fit-content",
    "max-content",
    "min-content",
    "none",
    "normal",
];

const LENGTH_UNITS: &[&str] = &[
    "%", "ch", "cm", "em", "ex", "in", "mm", "pc", "pt", "px", "q", "rem", "vh", "vmax", "vmin",
    "vw",
];

/// Properties whose value must be a single CSS `<color>`.
const COLOR_PROPS: &[&str] = &[
    "accent-color",
    "background-color",
    "border-bottom-color",
    "border-color",
    "border-left-color",
    "border-right-color",
    "border-top-color",
    "caret-color",
    "color",
    "column-rule-color",
    "fill",
    "outline-color",
    "stroke",
    "text-decoration-color",
    "text-emphasis-color",
];

/// Properties whose value is one or more length/percentage tokens
/// (shorthands like `padding: 4px 8px` and `border-radius: 8px / 4px`
/// validate per-token).
const LENGTH_PROPS: &[&str] = &[
    "border-bottom-left-radius",
    "border-bottom-right-radius",
    "border-bottom-width",
    "border-left-width",
    "border-radius",
    "border-right-width",
    "border-spacing",
    "border-top-left-radius",
    "border-top-right-radius",
    "border-top-width",
    "border-width",
    "bottom",
    "column-gap",
    "font-size",
    "gap",
    "height",
    "inset",
    "left",
    "letter-spacing",
    "line-height",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "min-height",
    "min-width",
    "outline-offset",
    "outline-width",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "right",
    "row-gap",
    "stroke-width",
    "text-indent",
    "top",
    "width",
    "word-spacing",
];

/// Properties whose value is a single number (or a keyword ident).
const NUMBER_PROPS: &[&str] = &[
    "flex-grow",
    "flex-shrink",
    "font-weight",
    "opacity",
    "order",
    "tab-size",
    "z-index",
];

/// The CSS named-color table (CSS Color 4), sorted for binary search.
const NAMED_COLORS: &[(&str, [u8; 3])] = &[
    ("aliceblue", [240, 248, 255]),
    ("antiquewhite", [250, 235, 215]),
    ("aqua", [0, 255, 255]),
    ("aquamarine", [127, 255, 212]),
    ("azure", [240, 255, 255]),
    ("beige", [245, 245, 220]),
    ("bisque", [255, 228, 196]),
    ("black", [0, 0, 0]),
    ("blanchedalmond", [255, 235, 205]),
    ("blue", [0, 0, 255]),
    ("blueviolet", [138, 43, 226]),
    ("brown", [165, 42, 42]),
    ("burlywood", [222, 184, 135]),
    ("cadetblue", [95, 158, 160]),
    ("chartreuse", [127, 255, 0]),
    ("chocolate", [210, 105, 30]),
    ("coral", [255, 127, 80]),
    ("cornflowerblue", [100, 149, 237]),
    ("cornsilk", [255, 248, 220]),
    ("crimson", [220, 20, 60]),
    ("cyan", [0, 255, 255]),
    ("darkblue", [0, 0, 139]),
    ("darkcyan", [0, 139, 139]),
    ("darkgoldenrod", [184, 134, 11]),
    ("darkgray", [169, 169, 169]),
    ("darkgreen", [0, 100, 0]),
    ("darkgrey", [169, 169, 169]),
    ("darkkhaki", [189, 183, 107]),
    ("darkmagenta", [139, 0, 139]),
    ("darkolivegreen", [85, 107, 47]),
    ("darkorange", [255, 140, 0]),
    ("darkorchid", [153, 50, 204]),
    ("darkred", [139, 0, 0]),
    ("darksalmon", [233, 150, 122]),
    ("darkseagreen", [143, 188, 143]),
    ("darkslateblue", [72, 61, 139]),
    ("darkslategray", [47, 79, 79]),
    ("darkslategrey", [47, 79, 79]),
    ("darkturquoise", [0, 206, 209]),
    ("darkviolet", [148, 0, 211]),
    ("deeppink", [255, 20, 147]),
    ("deepskyblue", [0, 191, 255]),
    ("dimgray", [105, 105, 105]),
    ("dimgrey", [105, 105, 105]),
    ("dodgerblue", [30, 144, 255]),
    ("firebrick", [178, 34, 34]),
    ("floralwhite", [255, 250, 240]),
    ("forestgreen", [34, 139, 34]),
    ("fuchsia", [255, 0, 255]),
    ("gainsboro", [220, 220, 220]),
    ("ghostwhite", [248, 248, 255]),
    ("gold", [255, 215, 0]),
    ("goldenrod", [218, 165, 32]),
    ("gray", [128, 128, 128]),
    ("green", [0, 128, 0]),
    ("greenyellow", [173, 255, 47]),
    ("grey", [128, 128, 128]),
    ("honeydew", [240, 255, 240]),
    ("hotpink", [255, 105, 180]),
    ("indianred", [205, 92, 92]),
    ("indigo", [75, 0, 130]),
    ("ivory", [255, 255, 240]),
    ("khaki", [240, 230, 140]),
    ("lavender", [230, 230, 250]),
    ("lavenderblush", [255, 240, 245]),
    ("lawngreen", [124, 252, 0]),
    ("lemonchiffon", [255, 250, 205]),
    ("lightblue", [173, 216, 230]),
    ("lightcoral", [240, 128, 128]),
    ("lightcyan", [224, 255, 255]),
    ("lightgoldenrodyellow", [250, 250, 210]),
    ("lightgray", [211, 211, 211]),
    ("lightgreen", [144, 238, 144]),
    ("lightgrey", [211, 211, 211]),
    ("lightpink", [255, 182, 193]),
    ("lightsalmon", [255, 160, 122]),
    ("lightseagreen", [32, 178, 170]),
    ("lightskyblue", [135, 206, 250]),
    ("lightslategray", [119, 136, 153]),
    ("lightslategrey", [119, 136, 153]),
    ("lightsteelblue", [176, 196, 222]),
    ("lightyellow", [255, 255, 224]),
    ("lime", [0, 255, 0]),
    ("limegreen", [50, 205, 50]),
    ("linen", [250, 240, 230]),
    ("magenta", [255, 0, 255]),
    ("maroon", [128, 0, 0]),
    ("mediumaquamarine", [102, 205, 170]),
    ("mediumblue", [0, 0, 205]),
    ("mediumorchid", [186, 85, 211]),
    ("mediumpurple", [147, 112, 219]),
    ("mediumseagreen", [60, 179, 113]),
    ("mediumslateblue", [123, 104, 238]),
    ("mediumspringgreen", [0, 250, 154]),
    ("mediumturquoise", [72, 209, 204]),
    ("mediumvioletred", [199, 21, 133]),
    ("midnightblue", [25, 25, 112]),
    ("mintcream", [245, 255, 250]),
    ("mistyrose", [255, 228, 225]),
    ("moccasin", [255, 228, 181]),
    ("navajowhite", [255, 222, 173]),
    ("navy", [0, 0, 128]),
    ("oldlace", [253, 245, 230]),
    ("olive", [128, 128, 0]),
    ("olivedrab", [107, 142, 35]),
    ("orange", [255, 165, 0]),
    ("orangered", [255, 69, 0]),
    ("orchid", [218, 112, 214]),
    ("palegoldenrod", [238, 232, 170]),
    ("palegreen", [152, 251, 152]),
    ("paleturquoise", [175, 238, 238]),
    ("palevioletred", [219, 112, 147]),
    ("papayawhip", [255, 239, 213]),
    ("peachpuff", [255, 218, 185]),
    ("peru", [205, 133, 63]),
    ("pink", [255, 192, 203]),
    ("plum", [221, 160, 221]),
    ("powderblue", [176, 224, 230]),
    ("purple", [128, 0, 128]),
    ("rebeccapurple", [102, 51, 153]),
    ("red", [255, 0, 0]),
    ("rosybrown", [188, 143, 143]),
    ("royalblue", [65, 105, 225]),
    ("saddlebrown", [139, 69, 19]),
    ("salmon", [250, 128, 114]),
    ("sandybrown", [244, 164, 96]),
    ("seagreen", [46, 139, 87]),
    ("seashell", [255, 245, 238]),
    ("sienna", [160, 82, 45]),
    ("silver", [192, 192, 192]),
    ("skyblue", [135, 206, 235]),
    ("slateblue", [106, 90, 205]),
    ("slategray", [112, 128, 144]),
    ("slategrey", [112, 128, 144]),
    ("snow", [255, 250, 250]),
    ("springgreen", [0, 255, 127]),
    ("steelblue", [70, 130, 180]),
    ("tan", [210, 180, 140]),
    ("teal", [0, 128, 128]),
    ("thistle", [216, 191, 216]),
    ("tomato", [255, 99, 71]),
    ("turquoise", [64, 224, 208]),
    ("violet", [238, 130, 238]),
    ("wheat", [245, 222, 179]),
    ("white", [255, 255, 255]),
    ("whitesmoke", [245, 245, 245]),
    ("yellow", [255, 255, 0]),
    ("yellowgreen", [154, 205, 50]),
];

/// Declaration-context safety: printable, balanced quotes/parens, no `;`,
/// `{`, `}` outside quotes, and never `</` (style-tag breakout) anywhere.
pub fn safety_check(s: &str) -> Result<(), CssErr> {
    let mut depth: i32 = 0;
    let mut quote: Option<char> = None;
    let mut prev = '\0';
    for c in s.chars() {
        if c < ' ' || c == '\u{7f}' {
            return Err(CssErr::UnsafeChar);
        }
        if prev == '<' && c == '/' {
            return Err(CssErr::UnsafeChar);
        }
        match quote {
            Some(q) => {
                if c == q {
                    quote = None;
                }
            }
            None => match c {
                '\'' | '"' => quote = Some(c),
                '(' => depth += 1,
                ')' => {
                    depth -= 1;
                    if depth < 0 {
                        return Err(CssErr::Unbalanced);
                    }
                }
                ';' | '{' | '}' => return Err(CssErr::UnsafeChar),
                _ => {}
            },
        }
        prev = c;
    }
    if depth != 0 || quote.is_some() {
        return Err(CssErr::Unbalanced);
    }
    Ok(())
}

fn hex_color(digits: &str) -> Result<[f32; 4], CssErr> {
    let n = digits.len();
    if !matches!(n, 3 | 4 | 6 | 8) || !digits.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(CssErr::BadHex);
    }
    let nib = |b: u8| -> u32 {
        (digits.as_bytes()[b as usize] as char)
            .to_digit(16)
            .unwrap()
    };
    let (r, g, b, a) = if n <= 4 {
        let a = if n == 4 { nib(3) * 17 } else { 255 };
        (nib(0) * 17, nib(1) * 17, nib(2) * 17, a)
    } else {
        let byte = |i: u8| nib(i) * 16 + nib(i + 1);
        let a = if n == 8 { byte(6) } else { 255 };
        (byte(0), byte(2), byte(4), a)
    };
    Ok([
        r as f32 / 255.0,
        g as f32 / 255.0,
        b as f32 / 255.0,
        a as f32 / 255.0,
    ])
}

/// One numeric channel: a plain float or a percentage of `pct_base`,
/// clamped to `0..=max` (CSS clamps out-of-range channels).
fn channel(tok: &str, max: f32, pct_base: f32) -> Result<f32, CssErr> {
    let (num, scale) = match tok.strip_suffix('%') {
        Some(n) => (n, pct_base / 100.0),
        None => (tok, 1.0),
    };
    let v: f32 = num.parse().map_err(|_| CssErr::BadNumber)?;
    if !v.is_finite() {
        return Err(CssErr::BadNumber);
    }
    Ok((v * scale).clamp(0.0, max))
}

fn split_channels(args: &str) -> Vec<&str> {
    args.split(|c: char| c == ',' || c == '/' || c.is_whitespace())
        .filter(|t| !t.is_empty())
        .collect()
}

fn rgb_args(args: &str) -> Result<[f32; 4], CssErr> {
    let toks = split_channels(args);
    if !matches!(toks.len(), 3 | 4) {
        return Err(CssErr::BadColor);
    }
    let r = channel(toks[0], 255.0, 255.0)? / 255.0;
    let g = channel(toks[1], 255.0, 255.0)? / 255.0;
    let b = channel(toks[2], 255.0, 255.0)? / 255.0;
    let a = if toks.len() == 4 {
        channel(toks[3], 1.0, 1.0)?
    } else {
        1.0
    };
    Ok([r, g, b, a])
}

fn hsl_args(args: &str) -> Result<[f32; 4], CssErr> {
    let toks = split_channels(args);
    if !matches!(toks.len(), 3 | 4) {
        return Err(CssErr::BadColor);
    }
    let h_tok = toks[0].strip_suffix("deg").unwrap_or(toks[0]);
    let h: f32 = h_tok.parse().map_err(|_| CssErr::BadNumber)?;
    if !h.is_finite() {
        return Err(CssErr::BadNumber);
    }
    let s = channel(
        toks[1].strip_suffix('%').ok_or(CssErr::BadUnit)?,
        100.0,
        100.0,
    )? / 100.0;
    let l = channel(
        toks[2].strip_suffix('%').ok_or(CssErr::BadUnit)?,
        100.0,
        100.0,
    )? / 100.0;
    let a = if toks.len() == 4 {
        channel(toks[3], 1.0, 1.0)?
    } else {
        1.0
    };
    // CSS HSL -> RGB (hue wraps; s/l already 0..1).
    let h = h.rem_euclid(360.0) / 30.0;
    let f = |n: f32| {
        let k = (n + h).rem_euclid(12.0);
        l - s * l.min(1.0 - l) * (k - 3.0).min(9.0 - k).clamp(-1.0, 1.0)
    };
    Ok([f(0.0), f(8.0), f(4.0), a])
}

/// Parse a CSS `<color>`. `Ok(Checked::Parsed(Some(rgba)))` for statically
/// resolvable colors; `Parsed(None)` for `currentColor` (valid, resolves to
/// the mark/text color at paint); `Passthrough` for browser-resolved
/// functions. Errors are loud and specific.
pub fn parse_color(raw: &str) -> Result<Checked, CssErr> {
    let s = raw.trim();
    if s.is_empty() {
        return Err(CssErr::Empty);
    }
    safety_check(s)?;
    if let Some(digits) = s.strip_prefix('#') {
        return hex_color(digits).map(|c| Checked::Parsed(Some(c)));
    }
    let lower = s.to_ascii_lowercase();
    match lower.as_str() {
        "transparent" => return Ok(Checked::Parsed(Some([0.0, 0.0, 0.0, 0.0]))),
        "currentcolor" => return Ok(Checked::Parsed(None)),
        _ => {}
    }
    if let Some(open) = lower.find('(') {
        if !lower.ends_with(')') {
            return Err(CssErr::Unbalanced);
        }
        let head = &lower[..open];
        let args = &lower[open + 1..lower.len() - 1];
        if args.contains("var(") {
            // Channels from custom properties resolve only in the browser.
            return Ok(Checked::Passthrough);
        }
        return match head {
            "rgb" | "rgba" => rgb_args(args).map(|c| Checked::Parsed(Some(c))),
            "hsl" | "hsla" => hsl_args(args).map(|c| Checked::Parsed(Some(c))),
            _ if PASSTHROUGH_COLOR_FNS.contains(&head) => Ok(Checked::Passthrough),
            _ => Err(CssErr::BadFunction),
        };
    }
    match NAMED_COLORS.binary_search_by(|(name, _)| name.cmp(&lower.as_str())) {
        Ok(i) => {
            let [r, g, b] = NAMED_COLORS[i].1;
            Ok(Checked::Parsed(Some([
                r as f32 / 255.0,
                g as f32 / 255.0,
                b as f32 / 255.0,
                1.0,
            ])))
        }
        Err(_) => Err(CssErr::UnknownColorName),
    }
}

/// Split on whitespace outside parentheses, so `clamp(1px, 2vw, 3px) 4px`
/// yields two tokens. `/` separates too (border-radius shorthand).
fn split_tokens(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut depth = 0u32;
    let mut start: Option<usize> = None;
    for (i, c) in s.char_indices() {
        let sep = depth == 0 && (c.is_whitespace() || c == '/');
        match (sep, start) {
            (true, Some(b)) => {
                out.push(&s[b..i]);
                start = None;
            }
            (false, None) => start = Some(i),
            _ => {}
        }
        if c == '(' {
            depth += 1;
        } else if c == ')' {
            depth = depth.saturating_sub(1);
        }
    }
    if let Some(b) = start {
        out.push(&s[b..]);
    }
    out
}

fn is_ident(s: &str) -> bool {
    let mut chars = s.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_alphabetic())
        && chars.all(|c| c.is_ascii_alphanumeric() || c == '-')
}

fn fn_head(tok: &str) -> Option<&str> {
    tok.find('(')
        .filter(|_| tok.ends_with(')'))
        .map(|i| &tok[..i])
}

/// One length/percentage token: number + known unit, a bare number, a
/// layout keyword, or a browser-resolved function.
pub fn check_length_token(raw: &str) -> Result<Checked, CssErr> {
    let tok = raw.trim();
    if tok.is_empty() {
        return Err(CssErr::Empty);
    }
    let lower = tok.to_ascii_lowercase();
    if LENGTH_KEYWORDS.contains(&lower.as_str()) || GLOBAL_KEYWORDS.contains(&lower.as_str()) {
        return Ok(Checked::Parsed(None));
    }
    if let Some(head) = fn_head(&lower) {
        return if PASSTHROUGH_VALUE_FNS.contains(&head) {
            Ok(Checked::Passthrough)
        } else {
            Err(CssErr::BadFunction)
        };
    }
    let unit_start = lower
        .char_indices()
        .find(|&(i, c)| !(c.is_ascii_digit() || c == '.' || ((c == '+' || c == '-') && i == 0)))
        .map(|(i, _)| i)
        .unwrap_or(lower.len());
    let (num, unit) = lower.split_at(unit_start);
    let v: f64 = num.parse().map_err(|_| CssErr::BadNumber)?;
    if !v.is_finite() {
        return Err(CssErr::BadNumber);
    }
    if !unit.is_empty() && !LENGTH_UNITS.contains(&unit) {
        return Err(CssErr::BadUnit);
    }
    Ok(Checked::Parsed(None))
}

fn check_number_value(value: &str) -> Result<Checked, CssErr> {
    let lower = value.trim().to_ascii_lowercase();
    if lower.is_empty() {
        return Err(CssErr::Empty);
    }
    if GLOBAL_KEYWORDS.contains(&lower.as_str()) || is_ident(&lower) {
        // Keyword values (`bold`, `normal`, `auto`) stay browser-checked.
        return Ok(Checked::Parsed(None));
    }
    if let Some(head) = fn_head(&lower) {
        return if PASSTHROUGH_VALUE_FNS.contains(&head) {
            Ok(Checked::Passthrough)
        } else {
            Err(CssErr::BadFunction)
        };
    }
    let v: f64 = lower.parse().map_err(|_| CssErr::BadNumber)?;
    if !v.is_finite() {
        return Err(CssErr::BadNumber);
    }
    Ok(Checked::Parsed(None))
}

/// Validate one declaration. Properties with a closed value grammar
/// (colors, lengths, numbers) parse strictly; every other property gets the
/// declaration-context safety check and passes through — the styling
/// contract says the user's CSS is authority, so unknown properties are not
/// rejected, only unsafe ones.
pub fn check_declaration(prop: &str, value: &str) -> Result<Checked, CssErr> {
    let p = prop.trim();
    if p.is_empty() {
        return Err(CssErr::BadProperty);
    }
    let value_t = value.trim();
    if value_t.is_empty() {
        return Err(CssErr::Empty);
    }
    safety_check(value_t)?;
    if let Some(custom) = p.strip_prefix("--") {
        return if is_ident(&custom.to_ascii_lowercase()) {
            Ok(Checked::Passthrough)
        } else {
            Err(CssErr::BadProperty)
        };
    }
    let p_lower = p.to_ascii_lowercase();
    if !is_ident(&p_lower) {
        return Err(CssErr::BadProperty);
    }
    let v_lower = value_t.to_ascii_lowercase();
    if GLOBAL_KEYWORDS.contains(&v_lower.as_str()) {
        return Ok(Checked::Parsed(None));
    }
    if COLOR_PROPS.contains(&p_lower.as_str()) {
        return parse_color(value_t);
    }
    if LENGTH_PROPS.contains(&p_lower.as_str()) {
        let toks = split_tokens(value_t);
        if toks.is_empty() {
            return Err(CssErr::Empty);
        }
        let mut passthrough = false;
        for tok in toks {
            passthrough |= matches!(check_length_token(tok)?, Checked::Passthrough);
        }
        return Ok(if passthrough {
            Checked::Passthrough
        } else {
            Checked::Parsed(None)
        });
    }
    if NUMBER_PROPS.contains(&p_lower.as_str()) {
        return check_number_value(value_t);
    }
    Ok(Checked::Passthrough)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rgba(s: &str) -> [f32; 4] {
        match parse_color(s) {
            Ok(Checked::Parsed(Some(c))) => c,
            other => panic!("{s:?} -> {other:?}"),
        }
    }

    #[test]
    fn named_table_is_sorted_for_binary_search() {
        for pair in NAMED_COLORS.windows(2) {
            assert!(pair[0].0 < pair[1].0, "{} !< {}", pair[0].0, pair[1].0);
        }
    }

    #[test]
    fn hex_forms_parse_exactly() {
        assert_eq!(rgba("#fff"), [1.0, 1.0, 1.0, 1.0]);
        assert_eq!(rgba("#f00e")[3], 14.0 * 17.0 / 255.0);
        assert_eq!(rgba("#3b82f6"), rgba("#3B82F6"));
        assert_eq!(rgba("#3b82f680")[3], 128.0 / 255.0);
    }

    #[test]
    fn hex_rejects_prefix_parsing_and_bad_lengths() {
        // The regression: parseInt-style prefix acceptance treated
        // "#3b82zz" as valid hex. Strict parsing must not.
        assert_eq!(parse_color("#3b82zz"), Err(CssErr::BadHex));
        assert_eq!(parse_color("#3b82f"), Err(CssErr::BadHex)); // 5 digits
        assert_eq!(parse_color("#12"), Err(CssErr::BadHex));
        assert_eq!(parse_color("#1234567"), Err(CssErr::BadHex));
        assert_eq!(parse_color("#"), Err(CssErr::BadHex));
    }

    #[test]
    fn rgb_hsl_forms() {
        assert_eq!(rgba("rgb(255, 0, 0)"), [1.0, 0.0, 0.0, 1.0]);
        assert_eq!(rgba("rgb(255 0 0 / 0.5)")[3], 0.5);
        assert_eq!(rgba("rgba(100%, 0%, 0%, 50%)")[3], 0.5);
        assert_eq!(rgba("rgb(300, -5, 0)")[0], 1.0); // CSS clamps channels
        let red = rgba("hsl(0, 100%, 50%)");
        assert!((red[0] - 1.0).abs() < 1e-6 && red[1].abs() < 1e-6);
        let teal = rgba("hsl(180deg 100% 25%)");
        assert!((teal[2] - 0.5).abs() < 1e-6);
        assert_eq!(parse_color("rgb(1, 2)"), Err(CssErr::BadColor));
        assert_eq!(parse_color("rgb(a, b, c)"), Err(CssErr::BadNumber));
        assert_eq!(parse_color("hsl(0, 1, 0.5)"), Err(CssErr::BadUnit));
    }

    #[test]
    fn named_keywords_and_dynamic() {
        assert_eq!(rgba("rebeccapurple"), rgba("#663399"));
        assert_eq!(rgba("Tomato"), rgba("#ff6347"));
        assert_eq!(rgba("transparent")[3], 0.0);
        assert_eq!(parse_color("currentColor"), Ok(Checked::Parsed(None)));
        assert_eq!(parse_color("bluu"), Err(CssErr::UnknownColorName));
        assert_eq!(parse_color(""), Err(CssErr::Empty));
    }

    #[test]
    fn browser_only_color_functions_pass_through() {
        for s in [
            "var(--accent)",
            "oklch(0.7 0.1 250)",
            "color-mix(in oklab, red, blue)",
            "light-dark(#fff, #000)",
            "rgb(var(--r), 0, 0)",
        ] {
            assert_eq!(parse_color(s), Ok(Checked::Passthrough), "{s}");
        }
        assert_eq!(parse_color("bogus(1, 2)"), Err(CssErr::BadFunction));
    }

    #[test]
    fn declaration_context_safety() {
        assert_eq!(parse_color("red;}"), Err(CssErr::UnsafeChar));
        assert_eq!(parse_color("rgb(1, 2"), Err(CssErr::Unbalanced));
        assert_eq!(safety_check("url(</style>)"), Err(CssErr::UnsafeChar));
        assert_eq!(safety_check("a { b }"), Err(CssErr::UnsafeChar));
        assert_eq!(safety_check("'unterminated"), Err(CssErr::Unbalanced));
        assert_eq!(safety_check("\"; ) { fine inside quotes\""), Ok(()));
        assert_eq!(safety_check("bad\u{7}bell"), Err(CssErr::UnsafeChar));
    }

    #[test]
    fn length_tokens() {
        for good in ["18px", "0", ".5em", "-2px", "100%", "1.25rem", "auto"] {
            assert!(check_length_token(good).is_ok(), "{good}");
        }
        assert_eq!(
            check_length_token("clamp(1px, 2vw, 3px)"),
            Ok(Checked::Passthrough)
        );
        assert_eq!(check_length_token("banana"), Err(CssErr::BadNumber));
        assert_eq!(check_length_token("12parsecs"), Err(CssErr::BadUnit));
        assert_eq!(check_length_token("12pxx"), Err(CssErr::BadUnit));
    }

    #[test]
    fn declarations() {
        let ok = |p, v| check_declaration(p, v).unwrap();
        ok("font-size", "18px");
        ok("padding", "4px 8px");
        ok("border-radius", "8px / 4px");
        ok("color", "#3b82f6");
        ok("opacity", "0.5");
        ok("font-weight", "bold");
        ok("letter-spacing", "0.02em");
        ok("width", "calc(100% - 8px)");
        ok("--chart-bg", "linear-gradient(red, blue)");
        // Unknown properties pass with safe values (user CSS is authority)...
        assert_eq!(
            check_declaration("backdrop-filter", "blur(4px)"),
            Ok(Checked::Passthrough)
        );
        // ...but closed grammars stay strict, and injection never passes.
        assert_eq!(check_declaration("color", "#3b82zz"), Err(CssErr::BadHex));
        assert_eq!(
            check_declaration("font-size", "big"),
            Err(CssErr::BadNumber)
        );
        assert_eq!(
            check_declaration("opacity", "0.5; position: fixed"),
            Err(CssErr::UnsafeChar)
        );
        assert_eq!(
            check_declaration("padding", "4px }body{"),
            Err(CssErr::UnsafeChar)
        );
        assert_eq!(check_declaration("", "x"), Err(CssErr::BadProperty));
        assert_eq!(check_declaration("1bad", "x"), Err(CssErr::BadProperty));
        assert_eq!(check_declaration("--", "x"), Err(CssErr::BadProperty));
    }
}
