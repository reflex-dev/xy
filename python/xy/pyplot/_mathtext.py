"""Bounded TeX-subset → unicode text conversion for shim-rendered chrome.

Matplotlib renders ``$...$`` spans with its own mathtext engine; xy's static
exporters draw plain glyph runs. This module converts the small TeX subset
that chart labels actually use (greek letters, super/subscripts, common
operators, ``\\frac``) into unicode so ``km$^2$`` reads km² instead of raw
TeX source. It is total: unsupported tokens degrade locally to readable plain
text so one unfamiliar command cannot expose TeX source across a whole label.
"""

# ruff: noqa: RUF001 — the whole point of this module is unicode lookalikes.
from __future__ import annotations

import re

_COMMANDS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "times": "×",
    "cdot": "·",
    "pm": "±",
    "mp": "∓",
    "leq": "≤",
    "le": "≤",
    "geq": "≥",
    "ge": "≥",
    "neq": "≠",
    "ne": "≠",
    "approx": "≈",
    "sim": "~",
    "infty": "∞",
    "partial": "∂",
    "nabla": "∇",
    "sqrt": "√",
    "circ": "°",
    "degree": "°",
    "rightarrow": "→",
    "to": "→",
    "leftarrow": "←",
    "sum": "Σ",
    "prod": "Π",
    "int": "∫",
    "propto": "∝",
    "in": "∈",
    "clubsuit": "♣",
    "diamondsuit": "♦",
    "heartsuit": "♥",
    "spadesuit": "♠",
    "percent": "%",
    "%": "%",
    # TeX ignores ordinary spaces in math mode.  Explicit spacing commands
    # survive through a sentinel until that whitespace has been removed.
    ",": "\x01",
    ";": "\x01",
    " ": "\x01",
    "!": "",
    # Matplotlib's named functions are upright roman glyph runs, not unknown
    # TeX commands and not italic variables.
    "arccos": "arccos",
    "arcsin": "arcsin",
    "arctan": "arctan",
    "arg": "arg",
    "cos": "cos",
    "cosh": "cosh",
    "cot": "cot",
    "csc": "csc",
    "deg": "deg",
    "det": "det",
    "dim": "dim",
    "exp": "exp",
    "gcd": "gcd",
    "hom": "hom",
    "ker": "ker",
    "lg": "lg",
    "lim": "lim",
    "liminf": "liminf",
    "limsup": "limsup",
    "ln": "ln",
    "log": "log",
    "max": "max",
    "min": "min",
    "sec": "sec",
    "sin": "sin",
    "sinh": "sinh",
    "sup": "sup",
    "tan": "tan",
}

_UPRIGHT_COMMANDS = frozenset(
    {
        "Gamma",
        "Delta",
        "Theta",
        "Lambda",
        "Xi",
        "Pi",
        "Sigma",
        "Phi",
        "Psi",
        "Omega",
        "sum",
        "prod",
    }
    | {
        name
        for name, value in _COMMANDS.items()
        if name.isalpha() and value.isascii() and value.isalpha()
    }
)

# Wrappers whose braces disappear and whose contents pass through.
_WRAPPERS = ("mathdefault", "mathrm", "mathit", "mathbf", "text", "textrm", "operatorname")
_UPRIGHT_WRAPPERS = frozenset({"mathdefault", "mathrm", "mathbf", "text", "textrm", "operatorname"})

_SUPERSCRIPTS = dict(zip("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ", strict=True))
_SUBSCRIPTS = dict(
    zip("0123456789+-=()aehiklmnoprstuvx", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑₕᵢₖₗₘₙₒₚᵣₛₜᵤᵥₓ", strict=True)
)

_MATH_SPAN = re.compile(r"\$([^$]*)\$")
_SCRIPT = re.compile(r"([\^_])(\{[^{}]*\}|[^\s{}])")
_COMMAND = re.compile(r"\\([A-Za-z]+|[%,;! ])")
_STYLE_ITALIC = "\x02"
_STYLE_UPRIGHT = "\x03"
_STYLE_POP = "\x04"


def _convert_script(kind: str, body: str) -> str:
    """Unicode a script when possible, otherwise retain a readable local form."""
    body = body[1:-1] if body.startswith("{") else body
    table = _SUPERSCRIPTS if kind == "^" else _SUBSCRIPTS
    if body and all(ch in table for ch in body):
        return "".join(table[ch] for ch in body)
    # Unicode has no uppercase subscripts (the gallery commonly uses f_X).
    # Preserve the case and relationship instead of rejecting the whole math
    # span or silently changing the variable to lowercase.
    return kind + (body if len(body) <= 1 else f"({body})")


def _balanced_group(text: str, start: int) -> tuple[str, int] | None:
    """Return one balanced ``{...}`` body and the first following index."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for index in range(start, len(text)):
        character = text[index]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    return None


def _fraction_piece(body: str) -> str:
    """Parenthesize fraction operands whose top-level operators need grouping."""
    depth = 0
    for character in body:
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(0, depth - 1)
        elif depth == 0 and character in "+-=/":
            return f"({body})"
    return body


def _replace_fractions(text: str) -> str:
    """Flatten ``\\frac`` with balanced, recursively parsed brace arguments."""
    pieces: list[str] = []
    cursor = 0
    while True:
        start = text.find(r"\frac", cursor)
        if start < 0:
            pieces.append(text[cursor:])
            break
        pieces.append(text[cursor:start])
        numerator = _balanced_group(text, start + len(r"\frac"))
        if numerator is None:
            pieces.append("frac")
            cursor = start + len(r"\frac")
            continue
        denominator = _balanced_group(text, numerator[1])
        if denominator is None:
            pieces.append("frac" + text[start + len(r"\frac") : numerator[1]])
            cursor = numerator[1]
            continue
        numerator_text = _replace_fractions(numerator[0])
        denominator_text = _replace_fractions(denominator[0])
        pieces.append(f"{_fraction_piece(numerator_text)}/{_fraction_piece(denominator_text)}")
        cursor = denominator[1]
    return "".join(pieces)


def _convert_math_styled(body: str) -> tuple[str, list[bool]] | None:
    """Convert one math span while retaining each glyph's source font style."""
    out = _replace_fractions(body)

    def script(match: re.Match[str]) -> str:
        return _convert_script(match.group(1), match.group(2))

    # Scripts first: converting ^{3} removes the inner braces, so wrappers
    # like \mathdefault{10^{3}} become flat and unwrap cleanly below.
    out = _SCRIPT.sub(script, out)
    for name in _WRAPPERS:
        marker = _STYLE_UPRIGHT if name in _UPRIGHT_WRAPPERS else _STYLE_ITALIC
        out = re.sub(
            r"\\" + name + r"\{([^{}]*)\}",
            lambda match, marker=marker: marker + match.group(1) + _STYLE_POP,
            out,
        )
    out = out.replace("\\left", "").replace("\\right", "")

    def command(match: re.Match[str]) -> str:
        name = match.group(1)
        converted = _COMMANDS.get(name)
        if converted is None:
            # Keep the local token readable but never expose a raw backslash
            # command in legend or chrome text.
            return name
        if name in _UPRIGHT_COMMANDS:
            return _STYLE_UPRIGHT + converted + _STYLE_POP
        return converted

    out = _COMMAND.sub(command, out)
    out = out.replace("\\", "")

    # Unescaped spaces are insignificant in math mode.  Explicit spacing
    # commands survive as ``\x01``.  A stack lets command-local upright spans
    # restore an enclosing wrapper rather than flattening all provenance.
    pieces: list[str] = []
    italic: list[bool] = []
    style_stack = [True]
    for character in out:
        if character == _STYLE_ITALIC:
            style_stack.append(True)
        elif character == _STYLE_UPRIGHT:
            style_stack.append(False)
        elif character == _STYLE_POP:
            if len(style_stack) > 1:
                style_stack.pop()
        elif character.isspace():
            continue
        elif character not in "{}":
            pieces.append(" " if character == "\x01" else "−" if character == "-" else character)
            italic.append(style_stack[-1])
    return "".join(pieces), italic


def _convert_math(body: str) -> str | None:
    """Convert one $...$ span; None when it needs more TeX than we speak."""
    converted = _convert_math_styled(body)
    return None if converted is None else converted[0]


def mathtext_to_unicode(text: str) -> str:
    """Render ``$...$`` spans as unicode; unconvertible input passes through."""
    if "$" not in text:
        return text
    pieces: list[str] = []
    last = 0
    for match in _MATH_SPAN.finditer(text):
        converted = _convert_math(match.group(1))
        if converted is None:
            return text
        pieces.append(text[last : match.start()])
        pieces.append(converted)
        last = match.end()
    pieces.append(text[last:])
    return "".join(pieces)


def mathtext_italic_ranges(text: str) -> tuple[str, list[tuple[int, int]]]:
    r"""Flatten mathtext and return output ranges that use math italics.

    Matplotlib defaults variables (including Greek letters) to italics while
    named functions such as ``\cos`` and ``\exp`` remain upright.  The
    renderer-facing range list preserves that distinction without exposing a
    full TeX layout engine.
    """
    converted = mathtext_to_unicode(text)
    if converted == text or "$" not in text:
        return converted, []

    ranges: list[tuple[int, int]] = []
    output_cursor = 0
    source_cursor = 0
    for match in _MATH_SPAN.finditer(text):
        prefix = text[source_cursor : match.start()]
        output_cursor += len(prefix)
        styled = _convert_math_styled(match.group(1))
        if styled is None:  # guarded by ``converted == text`` above
            return converted, []
        body, italic = styled
        token_start: int | None = None
        for index in range(len(body) + 1):
            if index < len(body) and body[index].isalpha() and italic[index]:
                if token_start is None:
                    token_start = index
                continue
            if token_start is not None:
                ranges.append((output_cursor + token_start, output_cursor + index))
                token_start = None
        output_cursor += len(body)
        source_cursor = match.end()
    return converted, ranges
