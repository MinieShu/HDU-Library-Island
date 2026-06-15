#!/bin/bash
# =============================================
#  杭电图书馆座位预约系统 - 启动脚本
#  双击此文件即可运行（macOS）
# =============================================

# 获取脚本所在目录（支持双击运行和终端运行）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
VENV_DIR="$SCRIPT_DIR/venv"

echo "========================================"
echo "  杭电图书馆座位预约系统"
echo "========================================"
echo ""

# 检测 Python，优先使用项目虚拟环境，避免系统/用户目录里的 PyQt 架构不匹配
if [ -x "$VENV_DIR/bin/python" ]; then
    PYTHON="$VENV_DIR/bin/python"
else
    BASE_PYTHON=""
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" &> /dev/null && "$cmd" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            BASE_PYTHON="$cmd"
            break
        fi
    done

    if [ -z "$BASE_PYTHON" ]; then
        echo "❌ 错误：未找到 Python 3.10+"
        echo "请先安装 Python 3.10+"
        echo "  https://www.python.org/downloads/"
        read -p "按回车键退出..."
        exit 1
    fi

    echo "📦 创建项目虚拟环境..."
    "$BASE_PYTHON" -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "❌ 虚拟环境创建失败"
        read -p "按回车键退出..."
        exit 1
    fi
    PYTHON="$VENV_DIR/bin/python"
fi

echo "🔍 检测到: $($PYTHON --version 2>&1)"

# 检测项目依赖
if ! "$PYTHON" -c "from PyQt6.QtWidgets import QApplication; import requests, cryptography, bs4" 2>/dev/null; then
    echo "📦 正在安装依赖..."
    "$PYTHON" -m pip install --upgrade pip
    "$PYTHON" -m pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo ""
        echo "❌ 依赖安装失败"
        echo "请手动执行："
        echo "  $PYTHON -m pip install -r requirements.txt"
        read -p "按回车键退出..."
        exit 1
    fi
    echo "✅ 依赖安装完成"
fi

echo "🚀 正在启动应用..."
echo ""

# 运行应用
"$PYTHON" main.py

# 如果应用退出，暂停以便查看错误
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 应用异常退出"
    read -p "按回车键关闭..."
fi
