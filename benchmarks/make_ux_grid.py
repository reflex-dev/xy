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
import shutil
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
    parser.add_argument(
        "--report",
        type=Path,
        help="bench_ux JSON; supplies each arm's measured visible_complete_ms "
        "so its timer freezes on the number the benchmark actually recorded",
    )
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
    # libx264 with yuv420p requires even dimensions; whether the natural size
    # is even depends on the arm count and the screencast aspect ratio, so a
    # layout that encodes fine with five panels fails with three.  Round up.
    canvas_size = (
        (cols * cell[0] + 1) // 2 * 2,
        (rows * (cell[1] + label_h) + 1) // 2 * 2,
    )

    # Each panel's timer stops at that arm's render.  Prefer the measured
    # visible_complete_ms; fall back to its last captured frame, which is the
    # same moment since recording stops at visible-complete.
    finish: dict[str, float] = {name: float(frames[-1][0]) for name, frames in tracks.items()}
    # An arm that never rendered has no finish time, and a blank panel with a
    # running timer reads as "still loading" rather than "failed" — so the
    # failure is named on the panel instead.
    failed: dict[str, str] = {}
    if args.report and args.report.exists():
        import json

        for row in json.loads(args.report.read_text()).get("results", []):
            key = f"{row['arm']}-{row['n']}"
            if key not in finish:
                continue
            status = str(row.get("status", "failed"))
            # A cell can fail *after* rendering (e.g. the zoom never resolved),
            # which is a different fact from never rendering at all — the
            # panel must not conflate them.
            vc = row.get("visible_complete_ms") or (row.get("detail") or {}).get(
                "visible_complete_ms"
            )
            if status == "ok" and vc:
                finish[key] = float(vc)
            elif vc:
                finish[key] = float(vc)
                failed[key] = status.replace("_", " ")
            else:
                finish[key] = float("inf")
                failed[key] = status.replace("_", " ")

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
            is_failed = name in failed
            done = not is_failed and now_ms >= finish[name]
            # Stopwatch semantics: the timer runs while the chart is loading,
            # freezes green on the render time once it is up, and turns red
            # naming the failure if the chart never rendered at all.
            if is_failed and finish[name] == float("inf"):
                header, colour = (46, 24, 26), (255, 120, 120)
                readout = "NEVER RENDERED"
            elif is_failed:
                # It drew, then failed later: keep its render time visible in
                # amber so the load result is not thrown away with the run.
                header, colour = (48, 38, 20), (240, 190, 90)
                readout = f"{finish[name] / 1000:6.3f}s"
            elif done:
                header, colour = (24, 42, 30), (86, 222, 132)
                readout = f"{finish[name] / 1000:6.3f}s"
            else:
                header, colour = (28, 28, 32), (150, 200, 255)
                readout = f"{now_ms / 1000:6.3f}s"
            draw.rectangle([x0, y0, x0 + cell[0], y0 + label_h], fill=header)
            draw.text((x0 + 10, y0 + 7), label, font=title_font, fill=(235, 235, 240))
            anchor_x = x0 + cell[0] - (176 if readout[0].isalpha() else 116)
            draw.text((anchor_x, y0 + 8), readout, font=time_font, fill=colour)
            if is_failed and now_ms >= min(finish[name], span_ms * 0.35):
                # Say why, centred on the panel it applies to.
                msg = failed[name]
                box = draw.textbbox((0, 0), msg, font=title_font)
                draw.text(
                    (
                        x0 + (cell[0] - (box[2] - box[0])) // 2,
                        y0 + label_h + cell[1] // 2 - 12,
                    ),
                    msg,
                    font=title_font,
                    fill=(226, 108, 108) if finish[name] == float("inf") else (226, 176, 84),
                )
        canvas.save(staging / f"{index:05d}.png")

    if shutil.which("ffmpeg") is None:
        # The frames are already on disk and are the expensive part; say so
        # rather than surfacing a bare FileNotFoundError from subprocess.
        print(
            f"ffmpeg not found: staged frames left in {staging}. "
            f"Install ffmpeg and rerun to assemble {args.out}."
        )
        raise SystemExit(2)
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
