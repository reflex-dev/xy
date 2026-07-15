import reflex as rx

config = rx.Config(
    app_name="xy_docs",
    default_color_mode="system",
    frontend_packages=[
        "tailwindcss-animated@2.0.0",
        "tailwindcss-scroll-mask@0.0.3",
    ],
    plugins=[
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(
                appearance="inherit",
                accent_color="violet",
                gray_color="slate",
                radius="large",
            )
        ),
        rx.plugins.SitemapPlugin(trailing_slash="always"),
    ],
    telemetry_enabled=False,
)
