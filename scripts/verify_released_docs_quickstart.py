"""Run the public docs quickstarts against an installed XY release.

This script intentionally uses only the standard library plus the ``xy`` package
under test. CI runs it in an isolated uv environment populated from PyPI, not
from this checkout.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import re
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = (REPO_ROOT / "python" / "xy").resolve()
QUICKSTART_PAGES = (("first-chart page", REPO_ROOT / "docs" / "overview" / "first-chart.md"),)
PYTHON_FENCE_RE = re.compile(
    r"^~~~python[^\n]*\n(?P<code>.*?)^~~~\s*$",
    flags=re.MULTILINE | re.DOTALL,
)
EXTERNAL_CSS_RE = re.compile(
    r"@import\s|url\(\s*['\"]?(?:https?:)?//",
    flags=re.IGNORECASE,
)


def fail(message: str) -> None:
    """Exit with a diagnostic that identifies this contract check."""
    raise SystemExit(f"Released docs quickstart contract failed: {message}")


def require(condition: bool, message: str) -> None:
    """Fail with ``message`` unless ``condition`` is true."""
    if not condition:
        fail(message)


class StandaloneHtmlProbe(HTMLParser):
    """Collect the standalone-document properties relevant to this contract."""

    def __init__(self) -> None:
        super().__init__()
        self.csp_values: list[str] = []
        self.linked_assets: list[str] = []
        self.has_chart_mount = False
        self.has_inline_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value or "" for name, value in attrs}

        if tag == "meta" and attributes.get("http-equiv", "").casefold() == (
            "content-security-policy"
        ):
            self.csp_values.append(attributes.get("content", ""))

        if tag == "div" and attributes.get("id") == "chart":
            self.has_chart_mount = True

        if tag == "script":
            source = attributes.get("src")
            if source:
                self.linked_assets.append(f"script src={source!r}")
            else:
                self.has_inline_script = True

        if tag == "link" and attributes.get("href"):
            self.linked_assets.append(f"link href={attributes['href']!r}")

        resource_attributes = {
            "audio": "src",
            "embed": "src",
            "iframe": "src",
            "img": "src",
            "object": "data",
            "source": "src",
            "video": "src",
        }
        resource_attribute = resource_attributes.get(tag)
        if resource_attribute:
            resource = attributes.get(resource_attribute)
            if resource and not resource.casefold().startswith("data:"):
                self.linked_assets.append(f"{tag} {resource_attribute}={resource!r}")

        poster = attributes.get("poster")
        if poster and not poster.casefold().startswith("data:"):
            self.linked_assets.append(f"{tag} poster={poster!r}")


def extract_quickstart(page: Path, label: str) -> str:
    """Return the single exportable XY quickstart fenced on ``page``.

    The quickstart is the beginner script that exports ``scatter.html``; other
    exportable showcase fences on the page (for example the large-data demo)
    are not part of this release contract.
    """
    text = page.read_text(encoding="utf-8")
    candidates = [
        match.group("code").strip()
        for match in PYTHON_FENCE_RE.finditer(text)
        if "xy.scatter_chart(" in match.group("code")
        and 'chart.to_html("scatter.html")' in match.group("code")
    ]
    require(
        len(candidates) == 1,
        f"expected exactly one Python quickstart exporting scatter.html in {label} "
        f"({page}), found {len(candidates)}",
    )
    return candidates[0]


def verify_release_import(xy_module: ModuleType, expected_version: str, label: str) -> None:
    """Ensure the snippet imported the requested wheel rather than this checkout."""
    module_file = getattr(xy_module, "__file__", None)
    require(module_file is not None, f"{label} imported an XY module without a filesystem path")
    imported_path = Path(module_file).resolve()
    try:
        imported_path.relative_to(SOURCE_PACKAGE)
    except ValueError:
        pass
    else:
        fail(
            f"{label} imported the checkout at {imported_path}; run this script in an "
            "isolated environment containing the published wheel"
        )

    actual_version = getattr(xy_module, "__version__", None)
    require(
        actual_version == expected_version,
        f"{label} imported xy=={actual_version!r} from {imported_path}, expected "
        f"xy=={expected_version}",
    )


def verify_standalone_html(html_path: Path, label: str) -> None:
    """Verify that the quickstart emitted a self-contained interactive document."""
    html = html_path.read_text(encoding="utf-8")
    lower_html = html.casefold()
    require(len(html) > 1_000, f"{label} generated an unexpectedly small HTML file")
    require("<!doctype html>" in lower_html, f"{label} output is not a complete HTML document")
    require("first chart" in lower_html, f"{label} output did not embed the chart title")

    probe = StandaloneHtmlProbe()
    probe.feed(html)
    require(probe.has_chart_mount, f"{label} output is missing the #chart mount element")
    require(probe.has_inline_script, f"{label} output is missing its inline chart runtime")
    require(
        not probe.linked_assets,
        f"{label} output links external assets: {', '.join(probe.linked_assets)}",
    )
    require(
        not EXTERNAL_CSS_RE.search(html),
        f"{label} output contains an external CSS import or URL",
    )

    csp = "; ".join(probe.csp_values).casefold()
    for directive in ("default-src 'none'", "connect-src 'none'", "object-src 'none'"):
        require(directive in csp, f"{label} output CSP is missing {directive!r}")


def run_quickstart(source: str, label: str, expected_version: str) -> None:
    """Execute one docs snippet and validate its exported HTML."""
    with TemporaryDirectory(prefix="xy-released-quickstart-") as temp_dir:
        output_dir = Path(temp_dir)
        namespace: dict[str, object] = {"__name__": "__main__"}
        try:
            with contextlib.chdir(output_dir):
                exec(compile(source, f"<{label} quickstart>", "exec"), namespace)
        except (AttributeError, TypeError) as exc:
            fail(f"{label} API drifted from xy=={expected_version}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            fail(f"{label} did not run on xy=={expected_version}: {type(exc).__name__}: {exc}")

        xy_module = namespace.get("xy")
        require(isinstance(xy_module, ModuleType), f"{label} did not import the xy package")
        verify_release_import(xy_module, expected_version, label)

        html_files = list(output_dir.glob("*.html"))
        require(
            len(html_files) == 1,
            f"{label} should export exactly one HTML file, found {len(html_files)}",
        )
        verify_standalone_html(html_files[0], label)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-version",
        default="0.0.1",
        help="Published xy version that must run the docs quickstarts (default: 0.0.1)",
    )
    args = parser.parse_args()

    try:
        installed_version = importlib.metadata.version("xy")
    except importlib.metadata.PackageNotFoundError:
        fail("xy is not installed; install the expected published wheel before running")
    require(
        installed_version == args.expected_version,
        f"installed distribution is xy=={installed_version}, expected xy=={args.expected_version}",
    )

    for label, page in QUICKSTART_PAGES:
        source = extract_quickstart(page, label)
        run_quickstart(source, label, args.expected_version)

    page_count = len(QUICKSTART_PAGES)
    page_label = "page" if page_count == 1 else "pages"
    print(
        f"Released docs quickstart contract passed for xy=={args.expected_version} "
        f"({page_count} {page_label})."
    )


if __name__ == "__main__":
    main()
