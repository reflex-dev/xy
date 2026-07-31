"""Accessibility contracts for documentation code-copy controls."""

from xy_docs.code import code_block, code_copy_feedback_script


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
