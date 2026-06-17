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

install_linux_packages() {
    print_step "尝试安装/更新 Python、venv、Node.js 和 npm"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv python3-pip nodejs npm
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip nodejs npm
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -Sy --needed python python-pip nodejs npm
    else
        echo "未识别当前 Linux 包管理器。请手动安装 Python 3.10+、Node.js 18+ 和 npm。"
        exit 1
    fi
}

node_is_valid() {
    command -v node >/dev/null 2>&1 &&
        node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 18 ? 0 : 1)' >/dev/null 2>&1 &&
        command -v npm >/dev/null 2>&1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ] || ! node_is_valid; then
    install_linux_packages
fi

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
    echo "Python 3.10+ 安装后仍不可用。请检查系统包源或 PATH。"
    exit 1
fi

if ! node_is_valid; then
    echo "Node.js 18+ / npm 安装后仍不可用。某些系统默认源的 Node.js 版本较旧，请安装 NodeSource 或官方 LTS 版本。"
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
echo "Linux 配置完成。现在可以运行 start.sh 或 scripts/start_linux.sh 启动。"
pause_if_double_clicked
