"""The vendored XML escaper must never drift from the stdlib it replaced.

`xy._svg.escape` is a local copy of `xml.sax.saxutils.escape` (see the docstring
there for why). These tests are the drift guard: they import the stdlib version
*inside the test* — never at module import of xy — and compare outputs.
"""

from __future__ import annotations

import random
import subprocess
import sys
from xml.sax.saxutils import escape as stdlib_escape

import pytest

from xy._svg import escape

# Characters that matter for XML escaping, plus neighbours that must NOT change.
ALPHABET = "&<>\"'; abc\\/=\n\té中\U0001f600"


def test_matches_stdlib_on_every_short_string() -> None:
    """Exhaustive over all strings of length <= 3 on a hostile alphabet."""
    for a in ALPHABET:
        assert escape(a) == stdlib_escape(a)
        for b in ALPHABET:
            assert escape(a + b) == stdlib_escape(a + b)
            for c in ALPHABET:
                s = a + b + c
                assert escape(s) == stdlib_escape(s)


@pytest.mark.parametrize(
    "entities",
    [
        {},
        {chr(34): "&quot;"},
        {"'": "&apos;"},
        {chr(34): "&quot;", "'": "&apos;"},
        # Overlapping/chained replacements exercise dict ordering.
        {"a": "b", "b": "c"},
    ],
)
def test_matches_stdlib_with_entities(entities: dict[str, str]) -> None:
    rng = random.Random(20260725)
    for _ in range(20_000):
        s = "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(0, 12)))
        assert escape(s, entities) == stdlib_escape(s, entities)


def test_ampersand_goes_first() -> None:
    """The one ordering bug a naive rewrite makes: && double-escaping."""
    assert escape("&lt;") == "&amp;lt;"
    assert escape("<&>") == "&lt;&amp;&gt;"
    assert escape("") == ""


def test_none_entities_matches_empty_dict() -> None:
    """Our signature uses None instead of a mutable default; same behavior."""
    assert escape("<a&b>", None) == escape("<a&b>", {}) == stdlib_escape("<a&b>")


def test_svg_export_does_not_import_urllib_or_ssl() -> None:
    """The whole point: a static export must not drag in the network stack.

    Runs in a fresh subprocess because pytest itself imports `email` and
    friends, which would mask the regression in-process.
    """
    code = (
        "import sys; import numpy as np; import xy\n"
        "fig = xy.scatter_chart(xy.scatter(x=np.arange(5.0), y=np.arange(5.0)),\n"
        "                       title='a & b < c > d').figure()\n"
        "svg = fig.to_svg(width=200, height=150)\n"
        "assert '&amp;' in svg and '&lt;' in svg and '&gt;' in svg, 'escape not exercised'\n"
        "leaked = {'urllib.request', 'ssl', 'http.client', 'email', 'socket'} & set(sys.modules)\n"
        "assert not leaked, f'static SVG export imported {sorted(leaked)}'\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout
