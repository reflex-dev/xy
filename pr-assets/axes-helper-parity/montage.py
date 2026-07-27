from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    panels = [Image.open(path).convert("RGB") for path in (args.reference, args.before, args.after)]
    width = 720
    panels = [
        panel.resize(
            (width, round(panel.height * width / panel.width)),
            Image.Resampling.LANCZOS,
        )
        for panel in panels
    ]
    panel_height = max(panel.height for panel in panels)
    header = 64
    gap = 18
    canvas = Image.new(
        "RGB",
        (width * len(panels) + gap * (len(panels) - 1), panel_height + header),
        "white",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=22)
    labels = ("Matplotlib 3.11 reference", "XY before", "XY after")
    for index, (panel, label) in enumerate(zip(panels, labels, strict=True)):
        left = index * (width + gap)
        bbox = draw.textbbox((0, 0), label, font=font)
        draw.text(
            (left + (width - (bbox[2] - bbox[0])) / 2, 20),
            label,
            fill="#111827",
            font=font,
        )
        canvas.paste(panel, (left, header))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.output, optimize=True)


if __name__ == "__main__":
    main()
