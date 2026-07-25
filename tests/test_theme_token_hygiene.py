"""Theme tokens nothing reads are named, not swallowed."""

from __future__ import annotations

import pytest

import xy

# ---------------------------------------------------------------------------
# Unknown theme tokens are allowed but never silent (§28)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token", ["text_colour", "gridcolor", "bogus_token"])
def test_a_misspelled_theme_token_warns_instead_of_vanishing(token) -> None:
    with pytest.warns(RuntimeWarning, match="no XY renderer reads"):
        xy.theme(**{token: "#ff0000"})


@pytest.mark.parametrize(
    "tokens",
    [
        {"text_color": "#ff0000"},
        {"background": "#ffffff"},
        {"font_family": "Georgia, serif"},
        {"--chart-tooltip-bg": "#000000"},
        # An author's own custom property is theirs to define and read back.
        {"--brand-accent": "#ff5c00"},
    ],
)
def test_tokens_a_renderer_reads_do_not_warn(tokens) -> None:
    import warnings

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        xy.theme(**tokens)
    assert [str(record.message) for record in records] == []
