# Bad Apple!! — rendered with xy

A self-contained HTML page that plays the full "Bad Apple!!" animation where
**every frame is a live xy scatter**. Each frame's ink pixels become square
points, and the player feeds one fresh payload per frame into xy's streaming
render path (`ChartView._applyAppend` — the same WebGL2 code a live dashboard
uses, §5/§29). It's a fun stress test of the append path: ~20 full scatter
rebuilds a second, up to the whole grid of points.

## How it works

```
video ──ffmpeg──▶ WxH grayscale frames ──threshold──▶ 1 bit/cell mask
      ──gzip+base64──▶ embedded in one HTML file
```

In the browser the mask is inflated with `DecompressionStream`, and for each
frame the set bits are turned back into xy payload buffers **client-side**
(offset-encoded f32 x/y columns) and handed to the renderer. The axis domain is
pinned to the whole grid so every frame reuses one f32 offset; an authentic
xy-generated spec is used as the per-frame template, so this drives the real
engine, not a reimplementation. A 3.5-minute clip at 120×90 / 20 fps is ~1 MB.

The soundtrack (extracted from the same clip as MP3) is embedded too and acts as
the **master clock**: the displayed frame is read from `audio.currentTime`, so
picture and sound can't drift. Browsers block autoplay-with-sound, so the page
starts paused — press play. Build with `--no-audio` for a silent ~1 MB page.

## Build it

```bash
# from the repo root, with the dev venv active (numpy + native core required)
python examples/bad_apple/build.py            # downloads the clip if needed
open examples/bad_apple/bad_apple.html        # then just open it in a browser
```

Options:

```bash
python examples/bad_apple/build.py --video path/to/clip.mp4   # use a local file
python examples/bad_apple/build.py --width 160 --height 120 --fps 24
python examples/bad_apple/build.py --invert                   # light pixels are ink
```

`ffmpeg` and `yt-dlp` must be on `PATH`. Dark pixels become ink by default
(faithful to the source, so the demo reproduces the video's polarity flips).

## Looks

The same 1-bit mask drives several live styles (the chip picker in the player) —
only the per-point color scalar (fed through one of the engine's colormaps), the
marker symbol, and the background change:

- **Solid ink** — faithful black-on-white silhouette (the baseline)
- **Neon** — dots colored by radial distance through `turbo`, hue drifting over the song
- **Heatmap** / **Thermal** — the mask blurred into a smooth field and handed to the
  engine's real `heatmap` trace (`inferno` / `jet`), swapped in live per frame
- **Ember** / **Aurora** — `inferno` / `viridis` by height on black
- **Outline** — silhouette edge only, `rainbow` line-art
- **Dot matrix** — mono green LED board

The heatmap looks are the actual heatmap chart type (not points): each frame's
1-bit mask is Gaussian-blurred, upscaled, and shipped as a normalized grid, so
the trace *kind* changes live through the same append path.

## Player controls

A full media-player UI: play/pause, seek scrubber, volume + mute, fullscreen,
and a chip picker for the look. Click the picture to toggle playback.

Keyboard shortcuts (press <kbd>?</kbd> in the player for the full list):

| Key | Action | Key | Action |
| --- | --- | --- | --- |
| `Space` / `K` | play / pause | `,` `.` | step one frame |
| `←` `→` | seek ∓5 s | `0`–`9` | jump to 0–90% |
| `J` `L` | seek ∓10 s | `Home` / `End` | start / end |
| `↑` `↓` / `M` | volume / mute | `F` | fullscreen |

Accessibility: the looks are an ARIA `radiogroup` (arrow-key navigable), controls
carry labels and live-updating `aria-valuetext`, state changes are announced via a
polite live region, focus is keyboard-visible, and the demo starts paused under
`prefers-reduced-motion`. It's responsive down to phone widths.

Deep-links: `bad_apple.html#f=1200` opens paused at a frame; `#look=neon` picks a
look. Both are also how the build's headless check verifies frames.

## A note on the source

The clip and its soundtrack are copyrighted, so neither the download nor the
generated `bad_apple.html` (which embeds the derived frames and the audio) is
committed — both are git-ignored. Run `build.py` to regenerate the page locally.
