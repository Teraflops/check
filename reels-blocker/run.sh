#!/usr/bin/env bash
# Start the reels-blocking filtering proxy.
#
#   ./run.sh              # listen on 0.0.0.0:8080 (default)
#   PORT=9090 ./run.sh    # custom port
#
# Point your device/router HTTP+HTTPS proxy at this host:$PORT and install the
# mitmproxy CA on the client (http://mitm.it once connected) so HTTPS reels
# traffic can be inspected. See README.md for full setup.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"

if ! command -v mitmdump >/dev/null 2>&1; then
  echo "mitmdump not found. Install deps first:  pip install -r requirements.txt" >&2
  exit 1
fi

echo "Starting reels-blocker proxy on :$PORT  (Ctrl-C to stop)"
exec mitmdump --listen-port "$PORT" -s reels_blocker.py
