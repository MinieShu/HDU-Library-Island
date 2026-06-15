"""
API 模块 - HTTP 客户端基类

封装 requests.Session，提供统一的请求处理、重试、日志功能。
"""
from __future__ import annotations

import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Any

logger = logging.getLogger(__name__)


class APIClient:
    """图书馆预约系统 HTTP 客户端。

    维护 Session、Cookie，提供带重试的 GET/POST 方法。
    """

    def __init__(
        self,
        base_url: str,
        user_agent: str = "Mozilla/5.0",
        timeout: int = 10,
        retry_count: int = 3,
        retry_delay: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        self.session = requests.Session()

        # 配置重试策略
        retry_strategy = Retry(
            total=retry_count,
            backoff_factor=retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # 设置默认请求头
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            }
        )

        self._is_logged_in = False

    def _build_url(self, path: str) -> str:
        """拼接完整的请求 URL。"""
        return f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"

    def get(self, path: str, params: dict | None = None, **kwargs) -> requests.Response:
        """发送 GET 请求。"""
        url = self._build_url(path)
        logger.debug(f"GET {url} params={params}")
        resp = self.session.get(url, params=params, timeout=self.timeout, **kwargs)
        logger.debug(f"GET {url} -> {resp.status_code} ({len(resp.content)} bytes)")
        return resp

    def post(self, path: str, data: dict | None = None, json: dict | None = None, **kwargs) -> requests.Response:
        """发送 POST 请求。"""
        url = self._build_url(path)
        logger.debug(f"POST {url}")
        resp = self.session.post(url, data=data, json=json, timeout=self.timeout, **kwargs)
        logger.debug(f"POST {url} -> {resp.status_code} ({len(resp.content)} bytes)")
        return resp

    def graphql(self, path: str, query: str, variables: dict | None = None) -> requests.Response:
        """发送 GraphQL 请求。"""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        return self.post(path, json=payload)

    @property
    def is_logged_in(self) -> bool:
        return self._is_logged_in

    @property
    def cookies(self) -> dict:
        return dict(self.session.cookies)

    def update_header(self, key: str, value: str) -> None:
        """更新请求头。"""
        self.session.headers[key] = value

    def set_referer(self, referer: str) -> None:
        self.session.headers["Referer"] = referer
