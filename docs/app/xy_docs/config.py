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
            ("Examples", "/styling/examples/"),
            ("Customize Each Part", "/styling/customize/"),
            ("Themes and Export", "/styling/themes-and-tokens/"),
            ("Advanced Styling Gallery", "/styling/gallery/"),
        ),
    ),
    (
        "Chart Gallery",
        "/overview/gallery/",
        "chart-column",
        (
            ("Line and Area", "/charts/line-and-area/"),
            ("Scatter", "/charts/scatter/"),
            ("Bar and Column", "/charts/bar-and-column/"),
            ("Distributions", "/charts/distributions/"),
            ("Density and Grids", "/charts/density-and-grids/"),
            ("Uncertainty", "/charts/uncertainty/"),
            ("Specialized", "/charts/specialized/"),
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
            (
                "DataFrames and Real Data",
                "/guides/dataframes-and-real-data/",
            ),
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
            ("Deployment Recipes", "/guides/deployment-recipes/"),
            ("Troubleshooting", "/guides/troubleshooting/"),
            ("Getting Help", "/guides/getting-help/"),
        ),
    ),
    (
        "Advanced",
        "/advanced/",
        "network",
        (
            ("XY Architecture", "/advanced/"),
            (
                "Runtime and Deployment",
                "/advanced/runtime-and-deployment/",
            ),
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

DOCS_REDIRECTS = {
    "/charts/annotations/": "/components/annotations/",
    "/styling/playground/": "/styling/examples/#palette-playground",
    "/styling/recipes/": "/styling/examples/#responsive-combo-chart",
    "/styling/chrome-slots/": "/styling/customize/#legend",
    "/styling/mark-styles/": "/styling/customize/#fill,-stroke,-opacity,-and-gradients",
    "/styling/component-variations/": "/styling/customize/#annotations",
}

_SECTION_ROUTES = tuple(
    dict.fromkeys(
        route
        for _title, landing_route, _icon, leaves in DOCS_SECTIONS
        for route in (
            landing_route,
            *(leaf_route for _leaf_title, leaf_route in leaves),
        )
    )
)

# The pager is an adoption path, not just a serialization of the sidebar.
# Move readers from installation to a first chart and then directly into a
# real-data workflow. Benchmark methodology stays available in Overview but is
# deferred until after the task-oriented documentation.
_ONBOARDING_ROUTES = (
    "/",
    "/overview/installation/",
    "/overview/first-chart/",
    "/guides/dataframes-and-real-data/",
)
_DEFERRED_ROUTES = ("/overview/benchmarks/",)
DOCS_NAVIGATION = tuple(
    dict.fromkeys(
        (
            *_ONBOARDING_ROUTES,
            *(
                route
                for route in _SECTION_ROUTES
                if route not in {*_ONBOARDING_ROUTES, *_DEFERRED_ROUTES}
            ),
            *_DEFERRED_ROUTES,
        )
    )
)

DOCS_CONFIG = DocsSiteConfig(
    content_dir=DOCS_ROOT,
    exclude=(
        "app/**",
        "assets/**",
        "engineering/**",
        "styling/chrome-slots.md",
        "styling/component-variations.md",
        "styling/mark-styles.md",
        "styling/playground.md",
        "styling/recipes.md",
    ),
    navigation_order=DOCS_NAVIGATION,
    sitemap_base_url=PUBLIC_DOCS_URL,
)

__all__ = [
    "DOCS_CONFIG",
    "DOCS_NAVIGATION",
    "DOCS_REDIRECTS",
    "DOCS_ROOT",
    "DOCS_SECTIONS",
]
