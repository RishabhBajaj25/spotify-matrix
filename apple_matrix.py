#!/usr/bin/env python3
"""
Shows Apple Music's current album art on a 64x64 RGB matrix as a
circular spinning record.

Data comes from your phone (via Tasker + AutoNotification), which
POSTs "now playing" updates to this script's built-in HTTP server:

  POST /now-playing       JSON: {"title", "artist", "is_playing"}
  POST /now-playing-art   raw image bytes (the album art)

This script no longer talks to Spotify's API at all -- the phone is
the source of truth. See the Tasker setup notes for how those POSTs
get sent.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps


# ---------------------------------------------------------------------------
# Shared state: the HTTP server thread writes to this, the render loop reads it.
# ---------------------------------------------------------------------------

@dataclass
class SharedPlaybackState:
    title: str = ""
    artist: str = ""
    is_playing: bool = False
    image: Image.Image | None = None


# ---------------------------------------------------------------------------
# HTTP receiver -- same behavior as the standalone now_playing_server.py,
# but writing into SharedPlaybackState instead of disk files.
# ---------------------------------------------------------------------------

def make_handler(state: SharedPlaybackState, lock: threading.Lock) -> type[BaseHTTPRequestHandler]:
    class NowPlayingHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"status": "ok"})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path == "/now-playing":
                self._handle_metadata()
            elif self.path == "/now-playing-art":
                self._handle_art()
            else:
                self._send_json(404, {"error": "not found"})

        def _handle_metadata(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(length)
            try:
                payload = json.loads(raw_body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json(400, {"error": f"invalid JSON body: {exc}"})
                return

            with lock:
                state.title = payload.get("title", "")
                state.artist = payload.get("artist", "")
                state.is_playing = bool(payload.get("is_playing", False))

            print(f"Metadata: title={state.title!r} artist={state.artist!r} "
                  f"is_playing={state.is_playing}", flush=True)
            self._send_json(200, {"status": "received"})

        def _handle_art(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0:
                self._send_json(400, {"error": "empty body -- no image data received"})
                return

            image_bytes = self.rfile.read(length)
            try:
                image = Image.open(BytesIO(image_bytes)).convert("RGB")
            except Exception as exc:
                self._send_json(400, {"error": f"could not decode image: {exc}"})
                return

            with lock:
                state.image = image

            print(f"Art: {len(image_bytes)} bytes, {image.size}", flush=True)
            self._send_json(200, {"status": "received", "bytes": len(image_bytes)})

        def _send_json(self, status: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:  # quieter default logging
            pass

    return NowPlayingHandler


def run_server(state: SharedPlaybackState, lock: threading.Lock, host: str, port: int) -> None:
    server = HTTPServer((host, port), make_handler(state, lock))
    print(f"Now-playing receiver listening on http://{host}:{port}", flush=True)
    print("  POST /now-playing      (JSON: title, artist, is_playing)", flush=True)
    print("  POST /now-playing-art  (raw image bytes)", flush=True)
    server.serve_forever()


# ---------------------------------------------------------------------------
# Rendering -- unchanged from the original script.
# ---------------------------------------------------------------------------

def render_record(art: Image.Image | None, angle: float, size: int) -> Image.Image:
    frame = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    if art is None:
        return frame.convert("RGB")

    margin = max(2, size // 32)
    disc_size = size - margin * 2
    art_square = ImageOps.fit(art, (disc_size, disc_size), method=Image.Resampling.LANCZOS)
    rotated = art_square.rotate(angle, resample=Image.Resampling.BICUBIC)

    disc_mask = Image.new("L", (disc_size, disc_size), 0)
    mask_draw = ImageDraw.Draw(disc_mask)
    mask_draw.ellipse((0, 0, disc_size - 1, disc_size - 1), fill=255)
    frame.paste(rotated.convert("RGBA"), (margin, margin), disc_mask)

    draw = ImageDraw.Draw(frame, "RGBA")
    outer = (margin, margin, size - margin - 1, size - margin - 1)
    draw.ellipse(outer, outline=(6, 6, 6, 255), width=max(1, size // 32))

    center = size // 2
    label_radius = max(5, size // 11)
    hole_radius = max(2, size // 25)
    draw.ellipse(
        (center - label_radius, center - label_radius, center + label_radius, center + label_radius),
        fill=(16, 16, 16, 210),
        outline=(220, 220, 220, 90),
    )
    draw.ellipse(
        (center - hole_radius, center - hole_radius, center + hole_radius, center + hole_radius),
        fill=(0, 0, 0, 255),
    )
    return frame.convert("RGB")


def render_idle(size: int) -> Image.Image:
    frame = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(frame)
    margin = max(2, size // 32)
    draw.ellipse((margin, margin, size - margin - 1, size - margin - 1), outline=(55, 55, 55), width=2)
    center = size // 2
    radius = max(3, size // 18)
    draw.ellipse((center - radius, center - radius, center + radius, center + radius), fill=(18, 18, 18))
    return frame


def render_test_pattern(size: int, offset: int) -> Image.Image:
    frame = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(frame)
    colors = (
        (255, 0, 0), (255, 160, 0), (255, 255, 0), (0, 255, 0),
        (0, 120, 255), (80, 0, 255), (255, 255, 255), (0, 0, 0),
    )
    stripe_width = max(1, size // len(colors))
    for index, color in enumerate(colors):
        x0 = (index * stripe_width + offset) % size
        draw.rectangle((x0, 0, min(size - 1, x0 + stripe_width - 1), size - 1), fill=color)
        if x0 + stripe_width > size:
            draw.rectangle((0, 0, (x0 + stripe_width) % size, size - 1), fill=color)
    draw.rectangle((0, 0, size - 1, size - 1), outline=(255, 255, 255))
    return frame


def demo_album_art(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), (18, 18, 18))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size // 2, size // 2), fill=(238, 70, 60))
    draw.rectangle((size // 2, 0, size, size // 2), fill=(245, 180, 40))
    draw.rectangle((0, size // 2, size // 2, size), fill=(35, 150, 235))
    draw.rectangle((size // 2, size // 2, size, size), fill=(65, 185, 95))
    draw.line((0, 0, size, size), fill=(255, 255, 255), width=max(2, size // 18))
    draw.line((size, 0, 0, size), fill=(0, 0, 0), width=max(2, size // 22))
    return image


def render_preview_frames(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    art = demo_album_art(96)
    for index, angle in enumerate((0, 45, 90, 135)):
        render_record(art, angle, 64).save(directory / f"album-disk-{index:02d}.png")


# ---------------------------------------------------------------------------
# Display backends -- unchanged from the original script.
# ---------------------------------------------------------------------------

class MatrixDisplay:
    def __init__(self, args: argparse.Namespace) -> None:
        try:
            from rgbmatrix import RGBMatrix, RGBMatrixOptions
        except ImportError as exc:
            raise RuntimeError(
                "The rgbmatrix Python bindings are not installed. "
                "Install hzeller/rpi-rgb-led-matrix on the Pi, or run with --mock-output."
            ) from exc

        options = RGBMatrixOptions()
        options.rows = args.rows
        options.cols = args.cols
        options.chain_length = args.chain_length
        options.parallel = args.parallel
        options.brightness = args.brightness
        options.gpio_slowdown = args.gpio_slowdown
        options.hardware_mapping = args.hardware_mapping
        options.pwm_bits = args.pwm_bits
        options.limit_refresh_rate_hz = args.limit_refresh_rate_hz
        options.disable_hardware_pulsing = args.no_hardware_pulse

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()

    def show(self, image: Image.Image) -> None:
        self.canvas.SetImage(image.convert("RGB"))
        self.canvas = self.matrix.SwapOnVSync(self.canvas)

    def clear(self) -> None:
        self.matrix.Clear()


class MockDisplay:
    def __init__(self, output: Path) -> None:
        self.output = output
        self.output.parent.mkdir(parents=True, exist_ok=True)

    def show(self, image: Image.Image) -> None:
        image.save(self.output)

    def clear(self) -> None:
        return


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    if args.preview_frames:
        render_preview_frames(args.preview_frames)
        return

    state = SharedPlaybackState()
    lock = threading.Lock()

    # Testing convenience: pre-seed state with a local image so --mock-output
    # --once produces a real spinning frame without needing a phone/curl.
    if args.seed_art:
        with lock:
            state.image = Image.open(args.seed_art).convert("RGB")
            state.is_playing = True
            state.title = "Seeded Test Track"

    server_thread = threading.Thread(
        target=run_server, args=(state, lock, args.host, args.port), daemon=True
    )
    server_thread.start()

    display: MatrixDisplay | MockDisplay
    if args.mock_output:
        display = MockDisplay(args.mock_output)
    else:
        display = MatrixDisplay(args)

    size = min(args.rows, args.cols)

    if args.test_pattern:
        try:
            offset = 0
            while True:
                display.show(render_test_pattern(size, offset))
                offset = (offset + 1) % size
                time.sleep(1.0 / args.fps)
        except KeyboardInterrupt:
            pass
        finally:
            display.clear()
        return

    idle = render_idle(size)
    angle = 0.0
    last_frame = time.monotonic()

    try:
        while True:
            frame_start = time.monotonic()
            with lock:
                current_art_image = state.image
                is_playing = state.is_playing

            now = time.monotonic()
            delta = now - last_frame
            last_frame = now

            if is_playing and current_art_image is not None:
                angle = (angle - 360.0 * (args.rpm / 60.0) * delta) % 360.0

            image = render_record(current_art_image, angle, size) if current_art_image else idle
            display.show(image)

            if args.once:
                break

            sleep_for = max(0.0, (1.0 / args.fps) - (time.monotonic() - frame_start))
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    finally:
        display.clear()


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spin Apple Music album art on a 64x64 RGB matrix.")
    parser.add_argument("--rows", type=int, default=64)
    parser.add_argument("--cols", type=int, default=64)
    parser.add_argument("--chain-length", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--brightness", type=int, default=65)
    parser.add_argument("--gpio-slowdown", type=int, default=2)
    parser.add_argument("--hardware-mapping", default="regular")
    parser.add_argument("--pwm-bits", type=int, default=11)
    parser.add_argument("--limit-refresh-rate-hz", type=int, default=120)
    parser.add_argument(
        "--no-hardware-pulse",
        action="store_true",
        help="Avoid Pi onboard sound conflict at the cost of more possible flicker.",
    )
    parser.add_argument("--fps", type=positive_float, default=20.0)
    parser.add_argument("--rpm", type=positive_float, default=20.0)
    parser.add_argument("--host", default="0.0.0.0", help="Address the now-playing receiver listens on.")
    parser.add_argument("--port", type=int, default=8890, help="Port the now-playing receiver listens on.")
    parser.add_argument("--mock-output", type=Path, help="Write the current frame PNG instead of using RGB matrix hardware.")
    parser.add_argument("--preview-frames", type=Path, help="Render sample spinning-album-art disk frames and exit.")
    parser.add_argument("--test-pattern", action="store_true", help="Show a bright moving color test pattern, ignoring phone input.")
    parser.add_argument("--once", action="store_true", help="Render one frame and exit.")
    parser.add_argument("--seed-art", type=Path, help="TESTING ONLY: pre-load a local image as if it were received from the phone.")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
