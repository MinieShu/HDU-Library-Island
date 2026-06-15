"""
工具模块 - 配置管理
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONFIG_DIR = Path(__file__).parent.parent
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.json"


class Config:
    """应用配置管理器，支持从 JSON 文件读写配置。"""

    def __init__(self, config_path: Path | None = None):
        self._path = config_path or DEFAULT_CONFIG_PATH
        self._data: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """从文件加载配置。"""
        if self._path.exists():
            with open(self._path, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        return self._data

    def save(self) -> None:
        """保存配置到文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=4, ensure_ascii=False)

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的嵌套键（如 'auth.student_id'）。"""
        keys = key.split(".")
        value: Any = self._data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """设置配置值，支持点号分隔的嵌套键。"""
        keys = key.split(".")
        target: dict[str, Any] = self._data
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    def update(self, data: dict[str, Any]) -> None:
        """用字典批量更新配置。"""
        self._data.update(data)

    @property
    def data(self) -> dict[str, Any]:
        return self._data
