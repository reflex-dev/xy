import reflex as rx
import reflex_xy

config = rx.Config(
    app_name="xy_reflex_demo",
    plugins=[
        rx.plugins.SitemapPlugin(),
        reflex_xy.XYPlugin(),
    ],
)
