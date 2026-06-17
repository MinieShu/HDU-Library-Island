#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/hdu_library_autobook"
WEB_DIR="$APP_DIR/web"
SETUP_SCRIPT="$ROOT_DIR/scripts/setup_macos.sh"
PYTHON="$APP_DIR/venv/bin/python"

pause_if_double_clicked() {
    if [ -t 0 ]; then
        printf "\n按回车键退出..."
        read -r _ || true
    fi
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo; echo "启动失败，请查看上面的错误信息。"; pause_if_double_clicked; fi' EXIT

needs_setup() {
    [ ! -x "$PYTHON" ] && return 0
    [ ! -d "$WEB_DIR/node_modules" ] && return 0
    "$PYTHON" -c 'import fastapi, uvicorn, PyQt6, requests' >/dev/null 2>&1 || return 0
    command -v node >/dev/null 2>&1 || return 0
    node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' >/dev/null 2>&1 || return 0
    command -v npm >/dev/null 2>&1 || return 0
    return 1
}

if needs_setup; then
    echo "检测到环境未配置或依赖不完整，正在自动配置..."
    HDU_NO_PAUSE=1 "$SETUP_SCRIPT"
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
