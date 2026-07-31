"""Accessibility contracts for documentation code-copy controls."""

from xy_docs.code import code_block, code_copy_feedback_script


def test_xy_code_blocks_name_copy_actions_and_announce_success() -> None:
    """Keep each icon-only code-copy control named, operable, and stateful."""
    rendered = str(code_block("print('hello')", "python"))
    feedback = code_copy_feedback_script()

    assert '"aria-label":' in rendered
    assert '"aria-live":"polite"' in rendered
    assert 'type:"button"' in rendered
    assert "Copy code" in rendered
    assert "data-xy-code-copy" in rendered
    assert "focus-visible:ring-2" in rendered
    assert "onClick:" in rendered
    assert "_call_function" in rendered
    assert '"Copied"' in rendered
    assert '"Copy failed"' in rendered
    assert 'useState("idle")' in feedback
    assert "useRef(null)" in feedback
    assert 'setCopyStatus_test("copied")' in feedback
    assert 'setCopyStatus_test("failed")' in feedback
    assert "navigator.clipboard?.writeText?.(\"print('hello')\")" in feedback
