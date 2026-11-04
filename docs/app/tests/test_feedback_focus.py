"""Production CSS regressions for the XY docs feedback form."""

import os

import pytest


@pytest.mark.parametrize("mode", ["light", "dark", "forced-colors"])
def test_feedback_fields_have_visible_keyboard_focus(mode: str) -> None:
    """Both fields need a visible ring after production CSS optimization."""
    base_url = os.environ.get("XY_DOCS_BASE_URL")
    if base_url is None:
        pytest.skip("XY_DOCS_BASE_URL is only set for the production-DOM check")

    from playwright.sync_api import expect, sync_playwright

    color_scheme = "dark" if mode == "dark" else "light"
    ring = "rgb(245, 245, 245)" if color_scheme == "dark" else "rgb(10, 10, 10)"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1440, "height": 900},
            color_scheme=color_scheme,
            forced_colors="active" if mode == "forced-colors" else "none",
        )
        page.goto(base_url)
        page.get_by_role("button", name="Send feedback", exact=True).click()
        form = page.locator(".docs-feedback-content")
        feedback = form.get_by_role("textbox", name="Feedback", exact=True)
        email = form.get_by_role("textbox", name="Contact email (optional)")
        page.keyboard.press("Tab")

        for field, surface in ((feedback, feedback), (email, email.locator(".."))):
            field.focus()
            expect(field).to_be_focused()
            assert field.evaluate("el => el.matches(':focus-visible')")
            if mode == "forced-colors":
                expect(surface).to_have_css("outline-style", "solid")
                expect(surface).to_have_css("outline-width", "2px")
            else:
                expect(surface).to_have_css("box-shadow", f"{ring} 0px 0px 0px 2px")

        browser.close()
