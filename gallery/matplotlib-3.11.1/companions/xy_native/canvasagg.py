"""Create and inspect a raster with XY's dependency-free native renderer.

XY-native companion for Matplotlib 3.11.0's
``user_interfaces/canvasagg.py``. This is an explicit API port, not a
``xy.pyplot`` import-swap example.

Upstream source SHA-256:
0770bf0383005e449ea16950307d7bf955fd019f83ef7e15a3633e30c7aef2cb
Matplotlib's license is retained at ``../../LICENSE``.

The upstream example constructs ``FigureCanvasAgg`` directly. XY exposes its
native rasterizer through ``Chart.to_png``; it uses the Rust renderer and does
not invoke Agg, another Matplotlib renderer, or a browser.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

from PIL import Image

import xy


def build_chart() -> xy.Chart:
    return xy.line_chart(
        xy.line(x=[0, 1, 2], y=[1, 2, 3]),
        width=500,
        height=400,
    )


def render_native() -> tuple[bytes, Image.Image]:
    """Return the native PNG bytes and their decoded RGBA image."""

    png = build_chart().to_png(
        width=500,
        height=400,
        scale=1,
        engine=xy.Engine.default,
    )
    with Image.open(BytesIO(png)) as decoded:
        rgba = decoded.convert("RGBA")
    return png, rgba


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--png", type=Path, default=Path("xy_canvas.png"))
    parser.add_argument("--bmp", type=Path, default=Path("xy_canvas.bmp"))
    args = parser.parse_args(argv)

    args.png.parent.mkdir(parents=True, exist_ok=True)
    args.bmp.parent.mkdir(parents=True, exist_ok=True)
    png, rgba = render_native()
    args.png.write_bytes(png)
    rgba.save(args.bmp, format="BMP")
    print(f"{args.png} {args.bmp} {rgba.width}x{rgba.height} RGBA")


if __name__ == "__main__":
    main()
