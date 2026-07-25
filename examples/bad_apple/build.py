#!/usr/bin/env python3
"""Build a self-contained "Bad Apple" animation player powered by xy.

Every frame of the source video is downsampled to a small grid, thresholded to
1 bit per cell, and the *ink* cells become points in an xy scatter. The player
drives xy's real streaming-append render path (``ChartView._applyAppend``) once
per frame, so what you see is the production WebGL2 renderer redrawing a fresh
scatter ~20 times a second — the same code path a live dashboard uses (§5/§29).

Transport is deliberately tiny: frames ship as a gzipped bit-packed mask
(one bit per grid cell), inflated in the browser via ``DecompressionStream`` and
turned back into xy payload buffers client-side. A 3.5-minute clip at 120x90 /
20 fps is a couple of MB, not tens.

The soundtrack (extracted from the same clip) is embedded and acts as the
master clock; the player offers several live "looks" (neon/ember/aurora/outline/
dots) that recolor the same points via the engine's colormaps. The derived data
lands in ``bad_apple.html`` which stays gitignored — run this to (re)generate it.

Usage:
    python build.py                      # uses ./badapple.mp4 or downloads it
    python build.py --video path.mp4     # use a local file
    python build.py --width 160 --fps 24 --invert --no-audio
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

import xy

HERE = Path(__file__).resolve().parent
DEFAULT_VIDEO = HERE / "badapple.mp4"
# Canonical "Bad Apple!! PV" upload; only touched locally to derive frames.
DEFAULT_URL = "https://www.youtube.com/watch?v=FtutLA63Cp8"
TEMPLATE = HERE / "player_template.html"
STANDALONE_JS = Path(xy.__file__).resolve().parent / "static" / "standalone.js"


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        sys.exit(f"error: `{tool}` is required but was not found on PATH")
    return path


def download_video(dest: Path, url: str) -> None:
    ytdlp = _require("yt-dlp")
    print(f"downloading {url} -> {dest}")
    subprocess.run(
        [
            ytdlp,
            # video (<=480p) + audio, merged — the audio track is the soundtrack.
            "-f",
            "bv*[height<=480]+ba/b[height<=480]/b",
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "-o",
            str(dest),
            url,
        ],
        check=True,
    )


def extract_frames(video: Path, width: int, height: int, fps: float) -> np.ndarray:
    """Return an (F, H, W) uint8 grayscale stack sampled at `fps`."""
    ffmpeg = _require("ffmpeg")
    print(f"extracting frames from {video.name} at {width}x{height}, {fps} fps")
    proc = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={fps},scale={width}:{height}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    raw = np.frombuffer(proc.stdout, dtype=np.uint8)
    frame_bytes = width * height
    n = raw.size // frame_bytes
    if n == 0:
        sys.exit("error: ffmpeg produced no frames")
    return raw[: n * frame_bytes].reshape(n, height, width)


def extract_audio(video: Path, bitrate: str) -> bytes:
    """Return the video's audio track as MP3 bytes (universally <audio>-playable)."""
    ffmpeg = _require("ffmpeg")
    print(f"extracting audio at {bitrate}")
    proc = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(video),
            "-vn",  # no video
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-f",
            "mp3",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return proc.stdout


def build_template_spec(width: int, height: int, canvas_w: int, canvas_h: int) -> dict:
    """Generate an authentic xy scatter spec to use as the per-frame template.

    The four corner points pin the axis domain (and thus the f32 offset the
    client decodes with) to the full grid, so every frame reuses one offset.
    """
    xs = np.array([0, width - 1, 0, width - 1], dtype=float)
    ys = np.array([0, 0, height - 1, height - 1], dtype=float)
    # Square edge = cell pitch (+1px overlap) so the ink tiles with no gaps.
    marker_px = max(canvas_w / width, canvas_h / height) + 1.0
    chart = xy.scatter_chart(
        # A plain scatter is the template; the player overwrites symbol, color
        # (constant or a colormap), size and background per "look" at runtime.
        xy.scatter(
            x=xs,
            y=ys,
            name="ink",
            color="#0a0a0a",
            size=marker_px,
            symbol="square",
            opacity=1.0,
            colormap="turbo",
        ),
        # No axis chrome: strategy="none" drops ticks, gridlines and the axis
        # baseline, and padding=0 makes the plot full-bleed so cells tile exactly.
        xy.x_axis(domain=(-0.5, width - 0.5), tick_label_strategy="none"),
        xy.y_axis(domain=(-0.5, height - 0.5), tick_label_strategy="none"),
        # Transparent plot so the page background (set per look) shows through.
        xy.theme(plot_background="rgba(0,0,0,0)"),
        xy.legend(show=False),
        xy.modebar(show=False),
        xy.tooltip(show=False),
        width=canvas_w,
        height=canvas_h,
        padding=0,
        title=None,
    )
    spec, _ = chart.figure().build_payload()
    return spec


def pack_frames(frames: np.ndarray, threshold: int, invert: bool) -> tuple[bytes, int]:
    """Threshold to 1 bit/cell (ink=1), bit-pack row-major, report max ink count."""
    ink = frames < threshold  # dark pixels are ink
    if invert:
        ink = ~ink
    max_ink = max(ink.reshape(ink.shape[0], -1).sum(axis=1).tolist())
    packed = np.packbits(ink.reshape(ink.shape[0], -1), axis=1)  # big-endian bit order
    return packed.tobytes(), max_ink


def render_html(
    *,
    spec: dict,
    payload_b64: str,
    audio_b64: str,
    meta: dict,
    out: Path,
) -> None:
    template = TEMPLATE.read_text()
    client_js = STANDALONE_JS.read_text()
    doc = (
        template.replace("__XY_CLIENT_JS__", client_js)
        .replace("__SPEC_JSON__", json.dumps(spec))
        .replace("__META_JSON__", json.dumps(meta))
        .replace("__PAYLOAD_B64__", payload_b64)
        .replace("__AUDIO_B64__", audio_b64)
    )
    out.write_text(doc)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--video", type=Path, default=None, help="source video (else download)")
    ap.add_argument("--url", default=DEFAULT_URL, help="download URL when no --video")
    ap.add_argument("--width", type=int, default=120, help="grid width in cells")
    ap.add_argument("--height", type=int, default=90, help="grid height in cells")
    ap.add_argument("--fps", type=float, default=20.0, help="playback frames per second")
    ap.add_argument("--threshold", type=int, default=128, help="0-255 ink cutoff")
    ap.add_argument("--invert", action="store_true", help="treat light pixels as ink")
    ap.add_argument("--canvas-w", type=int, default=720)
    ap.add_argument("--canvas-h", type=int, default=540)
    ap.add_argument("--no-audio", action="store_true", help="omit the embedded soundtrack")
    ap.add_argument("--audio-bitrate", default="96k", help="MP3 bitrate for the soundtrack")
    ap.add_argument("--out", type=Path, default=HERE / "bad_apple.html")
    args = ap.parse_args()

    video = args.video or DEFAULT_VIDEO
    if not video.exists():
        if args.video is not None:
            sys.exit(f"error: {video} does not exist")
        download_video(video, args.url)

    frames = extract_frames(video, args.width, args.height, args.fps)
    payload, max_ink = pack_frames(frames, args.threshold, args.invert)
    n_frames = frames.shape[0]
    bytes_per_frame = (args.width * args.height + 7) // 8

    gz = gzip.compress(payload, compresslevel=9)
    payload_b64 = base64.b64encode(gz).decode("ascii")

    audio_b64 = ""
    if not args.no_audio:
        audio = extract_audio(video, args.audio_bitrate)
        audio_b64 = base64.b64encode(audio).decode("ascii")

    spec = build_template_spec(args.width, args.height, args.canvas_w, args.canvas_h)
    cols = spec["columns"]
    meta = {
        "width": args.width,
        "height": args.height,
        "canvas_w": args.canvas_w,
        "canvas_h": args.canvas_h,
        "n_frames": n_frames,
        "fps": args.fps,
        "bytes_per_frame": bytes_per_frame,
        "max_ink": max_ink,
        # decode metadata the client needs to rebuild xy payload buffers:
        "x_offset": cols[0]["offset"],
        "x_scale": cols[0]["scale"],
        "y_offset": cols[1]["offset"],
        "y_scale": cols[1]["scale"],
    }

    meta["has_audio"] = bool(audio_b64)
    render_html(spec=spec, payload_b64=payload_b64, audio_b64=audio_b64, meta=meta, out=args.out)

    raw_mb = len(payload) / 2**20
    html_mb = args.out.stat().st_size / 2**20
    audio_note = f"{len(audio_b64) * 3 / 4 / 2**20:.1f} MB mp3" if audio_b64 else "no audio"
    print(
        f"\n{n_frames} frames @ {args.fps} fps ({n_frames / args.fps:.0f}s), "
        f"{args.width}x{args.height} grid\n"
        f"peak ink: {max_ink} of {args.width * args.height} cells\n"
        f"payload: {raw_mb:.1f} MB raw -> {len(gz) / 2**20:.2f} MB gzip  ·  {audio_note}\n"
        f"wrote {args.out}  ({html_mb:.1f} MB)"
    )


if __name__ == "__main__":
    main()
