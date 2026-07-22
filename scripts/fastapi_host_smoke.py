#!/usr/bin/env python3
"""Focused FastAPI/Starlette browser mount and drilldown transport probe."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FASTAPI_DIR = ROOT / "examples" / "fastapi"
sys.path.insert(0, str(ROOT / "scripts"))

from _app_smoke import ChromiumSession, Probe, decode_png, find_chromium  # noqa: E402

MIN_COLORED_PIXELS = 20


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as stream:
        stream.bind(("127.0.0.1", 0))
        return int(stream.getsockname()[1])


@contextlib.contextmanager
def serve_current_environment(log_path: Path, *, points: int = 5000) -> Iterator[str]:
    """Serve the example with this interpreter, preserving matrix versions."""
    port = _free_port()
    env = dict(os.environ)
    env["XY_LIVE_POINTS"] = str(points)
    env["PYTHONPATH"] = str(FASTAPI_DIR)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "info",
            ],
            cwd=FASTAPI_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"uvicorn exited with status {process.returncode}")
                try:
                    with urllib.request.urlopen(f"{base_url}/healthz", timeout=1) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, ConnectionError, OSError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("uvicorn did not become ready within 60 seconds")
            yield base_url
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
            if process.poll() is None:
                process.kill()
                process.wait()


def colored_pixels(png: bytes, rect: dict[str, float]) -> int:
    width, height, channels, pixels = decode_png(png)
    left = max(0, int(rect["x"]))
    top = max(0, int(rect["y"]))
    right = min(width, int(rect["x"] + rect["w"]))
    bottom = min(height, int(rect["y"] + rect["h"]))
    count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            offset = (y * width + x) * channels
            red, green, blue = pixels[offset : offset + 3]
            alpha = pixels[offset + 3] if channels == 4 else 255
            if alpha > 8 and max(red, green, blue) - min(red, green, blue) > 24:
                count += 1
    return count


def require_ink(count: int) -> None:
    if count < MIN_COLORED_PIXELS:
        raise AssertionError(
            f"FastAPI browser mount is blank ({count} colored pixels; need {MIN_COLORED_PIXELS})"
        )


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium")
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--screenshot", type=Path, required=True)
    parser.add_argument("--server-log", type=Path, required=True)
    args = parser.parse_args(argv)

    evidence: dict[str, object] = {"schema_version": 1, "status": "failed"}
    probe: Probe | None = None
    try:
        chromium = find_chromium(args.chromium)
        with (
            serve_current_environment(args.server_log) as base_url,
            ChromiumSession(
                chromium,
                gl="software",
                sandbox=not args.no_sandbox,
            ) as session,
        ):
            probe = Probe(session, f"{base_url}/chart/line-walk", emulate=(900, 560, 1.0))
            mount = probe.wait_for(
                "(() => { const c=document.querySelector('canvas');"
                " if(!c || !c.width || !c.height) return null;"
                " const gl=c.getContext('webgl2');"
                " return gl ? {width:c.width,height:c.height} : null; })()",
                timeout_s=45,
                label="FastAPI WebGL2 chart mount",
            )
            rect = probe.rect("canvas")
            screenshot = probe.screenshot()
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            args.screenshot.write_bytes(screenshot)
            ink = colored_pixels(screenshot, rect)
            require_ink(ink)

            # Standalone chart exports intentionally deny network access. Use
            # the host-owned gallery shell for a separate browser-originated
            # transport assertion after proving the static chart mount above.
            probe.close()
            probe = Probe(session, base_url, emulate=(900, 560, 1.0))
            probe.wait_for(
                "document.readyState === 'complete' ? true : null",
                timeout_s=30,
                label="FastAPI gallery shell",
            )
            endpoint = json.dumps(f"{base_url}/api/xy/drilldown")
            transport = probe.eval(
                f"(async () => {{ const response=await fetch({endpoint},{{"
                "method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({"
                "type:'density_view',trace:0,x0:-1,x1:1,y0:-1,y1:1,w:64,h:48,"
                "seq:23,client_id:'host-browser'})});"
                "const payload=await response.json();"
                "return {status:response.status,type:payload.message?.type}; })()"
            )
            if transport != {"status": 200, "type": "density_update"}:
                raise AssertionError(f"browser drilldown transport failed: {transport}")
            evidence.update(
                {
                    "status": "passed",
                    "mount": mount,
                    "colored_pixels": ink,
                    "transport": transport,
                }
            )
        print(f"FastAPI host browser smoke OK: {ink} colored pixels")
        return 0
    except Exception as exc:
        evidence["error"] = str(exc)
        raise
    finally:
        if probe is not None:
            probe.close()
        _write_evidence(args.evidence, evidence)


if __name__ == "__main__":
    raise SystemExit(main())
