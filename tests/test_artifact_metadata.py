from email.parser import Parser

from scripts.artifact_metadata import dependency_metadata_errors


def _metadata(reflex_requirement: str) -> object:
    return Parser().parsestr(
        "\n".join(
            [
                "Requires-Dist: anywidget>=0.9",
                "Requires-Dist: numpy>=1.24",
                f"Requires-Dist: {reflex_requirement}",
                "Provides-Extra: reflex",
                "",
            ]
        )
    )


def test_bounded_reflex_metadata_is_accepted() -> None:
    assert dependency_metadata_errors(_metadata('reflex<0.10,>=0.9.6; extra == "reflex"')) == []


def test_unbounded_reflex_metadata_is_rejected() -> None:
    errors = dependency_metadata_errors(_metadata('reflex>=0.9.6; extra == "reflex"'))

    assert any("reflex<0.10,>=0.9.6" in error for error in errors)
