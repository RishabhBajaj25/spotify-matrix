#!/usr/bin/env bash
# Stage 1 test: sends a fake "now playing" update to now_playing_server.py
# using curl, so you can confirm the server works BEFORE involving your phone.
#
# Usage:
#   1. In one terminal: python3 now_playing_server.py
#   2. In another terminal: bash test_stage1.sh
set -euo pipefail

IMAGE_B64=$(cat sample_album_art_base64.txt)

curl -s -X POST http://127.0.0.1:8890/now-playing \
  -H "Content-Type: application/json" \
  -d "{\"title\": \"Test Track\", \"artist\": \"Test Artist\", \"is_playing\": true, \"image_base64\": \"${IMAGE_B64}\"}"

echo
echo "---"
echo "If that printed {\"status\": \"received\"}, check received/latest_album_art.png"
