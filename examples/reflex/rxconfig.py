import reflex as rx
from reflex_base.plugins.sitemap import SitemapPlugin

config = rx.Config(
    app_name="reflex_xy_app",
    plugins=[
        SitemapPlugin(),
        rx.plugins.RadixThemesPlugin(),
    ],
)
