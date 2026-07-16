"""Official-style footer configuration for the XY documentation site."""

import reflex as rx
from reflex_site_shared.docs import DocsPage, docs_external_page_footer

REPOSITORY_URL = "https://github.com/reflex-dev/xy"


def xy_docs_footer(page: DocsPage) -> rx.Component:
    """Render the official documentation footer for an XY source page.

    Args:
        page: Current discovered XY documentation page.

    Returns:
        Shared official footer with XY issue and edit destinations.
    """
    public_path = f"/docs/xy{page.route}"
    return docs_external_page_footer(
        issue_href=(
            f"{REPOSITORY_URL}/issues/new"
            "?template=documentation.md"
            "&labels=documentation"
            f"&title=Issue with reflex.dev{public_path}"
            f"&body=Path: {public_path}%0A%0A"
        ),
        edit_href=(f"{REPOSITORY_URL}/blob/main/docs/{page.relative_path.as_posix()}"),
    )


__all__ = ["xy_docs_footer"]
