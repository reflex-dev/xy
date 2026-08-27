import reflex as rx

import reflex_xy

config = rx.Config(
    app_name="xy_bond_intro",
    plugins=[
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="dark", accent_color="crimson", gray_color="slate"),
        ),
        rx.plugins.SitemapPlugin(),
        # The whole adapter wiring: chart data rides the app's own websocket as
        # a second socket.io namespace of binary columns.
        reflex_xy.XYPlugin(),
    ],
)
