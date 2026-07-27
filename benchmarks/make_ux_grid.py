#!/usr/bin/env python3
"""Assemble screencast frames from bench_ux --record into one synced grid video.

Every arm's frames carry an offset in milliseconds from *its own* navigation,
so replaying them against one shared clock puts all five on the same timeline:
at video time T, every panel shows what that library had on screen T ms after
its page started loading.  A panel holds its last frame once its recording
ends, and shows black before its first frame.

    python benchmarks/make_ux_grid.py ux-rec-video --out ux-grid.mp4

Each panel is labeled with its arm and a live elapsed-time readout, so the
video can be checked frame-by-frame against the JSON's timings.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FRAME_RE = re.compile(r"^(\d+)_(\d+)\.jpg$")


def load_arm(directory: Path) -> list[tuple[int, Path]]:
    """[(offset_ms, path)] sorted by capture order."""
    frames = []
    for path in sorted(directory.iterdir()):
        match = FRAME_RE.match(path.name)
        if match:
            frames.append((int(match.group(2)), path))
    return sorted(frames, key=lambda item: item[0])


def font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video_dir", type=Path)
    parser.add_argument("--out", type=Path, default=Path("ux-grid.mp4"))
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--cell-width", type=int, default=640)
    parser.add_argument("--cols", type=int, default=3)
    parser.add_argument(
        "--slowdown",
        type=float,
        default=2.0,
        help="wall-clock seconds per second of real time (2 = half speed)",
    )
    args = parser.parse_args()

    arms = sorted(d for d in args.video_dir.iterdir() if d.is_dir())
    if not arms:
        parser.error(f"no arm directories under {args.video_dir}")
    tracks = {d.name: load_arm(d) for d in arms}
    tracks = {name: frames for name, frames in tracks.items() if frames}

    probe = Image.open(next(iter(tracks.values()))[0][1])
    scale = args.cell_width / probe.width
    cell = (args.cell_width, int(probe.height * scale))
    label_h = 34
    cols = min(args.cols, len(tracks))
    rows = (len(tracks) + cols - 1) // cols
    canvas_size = (cols * cell[0], rows * (cell[1] + label_h))

    span_ms = max(frames[-1][0] for frames in tracks.values())
    step_ms = 1000.0 / args.fps / args.slowdown
    total = int(span_ms / step_ms) + 1

    title_font, time_font = font(20), font(17)
    staging = args.out.parent / (args.out.stem + "-frames")
    staging.mkdir(parents=True, exist_ok=True)
    for old in staging.glob("*.png"):
        old.unlink()

    cursors = dict.fromkeys(tracks, 0)
    cache: dict[str, Image.Image] = {}
    for index in range(total):
        now_ms = index * step_ms
        canvas = Image.new("RGB", canvas_size, (16, 16, 18))
        draw = ImageDraw.Draw(canvas)
        for slot, (name, frames) in enumerate(sorted(tracks.items())):
            # Advance to the newest frame whose timestamp has arrived: this is
            # what the page had on screen at now_ms.
            while cursors[name] + 1 < len(frames) and frames[cursors[name] + 1][0] <= now_ms:
                cursors[name] += 1
            started = frames[cursors[name]][0] <= now_ms
            col, row = slot % cols, slot // cols
            x0, y0 = col * cell[0], row * (cell[1] + label_h)
            if started:
                path = frames[cursors[name]][1]
                key = str(path)
                if key not in cache:
                    cache.clear()
                    cache[key] = Image.open(path).convert("RGB").resize(cell)
                canvas.paste(cache[key], (x0, y0 + label_h))
            label = name.rsplit("-", 1)[0]
            draw.rectangle([x0, y0, x0 + cell[0], y0 + label_h], fill=(28, 28, 32))
            draw.text((x0 + 10, y0 + 7), label, font=title_font, fill=(235, 235, 240))
            draw.text(
                (x0 + cell[0] - 96, y0 + 8),
                f"{now_ms / 1000:6.2f}s",
                font=time_font,
                fill=(150, 200, 255),
            )
        canvas.save(staging / f"{index:05d}.png")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(args.fps),
            "-i",
            str(staging / "%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            str(args.out),
        ],
        check=True,
        capture_output=True,
    )
    print(f"{args.out}  ({total} frames, {span_ms / 1000:.2f}s real, {args.slowdown}x slower)")


if __name__ == "__main__":
    main()
