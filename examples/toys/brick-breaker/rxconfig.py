import reflex as rx
import reflex_xy

config = rx.Config(
    app_name="brick_breaker",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="dark", accent_color="cyan"),
        ),
        reflex_xy.XYPlugin(),
    ],
)
