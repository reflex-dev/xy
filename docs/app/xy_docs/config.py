"""Central documentation content and navigation configuration."""

from pathlib import Path

from reflex_site_shared.docs import DocsSiteConfig

from xy_docs.constants import PUBLIC_DOCS_URL

DOCS_ROOT = Path(__file__).resolve().parents[2]

DOCS_NAVIGATION = (
    "/",
    "/getting-started/",
    "/core-concepts/",
    "/core-concepts/composition/",
    "/core-concepts/data/",
    "/core-concepts/axes-and-scales/",
    "/core-concepts/interactions/",
    "/core-concepts/styling/",
    "/charts/",
    "/charts/line-and-area/",
    "/charts/scatter/",
    "/charts/bar-and-column/",
    "/charts/distributions/",
    "/charts/density-and-grids/",
    "/charts/uncertainty/",
    "/charts/specialized/",
    "/charts/facets-and-layers/",
    "/components/",
    "/components/annotations/",
    "/components/chart-chrome/",
    "/guides/",
    "/guides/exporting/",
    "/guides/notebooks-and-pyplot/",
    "/guides/large-datasets/",
    "/guides/streaming-data/",
    "/guides/framework-integration/",
    "/api-reference/",
    "/api-reference/components/",
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

__all__ = ["DOCS_CONFIG", "DOCS_NAVIGATION", "DOCS_ROOT"]
