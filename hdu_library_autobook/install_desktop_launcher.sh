#!/bin/bash
# =============================================
#  杭电图书馆预约系统 - 桌面启动器安装脚本
#  运行此脚本会在桌面创建应用图标
# =============================================

APP_NAME="杭电图书馆预约"
DESKTOP_PATH="$HOME/Desktop/$APP_NAME.app"
PROJECT_DIR="$HOME/Documents/hdu library/hdu_library_autobook"

echo "========================================"
echo "  创建桌面启动器..."
echo "========================================"
echo ""

# 检查项目是否存在
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 错误：找不到项目目录"
    echo "   期望路径: $PROJECT_DIR"
    exit 1
fi

# 创建 .app 包结构
mkdir -p "$DESKTOP_PATH/Contents/MacOS"
mkdir -p "$DESKTOP_PATH/Contents/Resources"

# 创建 Info.plist
cat > "$DESKTOP_PATH/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.hdu.library.autobook</string>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>杭电图书馆预约系统</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
EOF

# 创建启动器脚本
cat > "$DESKTOP_PATH/Contents/MacOS/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
# 杭电图书馆预约系统 - 桌面启动器

PROJECT_DIR="$HOME/Documents/hdu library/hdu_library_autobook"
VENV_DIR="$PROJECT_DIR/venv"
cd "$PROJECT_DIR" || {
    osascript -e 'display dialog "错误：找不到项目目录\n\n期望路径: '"$HOME/Documents/hdu library/hdu_library_autobook"'" buttons {"确定"} default button 1 with icon stop'
    exit 1
}

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
        osascript -e 'display dialog "错误：未找到 Python 3.10+\n\n请先安装 Python 3.10+" buttons {"确定"} default button 1 with icon stop'
        exit 1
    fi

    "$BASE_PYTHON" -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        osascript -e 'display dialog "虚拟环境创建失败\n\n请打开终端运行 install.sh 查看详情" buttons {"确定"} default button 1 with icon stop'
        exit 1
    fi
    PYTHON="$VENV_DIR/bin/python"
fi

# 检测依赖
if ! "$PYTHON" -c "from PyQt6.QtWidgets import QApplication; import requests, cryptography, bs4" 2>/dev/null; then
    INSTALL=$(osascript -e 'display dialog "需要安装或补齐项目依赖\n\n是否自动安装？" buttons {"取消", "安装"} default button 2 with icon caution')

    if echo "$INSTALL" | grep -q "button returned:安装"; then
        "$PYTHON" -m pip install --upgrade pip
        "$PYTHON" -m pip install -r requirements.txt
        if [ $? -ne 0 ]; then
            osascript -e 'display dialog "依赖安装失败，请手动运行:\n\n./install.sh" buttons {"确定"} default button 1 with icon stop'
            exit 1
        fi
    else
        exit 0
    fi
fi

# 启动应用（保留错误日志）
ERROR_LOG="$HOME/Desktop/杭电图书馆预约_错误日志.txt"
"$PYTHON" main.py > "$ERROR_LOG" 2>&1

# 如果启动失败，显示错误
if [ $? -ne 0 ]; then
    ERROR_MSG=$(cat "$ERROR_LOG")
    osascript -e "display dialog \"启动失败，错误信息：\n\n$ERROR_MSG\n\n完整日志已保存到桌面\" buttons {\"确定\"} default button 1 with icon stop"
fi
LAUNCHER

chmod +x "$DESKTOP_PATH/Contents/MacOS/$APP_NAME"

# 尝试设置图标（可选，使用系统默认的 Python 图标）
if [ -f "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns" ]; then
    cp "/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns" \
       "$DESKTOP_PATH/Contents/Resources/app.icns"
fi

echo "✅ 桌面启动器已创建！"
echo "   位置: $DESKTOP_PATH"
echo ""
echo "双击桌面上的「$APP_NAME」即可启动预约系统"
echo "首次启动可能需要右键点击 → 打开（因为来自未识别的开发者）"
echo ""

# 在 Finder 中显示
open -R "$DESKTOP_PATH"
