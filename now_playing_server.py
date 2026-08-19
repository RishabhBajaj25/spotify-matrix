#!/usr/bin/env python3
"""
A tiny HTTP server that receives "now playing" updates from Tasker
and saves the latest state to disk.

Two endpoints, kept deliberately simple:

  POST /now-playing
      JSON body: {"title": ..., "artist": ..., "is_playing": true/false}
      Just text metadata, no image.

  POST /now-playing-art
      Raw request body = the raw bytes of the album art image
      (whatever Tasker's "HTTP Request" action sends when its Body
      is set to a local file). No base64, no multipart parsing --
      just the image bytes directly, which Tasker can send natively.

This does NOT touch the LED matrix yet. It's just meant to prove
that a phone can successfully hand album art + metadata to this
computer over the network.

Run it with:
    python3 now_playing_server.py

Then, from another terminal, test it with test_stage1.sh (curl).
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOST = "0.0.0.0"  # listen on all network interfaces, so the phone can reach it
PORT = 8890

OUTPUT_DIR = Path("received")
OUTPUT_DIR.mkdir(exist_ok=True)
LATEST_IMAGE_PATH = OUTPUT_DIR / "latest_album_art.jpg"
LATEST_META_PATH = OUTPUT_DIR / "latest_meta.json"


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

        title = payload.get("title", "")
        artist = payload.get("artist", "")
        is_playing = bool(payload.get("is_playing", False))

        LATEST_META_PATH.write_text(
            json.dumps({"title": title, "artist": artist, "is_playing": is_playing}, indent=2)
        )

        print(f"Metadata received: title={title!r} artist={artist!r} is_playing={is_playing}")
        self._send_json(200, {"status": "received"})

    def _handle_art(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            self._send_json(400, {"error": "empty body -- no image data received"})
            return

        image_bytes = self.rfile.read(length)
        LATEST_IMAGE_PATH.write_bytes(image_bytes)

        print(f"Art received: {len(image_bytes)} bytes -> saved to {LATEST_IMAGE_PATH}")
        self._send_json(200, {"status": "received", "bytes": len(image_bytes)})

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:  # quieter default logging
        pass


def run() -> None:
    server = HTTPServer((HOST, PORT), NowPlayingHandler)
    print(f"Listening on http://{HOST}:{PORT}")
    print("  POST /now-playing      (JSON: title, artist, is_playing)")
    print("  POST /now-playing-art  (raw image bytes)")
    print("  GET  /health")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
