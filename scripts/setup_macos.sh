#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT_DIR/hdu_library_autobook"
WEB_DIR="$APP_DIR/web"
VENV_DIR="$APP_DIR/venv"

pause_if_double_clicked() {
    if [ "${HDU_NO_PAUSE:-}" = "1" ]; then
        return
    fi

    if [ -t 0 ]; then
        printf "\n按回车键退出..."
        read -r _ || true
    fi
}

trap 'status=$?; if [ "$status" -ne 0 ]; then echo; echo "配置失败，请查看上面的错误信息。"; pause_if_double_clicked; fi' EXIT

print_step() {
    echo
    echo "==> $1"
}

find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" >/dev/null 2>&1 && "$cmd" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
            echo "$cmd"
            return 0
        fi
    done
    return 1
}

install_python() {
    if command -v brew >/dev/null 2>&1; then
        print_step "未找到 Python 3.10+，正在通过 Homebrew 安装/更新 Python"
        brew install python || brew upgrade python
        return
    fi

    echo "未找到 Python 3.10+，也没有检测到 Homebrew。"
    echo "已打开 Python 下载页，请安装后重新双击 setup.command。"
    open "https://www.python.org/downloads/macos/" >/dev/null 2>&1 || true
    exit 1
}

node_is_valid() {
    command -v node >/dev/null 2>&1 &&
        node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' >/dev/null 2>&1 &&
        command -v npm >/dev/null 2>&1
}

install_node() {
    if command -v brew >/dev/null 2>&1; then
        print_step "未找到 Node.js 18+ / npm，正在通过 Homebrew 安装/更新 Node.js"
        brew install node || brew upgrade node
        return
    fi

    echo "未找到 Node.js 18+ / npm，也没有检测到 Homebrew。"
    echo "已打开 Node.js 下载页，请安装 LTS 版本后重新双击 setup.command。"
    open "https://nodejs.org/" >/dev/null 2>&1 || true
    exit 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    install_python
    PYTHON="$(find_python || true)"
fi

if ! node_is_valid; then
    install_node
fi

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "Python 安装后仍不可用。请重新打开此脚本或检查 PATH。"
    exit 1
fi

if ! node_is_valid; then
    echo "Node.js 18+ / npm 安装后仍不可用。请重新打开此脚本或检查 PATH。"
    exit 1
fi

print_step "使用 $($PYTHON --version 2>&1)"
echo "==> 使用 Node.js $(node --version) / npm $(npm --version)"

cd "$APP_DIR"
if [ -x "$VENV_DIR/bin/python" ] && ! "$VENV_DIR/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    print_step "现有虚拟环境 Python 版本过低，正在重建"
    rm -rf "$VENV_DIR"
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    print_step "创建 Python 虚拟环境"
    "$PYTHON" -m venv "$VENV_DIR"
fi

print_step "安装/更新 Python 依赖"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt

cd "$WEB_DIR"
print_step "安装/更新 Web 依赖"
npm install

echo
echo "macOS 配置完成。现在可以双击 start.command 启动。"
pause_if_double_clicked
