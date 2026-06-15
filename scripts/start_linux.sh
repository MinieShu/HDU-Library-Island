#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/hdu_library_autobook"
WEB_DIR="$APP_DIR/web"
SETUP_SCRIPT="$ROOT_DIR/scripts/setup_linux.sh"
PYTHON="$APP_DIR/venv/bin/python"

if [ ! -x "$PYTHON" ] || [ ! -d "$WEB_DIR/node_modules" ]; then
    "$SETUP_SCRIPT"
fi

cd "$ROOT_DIR"
"$PYTHON" -m hdu_library_autobook.web_api &
API_PID=$!

cleanup() {
    kill "$API_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

cd "$WEB_DIR"
npm run dev -- --host 127.0.0.1 --open
