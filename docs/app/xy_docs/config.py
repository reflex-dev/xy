"""Central documentation content and navigation configuration."""

from pathlib import Path

from reflex_site_shared.docs import DocsSiteConfig

from xy_docs.constants import PUBLIC_DOCS_URL

DOCS_ROOT = Path(__file__).resolve().parents[2]

DOCS_SECTIONS = (
    (
        "Overview",
        "/",
        "compass",
        (
            ("What is xy?", "/"),
            ("Gallery", "/overview/gallery/"),
            ("Installation", "/overview/installation/"),
            ("Your First Chart", "/overview/first-chart/"),
            ("Benchmarks", "/overview/benchmarks/"),
        ),
    ),
    (
        "Core Concepts",
        "/core-concepts/",
        "boxes",
        (
            ("Composition Model", "/core-concepts/"),
            ("Data and Columns", "/core-concepts/data/"),
            ("Axes and Scales", "/core-concepts/axes-and-scales/"),
            ("Interactions and Selections", "/core-concepts/interactions/"),
            (
                "Large Data and Performance",
                "/core-concepts/large-data-and-performance/",
            ),
            ("Configuration", "/core-concepts/configuration/"),
        ),
    ),
    (
        "Styling",
        "/styling/",
        "palette",
        (
            ("Overview", "/styling/"),
            ("Styling Gallery", "/styling/gallery/"),
            ("Chrome Slots", "/styling/chrome-slots/"),
            ("Component Variations", "/styling/component-variations/"),
            ("Mark Styles", "/styling/mark-styles/"),
            ("Themes and Tokens", "/styling/themes-and-tokens/"),
            ("Recipes", "/styling/recipes/"),
        ),
    ),
    (
        "Chart Gallery",
        "/charts/",
        "chart-column",
        (
            ("Line and Area", "/charts/line-and-area/"),
            ("Scatter", "/charts/scatter/"),
            ("Bar and Column", "/charts/bar-and-column/"),
            ("Distributions", "/charts/distributions/"),
            ("Density and Grids", "/charts/density-and-grids/"),
            ("Uncertainty", "/charts/uncertainty/"),
            ("Specialized", "/charts/specialized/"),
            ("Annotations", "/charts/annotations/"),
            ("Facets and Layers", "/charts/facets-and-layers/"),
        ),
    ),
    (
        "Components",
        "/components/",
        "layout-panel-left",
        (
            ("Marks", "/components/marks/"),
            ("Axes", "/components/axes/"),
            ("Legends", "/components/legends/"),
            ("Tooltips", "/components/tooltips/"),
            ("Colorbars", "/components/colorbars/"),
            (
                "Modebars & Controls",
                "/components/modebars-and-interaction-controls/",
            ),
            ("Annotations", "/components/annotations/"),
        ),
    ),
    (
        "Integrations",
        "/integrations/",
        "plug",
        (
            ("Reflex", "/integrations/reflex/"),
            ("Notebooks", "/integrations/notebooks/"),
            ("Matplotlib (xy.pyplot)", "/integrations/matplotlib/"),
        ),
    ),
    (
        "Guides",
        "/guides/",
        "book-open",
        (
            ("Display and Export", "/guides/display-and-export/"),
            (
                "Real-time and Streaming Data",
                "/guides/real-time-and-streaming-data/",
            ),
            (
                "Dashboards and Linked Views",
                "/guides/dashboards-and-linked-views/",
            ),
            (
                "Serving, CSP, and Offline Use",
                "/guides/serving-csp-and-offline-use/",
            ),
            ("Troubleshooting", "/guides/troubleshooting/"),
        ),
    ),
    (
        "Reference",
        "/api-reference/",
        "book-text",
        (
            ("Chart Factories", "/api-reference/chart-factories/"),
            ("Marks and Components", "/api-reference/marks-and-components/"),
            ("Figure Methods", "/api-reference/figure-methods/"),
            ("Events and Callbacks", "/api-reference/events-and-callbacks/"),
            ("Public Types", "/api-reference/public-types/"),
            (
                "Limitations and Alpha Status",
                "/api-reference/limitations-and-alpha-status/",
            ),
            ("Changelog", "/api-reference/changelog/"),
            ("Contributing", "/api-reference/contributing/"),
        ),
    ),
)

DOCS_NAVIGATION = tuple(
    dict.fromkeys(
        route
        for _title, landing_route, _icon, leaves in DOCS_SECTIONS
        for route in (
            landing_route,
            *(leaf_route for _leaf_title, leaf_route in leaves),
        )
    )
)

DOCS_CONFIG = DocsSiteConfig(
    content_dir=DOCS_ROOT,
    exclude=(
        "app/**",
        "assets/**",
        "engineering/**",
    ),
    navigation_order=DOCS_NAVIGATION,
    sitemap_base_url=PUBLIC_DOCS_URL,
)

__all__ = ["DOCS_CONFIG", "DOCS_NAVIGATION", "DOCS_ROOT", "DOCS_SECTIONS"]
