from __future__ import annotations

import pytest

from xy.pyplot._fmt import parse_fmt


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("r--o", ("r", "--", "o")),
        ("r--", ("r", "--", None)),
        ("--r", ("r", "--", None)),
        ("o", (None, None, "o")),
        ("go", ("g", None, "o")),
        ("-.", (None, "-.", None)),
        (":", (None, ":", None)),
        ("k", ("k", None, None)),
        ("C1-.s", ("C1", "-.", "s")),
        ("C9", ("C9", None, None)),
        ("bs-", ("b", "-", "s")),
        ("", (None, None, None)),
        ("D-", (None, "-", "D")),
        ("x:", (None, ":", "x")),
    ],
)
def test_parse(fmt: str, expected: tuple) -> None:
    assert parse_fmt(fmt) == expected


def test_marker_one_is_not_a_linestyle_dash() -> None:
    # '1' is the tri_down marker, never part of a linestyle.
    assert parse_fmt("1") == (None, None, "1")


@pytest.mark.parametrize("bad", ["z", "r--q", "??"])
def test_rejects_unknown(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_fmt(bad)
