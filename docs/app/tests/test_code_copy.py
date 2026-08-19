"""Accessibility contracts for documentation code-copy controls."""

import os
import re
from urllib.parse import urljoin

import pytest
from xy_docs.code import code_block, code_copy_feedback_script

_COPY_BUTTON_SELECTOR = (
    'button[data-xy-code-copy="true"]:visible, button:has(svg.lucide-copy):visible'
)
_PRODUCTION_DOCS_URL_ENV = "XY_DOCS_BASE_URL"


def test_xy_code_blocks_name_copy_actions_and_announce_success() -> None:
    """Keep each icon-only code-copy control named, operable, and stateful."""
    rendered = str(code_block("print('hello')", "python"))
    feedback = code_copy_feedback_script()

    assert '"aria-label":' in rendered
    assert 'type:"button"' in rendered
    assert "Copy code" in rendered
    assert "data-xy-code-copy" in rendered
    assert '"data-xy-code-copy-control":"true"' in rendered
    assert '"data-xy-code-copy-implementation":"delegated"' in rendered
    assert '"data-xy-code-copy-state":"idle"' in rendered
    assert '"data-xy-code-copy-text":"print(\'hello\')"' in rendered
    assert '"data-xy-code-copy-status":"true"' in rendered
    assert rendered.count('"aria-live":"polite"') == 1
    button_and_status = rendered.split('jsx("button"', maxsplit=1)[1]
    button, status_region = button_and_status.split('jsx("span"', maxsplit=1)
    assert '"aria-live"' not in button
    assert '"aria-live":"polite"' in status_region
    assert '"aria-atomic":"true"' in status_region
    assert 'className:"sr-only"' in status_region
    assert 'className:"absolute right-1 top-1"' in rendered
    assert "focus-visible:ring-2" in rendered
    assert "group-data-[copy-state=copied]" not in rendered
    assert 'data-xy-code-copy-state=\\"copied\\"' in rendered
    assert "window.__xyCodeCopyFeedbackInstalled" in feedback
    assert "const resetTimers = new WeakMap();" in feedback
    assert "const copyAttempts = new WeakMap();" in feedback
    assert 'document.addEventListener("click", (event) => {' in feedback
    assert "button instanceof HTMLButtonElement" in feedback
    assert "navigator.clipboard?.writeText?.(" in feedback
    assert "button.dataset.xyCodeCopyText ??" in feedback
    assert "if (!write) {" in feedback
    assert "} catch {" in feedback
    assert 'settleCopy(button, attempt, "failed", "Copy failed");' in feedback
    assert "Promise.resolve(write).then(" in feedback
    assert '() => settleCopy(button, attempt, "copied", "Copied"),' in feedback
    assert '() => settleCopy(button, attempt, "failed", "Copy failed"),' in feedback
    assert feedback.count("window.setTimeout") == 1
    assert 'renderCopyStatus(button, "idle", "Copy code", "");' in feedback


def test_xy_docs_install_copy_feedback_on_mount() -> None:
    """Install one delegated copy handler alongside the existing TOC script."""
    from xy_docs.xy_docs import _DOCS_ROUTES

    root_route = next(route for route in _DOCS_ROUTES if route.path == "/")
    on_mount = root_route.component().event_triggers["on_mount"]

    assert len(on_mount.events) == 2
    rendered = str(on_mount)
    assert "setupTableOfContentsHighlight" in rendered
    assert "__xyCodeCopyFeedbackInstalled" in rendered


def test_production_copy_buttons_have_accessible_names() -> None:
    """Reject unnamed visible copy controls across every built docs route."""
    base_url = os.environ.get(_PRODUCTION_DOCS_URL_ENV)
    if base_url is None:
        pytest.skip(f"{_PRODUCTION_DOCS_URL_ENV} is only set for the production-DOM check")

    from playwright.sync_api import sync_playwright
    from xy_docs.xy_docs import _DOCS_ROUTES

    unnamed_controls: list[str] = []
    audited_controls = 0
    named_button_pattern = re.compile(r"\S")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        for route in _DOCS_ROUTES:
            route_url = urljoin(
                f"{base_url.rstrip('/')}/",
                route.path.lstrip("/"),
            )
            static_response = context.request.get(route_url)
            assert static_response.ok, (
                f"Production docs route returned {static_response.status}: {route_url}"
            )
            static_html = static_response.text()
            if "data-xy-code-copy-control" not in static_html and "lucide-copy" not in static_html:
                continue

            navigation = page.goto(route_url, wait_until="domcontentloaded")
            assert navigation is not None and navigation.ok, (
                f"Browser could not load production docs route: {route_url}"
            )

            copy_buttons = page.locator(_COPY_BUTTON_SELECTOR)
            for index in range(copy_buttons.count()):
                button = copy_buttons.nth(index)
                audited_controls += 1
                named_button = button.and_(page.get_by_role("button", name=named_button_pattern))
                if named_button.count() == 0:
                    unnamed_controls.append(
                        f"{route.path} button {index + 1}: {button.aria_snapshot()}"
                    )

        browser.close()

    assert audited_controls > 0, "Production docs exposed no visible code-copy controls"
    assert not unnamed_controls, "Unnamed visible code-copy controls:\n" + "\n".join(
        unnamed_controls
    )


def test_production_copy_button_stays_icon_only() -> None:
    """Reject shared code-block styles that inject a visible Copy label."""
    base_url = os.environ.get(_PRODUCTION_DOCS_URL_ENV)
    if base_url is None:
        pytest.skip(f"{_PRODUCTION_DOCS_URL_ENV} is only set for the production-DOM check")

    from playwright.sync_api import expect, sync_playwright

    route_url = urljoin(
        f"{base_url.rstrip('/')}/",
        "overview/first-chart/",
    )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        navigation = page.goto(route_url, wait_until="domcontentloaded")
        assert navigation is not None and navigation.ok, (
            f"Browser could not load production docs route: {route_url}"
        )

        button = page.locator('button[data-xy-code-copy="true"]:visible').first
        expect(button).to_be_visible()
        assert button.evaluate("element => getComputedStyle(element, '::after').content") in {
            "none",
            "normal",
            '""',
        }
        expect(button.locator('[data-xy-code-copy-icon="copy"]')).to_be_visible()

        browser.close()
