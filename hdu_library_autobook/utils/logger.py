"""
工具模块 - 日志配置（基于标准库 logging）

减少外部依赖，使用 Python 标准日志库。
"""
import logging
import logging.handlers
import sys
from pathlib import Path


LOG_DIR = Path(__file__).parent.parent / "logs"


def setup_logger(verbose: bool = False) -> None:
    """配置日志系统。

    Args:
        verbose: 是否启用 DEBUG 级别
    """
    LOG_DIR.mkdir(exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有处理器，避免重复
    root.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # 文件处理器（保留 7 天，每个文件最大 10MB）
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)

    root.info("日志系统初始化完成")
