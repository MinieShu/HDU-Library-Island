#!/bin/bash
# =============================================
#  杭电图书馆座位预约系统 - 安装脚本
#  适用于 macOS / Linux
# =============================================

echo "========================================"
echo "  杭电图书馆座位预约系统 - 安装"
echo "========================================"
echo ""

PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cmd" &> /dev/null && "$cmd" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

# 检查 Python
if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 Python 3.10+，请先安装 Python 3.10+"
    exit 1
fi
echo "✅ $($PYTHON --version)"

# 创建虚拟环境（可选）
if "$PYTHON" -m venv --help &> /dev/null; then
    if [ ! -d "venv" ]; then
        echo "📦 创建虚拟环境..."
        "$PYTHON" -m venv venv
    fi
    source venv/bin/activate
    echo "✅ 虚拟环境已激活"
fi

# 安装依赖
echo "📥 安装依赖..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️  pip 安装失败，尝试使用 pip3..."
    "$PYTHON" -m pip install -r requirements.txt
fi

echo ""
echo "========================================"
echo "  ✅ 安装完成！"
echo "========================================"
echo ""
echo "启动应用："
echo "  python3 main.py"
echo ""
echo "调试模式："
echo "  python3 main.py --verbose"
echo ""
echo "========================================"
