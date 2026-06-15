#!/bin/zsh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

python3 -m hdu_library_autobook.web_api &
API_PID=$!

cd hdu_library_autobook/web
npm run dev -- --open

kill "$API_PID" 2>/dev/null || true
