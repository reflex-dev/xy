"""Documentation navigation and page metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class DocPage:
    """A Markdown page exposed by the documentation app."""

    title: str
    source: str
    description: str

    @property
    def path(self) -> Path:
        """Return the absolute source path."""
        return DOCS_ROOT / self.source

    @property
    def route(self) -> str:
        """Return the public route for the page."""
        source_path = Path(self.source)
        if source_path.stem == "index":
            return "/"
        route = source_path.with_suffix("").as_posix().replace("_", "-")
        return f"/{route}/"


@dataclass(frozen=True, slots=True)
class NavSection:
    """A named group of documentation pages."""

    title: str
    icon: str
    pages: tuple[DocPage, ...]


@dataclass(frozen=True, slots=True)
class NavArea:
    """A top-level documentation area in the Reflex-style sidebar."""

    title: str
    icon: str
    sections: tuple[NavSection, ...]


SECTIONS = (
    NavSection(
        title="Get started",
        icon="rocket",
        pages=(
            DocPage(
                "Overview",
                "index.md",
                "Install xy and build your first screen-bounded interactive chart.",
            ),
            DocPage(
                "API examples",
                "api-examples.md",
                "Copyable examples for every major chart family and composition API.",
            ),
            DocPage(
                "Styling",
                "styling.md",
                "Theme chart chrome and marks with CSS, tokens, and chart props.",
            ),
        ),
    ),
    NavSection(
        title="Matplotlib",
        icon="chart-no-axes-combined",
        pages=(
            DocPage(
                "Compatibility",
                "matplotlib-compat.md",
                "Use xy.pyplot as a fast, focused replacement for 2D Matplotlib workflows.",
            ),
            DocPage(
                "Compatibility matrix",
                "matplotlib-compat-matrix.md",
                "Method-by-method coverage for the supported pyplot surface.",
            ),
            DocPage(
                "Compatibility changelog",
                "matplotlib-compat-changelog.md",
                "Reviewed compatibility and visual-parity changes.",
            ),
            DocPage(
                "Shim audit",
                "matplotlib-shim-todo.md",
                "The completion record and remaining compatibility boundaries.",
            ),
        ),
    ),
    NavSection(
        title="Performance",
        icon="gauge",
        pages=(
            DocPage(
                "Benchmarks",
                "benchmark.md",
                "Reproducible comparisons across rendering, transport, and interaction.",
            ),
            DocPage(
                "Benchmark metrics",
                "benchmark_metrics.md",
                "The latest generated benchmark measurements and regression signals.",
            ),
            DocPage(
                "Benchmark methodology",
                "design/benchmark-methodology.md",
                "Definitions, scenarios, and disclosure rules behind xy performance claims.",
            ),
        ),
    ),
    NavSection(
        title="Architecture",
        icon="blocks",
        pages=(
            DocPage(
                "Design dossier",
                "design-dossier.md",
                "The complete design rationale for xy's screen-bounded charting engine.",
            ),
            DocPage(
                "Chart grammar",
                "design/chart-grammar.md",
                "The declarative model for chart composition, layering, and channels.",
            ),
            DocPage(
                "Renderer",
                "design/renderer-architecture.md",
                "WebGL renderer boundaries, audit findings, and the WebGPU path.",
            ),
            DocPage(
                "Level of detail",
                "design/lod-architecture.md",
                "The tiered drilldown architecture for exact, stable large-data rendering.",
            ),
            DocPage(
                "Rust engine",
                "design/rust-engine.md",
                "Native engine module boundaries and the evolving FFI protocol.",
            ),
            DocPage(
                "Reflex-shaped API",
                "design/reflex-shaped-api.md",
                "A composable API shaped by Reflex without a hard Reflex dependency.",
            ),
            DocPage(
                "Reflex integration",
                "design/reflex-integration.md",
                "The transport and adapter design for using xy in Reflex applications.",
            ),
        ),
    ),
    NavSection(
        title="Project",
        icon="folder-kanban",
        pages=(
            DocPage(
                "Contributing",
                "contributing.md",
                "Set up the project, run the checks, and prepare a focused pull request.",
            ),
            DocPage(
                "Production readiness",
                "production-readiness.md",
                "Release gates, supported contracts, and the hardening backlog.",
            ),
            DocPage(
                "Chart roadmap",
                "chart-roadmap.md",
                "Prioritized chart coverage and cross-cutting rendering work.",
            ),
            DocPage(
                "Chart-kind contract",
                "chart-kind-contract.md",
                "The kernel and client seams for adding a chart kind safely.",
            ),
            DocPage(
                "Security audit",
                "security-audit-2026-07-06.md",
                "Resolved findings, verified controls, and remaining security work.",
            ),
        ),
    ),
)

AREAS = (
    NavArea("Learn", "graduation-cap", SECTIONS[:2]),
    NavArea("Performance", "gauge", (SECTIONS[2],)),
    NavArea("Architecture", "blocks", (SECTIONS[3],)),
    NavArea("Project", "folder-kanban", (SECTIONS[4],)),
)

PAGES = tuple(page for area in AREAS for section in area.sections for page in section.pages)


def area_for_page(page: DocPage) -> NavArea:
    """Return the top-level sidebar area containing a page."""
    return next(area for area in AREAS if any(page in section.pages for section in area.sections))


def page_index(page: DocPage) -> int:
    """Return a page's position in the flattened navigation."""
    return PAGES.index(page)


def adjacent_pages(page: DocPage) -> tuple[DocPage | None, DocPage | None]:
    """Return the previous and next pages in navigation order."""
    index = page_index(page)
    previous = PAGES[index - 1] if index else None
    following = PAGES[index + 1] if index + 1 < len(PAGES) else None
    return previous, following
