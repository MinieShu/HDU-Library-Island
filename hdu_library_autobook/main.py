#!/usr/bin/env python3
"""
杭电图书馆座位预约系统 - 主入口

杭州电子科技大学图书馆座位/场地自动预约桌面应用。

使用方法：
    python main.py              # 启动图形界面
    python main.py --verbose    # 调试模式（详细日志）

依赖安装：
    pip install -r requirements.txt

注意事项：
1. 首次使用请先在登录页输入学号和密码
2. 如果系统 API 地址变更，可在登录页「高级设置」中修改
3. 定时抢座功能默认在每晚 20:00 触发
4. 签到需到图书馆现场扫码或使用蓝牙签到
"""
import sys
import argparse
import logging
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from PyQt6.QtWidgets import QApplication

from utils.config import Config
from utils.logger import setup_logger
from gui import MainWindow

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="杭电图书馆座位预约系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例：
  python main.py                 启动图形界面
  python main.py --verbose       调试模式
  python main.py --no-auto       禁用自动登录
        """,
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用详细日志输出（调试模式）",
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="禁用启动时自动登录",
    )
    return parser.parse_args()


def main():
    """主函数。"""
    args = parse_args()

    # 初始化日志
    setup_logger(verbose=args.verbose)
    logger.info("=" * 50)
    logger.info("杭电图书馆座位预约系统启动")
    logger.info("=" * 50)

    # 加载配置
    config = Config()
    config.load()
    logger.debug(f"配置已加载：{config.data}")

    # 启动 Qt 应用
    app = QApplication(sys.argv)
    app.setApplicationName("杭电图书馆座位预约系统")
    app.setApplicationVersion("1.0.0")

    # 设置应用全局样式
    app.setStyle("Fusion")

    # 创建并显示主窗口
    window = MainWindow(config)
    window.show()

    # 自动登录（如果配置了）
    if not args.no_auto:
        auto_login = config.get("auth.auto_login", False)
        if auto_login:
            logger.info("尝试自动登录...")
            window._login_panel.try_auto_login()

    # 进入事件循环
    try:
        exit_code = app.exec()
        logger.info(f"应用退出，退出码：{exit_code}")
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("用户中断")
        sys.exit(0)


if __name__ == "__main__":
    main()
