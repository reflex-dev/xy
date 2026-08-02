import reflex as rx

import reflex_xy

config = rx.Config(
    app_name="xy_reflex_demo",
    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                color_mode="dark",
                accent_color="amber",
                gray_color="olive",
                panel_background="solid",
                radius="none",
            )
        ),
        rx.plugins.SitemapPlugin(),
        reflex_xy.XYPlugin(),
    ],
)
