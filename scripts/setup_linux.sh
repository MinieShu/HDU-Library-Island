#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/hdu_library_autobook"
WEB_DIR="$APP_DIR/web"
VENV_DIR="$APP_DIR/venv"

find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" >/dev/null 2>&1 && "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "未找到 Python 3.10+。请先安装 Python 3.10 或更高版本。"
    exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
    echo "未找到 npm。请先安装 Node.js 18 或更高版本。"
    exit 1
fi

cd "$APP_DIR"
if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

cd "$WEB_DIR"
npm install

echo "Linux 配置完成。"
