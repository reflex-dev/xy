import reflex as rx
import reflex_xy

config = rx.Config(
    app_name="demo_app",
    plugins=[reflex_xy.XYPlugin()],
)
