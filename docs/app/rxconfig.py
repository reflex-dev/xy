"""Reflex configuration for the XY documentation site."""

import reflex as rx
import reflex_xy
from reflex_site_shared.plugins import SharedSiteStylesPlugin
from xy_docs.config import DOCS_CONFIG
from xy_docs.prerender import XyDocsMarkdownPlugin

config = rx.Config(
    app_name="xy_docs",
    frontend_path="/docs/xy",
    frontend_packages=[
        "tailwindcss-animated@2.0.0",
        "tailwindcss-scroll-mask@0.0.3",
        "es-toolkit@1.46.1",
        "@fontsource-variable/instrument-sans@5.2.8",
        "@fontsource-variable/jetbrains-mono@5.2.8",
    ],
    telemetry_enabled=False,
    plugins=[
        rx.plugins.TailwindV4Plugin(),
        SharedSiteStylesPlugin(),
        rx.plugins.RadixThemesPlugin(),
        rx.plugins.SitemapPlugin(trailing_slash="always"),
        XyDocsMarkdownPlugin(docs=DOCS_CONFIG),
        reflex_xy.XYPlugin(),
    ],
)
