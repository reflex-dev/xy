"""Production contracts for the announcement shared with reflex-marketing."""

import os

import pytest
from xy_docs.announcement import ANNOUNCEMENT_RELEASE


def test_production_announcement_matches_marketing_and_persists_dismissal() -> None:
    """Check responsive artwork, storage, reloads, and hidden-header geometry."""
    base_url = os.environ.get("XY_DOCS_BASE_URL")
    if base_url is None:
        pytest.skip("XY_DOCS_BASE_URL is only set for the production-DOM check")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        context.add_init_script(
            """if (!localStorage.getItem('reflex_announcement_dismissed_release')) {
                localStorage.setItem('reflex_announcement_dismissed_release', 'xy-in-reflex-build-v1');
            }"""
        )
        page = context.new_page()
        for width in (1440, 1280, 1279, 960, 390, 320):
            page.set_viewport_size({"width": width, "height": 900})
            page.goto(base_url, wait_until="networkidle")
            banner = page.locator("[data-announcement]")
            expect(banner).to_be_visible()
            expect(banner.locator(".docs-announcement-glass > span")).to_have_count(5)
            link = banner.locator("a")
            expect(link).to_have_accessible_name(
                "New: Build vs. Buy for Internal Software — Read more (opens in a new tab)"
            )
            expect(link).to_have_attribute(
                "href", "https://reflex.dev/blog/build-vs-buy-internal-software/"
            )
            expect(link).to_have_attribute("target", "_blank")
            assert {"noopener", "noreferrer"} <= set((link.get_attribute("rel") or "").split())
            assert page.locator(".docs-nav-frame").bounding_box()["height"] == (
                108 if width > 960 else 104
            )
            message = banner.locator(".announcement-shimmer").bounding_box()
            assert 0 <= message["x"] < message["x"] + message["width"] <= width
            cta = banner.get_by_text("Read more", exact=True)
            assert cta.is_visible() == (width > 640)
            assert not banner.locator("a svg").is_visible()
            header = page.locator(".docs-navbar-header")
            expect(header).to_have_css("border-top-left-radius", "24px")
            expect(header).to_have_css("border-top-right-radius", "24px")
            if width < 1280:
                menu = page.locator(".docs-navbar-menu > summary")
                menu.click()
                expect(header).to_have_css("border-top-left-radius", "0px")
                expect(header).to_have_css("border-top-right-radius", "0px")
                menu.click()
                expect(header).to_have_css("border-top-left-radius", "24px")
                expect(header).to_have_css("border-top-right-radius", "24px")
            for color_mode in ("light", "dark"):
                page.emulate_media(color_scheme=color_mode, reduced_motion="reduce")
                assert banner.evaluate("el => getComputedStyle(el).color") == "rgb(0, 0, 0)"
                assert (
                    banner.locator(".docs-announcement-glass").evaluate(
                        "el => getComputedStyle(el).animationName"
                    )
                    == "none"
                )

        # A second open tab receives marketing's same-origin storage event.
        other = context.new_page()
        other.goto(base_url, wait_until="networkidle")
        page.get_by_role("button", name="Dismiss announcement").click()
        for current in (page, other):
            expect(current.locator("[data-announcement]")).to_be_hidden()
            expect(current.locator(".docs-nav-frame")).to_have_css("height", "64px")
        assert (
            page.evaluate("localStorage.getItem('reflex_announcement_dismissed_release')")
            == ANNOUNCEMENT_RELEASE
        )
        page.reload(wait_until="networkidle")
        expect(page.locator("[data-announcement]")).to_be_hidden()
        expect(page.locator(".docs-nav-frame")).to_have_css("height", "64px")
        context.close()

        blocked = browser.new_context()
        blocked.add_init_script(
            "Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked')}})"
        )
        page = blocked.new_page()
        page.goto(base_url, wait_until="networkidle")
        expect(page.locator("[data-announcement]")).to_be_visible()
        page.get_by_role("button", name="Dismiss announcement").click()
        expect(page.locator("[data-announcement]")).to_be_hidden()
        expect(page.locator(".docs-nav-frame")).to_have_css("height", "64px")
        browser.close()
