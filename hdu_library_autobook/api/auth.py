"""
API 模块 - 认证

处理杭电图书馆座位预约系统的登录认证。

杭电使用 CAS SSO（统一身份认证），认证流程使用 CAS REST API：
1. POST sso.hdu.edu.cn/v1/tickets（明文密码）→ 获取 TGT
2. POST sso.hdu.edu.cn/v1/tickets/{TGT}（service 参数）→ 获取 ST
3. GET zhishulib 回调地址（携带 ticket={ST}）→ 建立认证会话
"""
import re
import logging
from typing import Optional
from urllib.parse import quote

from .client import APIClient

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────
SSO_BASE = "https://sso.hdu.edu.cn"
SSO_LOGIN_URL = f"{SSO_BASE}/login"
SSO_TICKETS_URL = f"{SSO_BASE}/v1/tickets"
ZHISHU_BASE = "https://hdu.huitu.zhishulib.com"
CAS_SERVICE_PATH = "/User/Index/hduCASLogin"
CAS_FORWARD_PATH = "/Space/Category/redirect"


class AuthAPI:
    """杭电图书馆 CAS SSO 认证接口（基于 CAS REST API）。"""

    def __init__(self, client: APIClient):
        self._client = client
        self._user_info: Optional[dict] = None

    # ── 公开属性 ──────────────────────────────────────────

    @property
    def is_logged_in(self) -> bool:
        return self._client.is_logged_in

    @property
    def user_info(self) -> Optional[dict]:
        return self._user_info

    # ── Service URL 构造 ──────────────────────────────────

    @staticmethod
    def _build_service_url(category_id: int = 591) -> str:
        """构造 CAS service 回调地址（zhishulib 的 CAS 登录入口）。

        Args:
            category_id: 登录后默认跳转的空间分类 ID

        Returns:
            完整的 service URL
        """
        forward = f"{CAS_FORWARD_PATH}?category_id={category_id}"
        return f"{ZHISHU_BASE}{CAS_SERVICE_PATH}?forward={quote(forward, safe='')}"

    # ── 预获取 CAS Session ──────────────────────────────────

    def _acquire_cas_session(self) -> None:
        """预访问 CAS 登录页面，获取 session cookie 和可能的 CSRF token。

        部分 CAS 实现需要先建立会话才能调用 /v1/tickets REST API。
        """
        try:
            resp = self._client.session.get(
                SSO_LOGIN_URL,
                timeout=self._client.timeout,
                allow_redirects=True,
            )
            logger.debug(
                f"CAS 预登录: HTTP {resp.status_code}, "
                f"cookies={dict(self._client.session.cookies)}"
            )
        except Exception:
            logger.warning("CAS 预登录请求失败，继续尝试直接获取 TGT", exc_info=True)

    # ── 登录 ──────────────────────────────────────────────

    def login_by_password(self, student_id: str, password: str) -> bool:
        """通过学号和密码登录——CAS REST API 流程。

        使用 CAS REST 协议直接提交明文密码获取 TGT，无需解析
        SSO 登录页面的 HTML 或进行 AES 加密。

        Args:
            student_id: 学号
            password:  数字杭电密码（明文）

        Returns:
            登录成功返回 True
        """
        logger.info(f"CAS REST 登录：学号={student_id}")

        try:
            # ── Step 0: 预访问 CAS 登录页，获取 session cookie ──
            self._acquire_cas_session()

            # ── Step 1: 获取 TGT ──
            resp = self._client.session.post(
                SSO_TICKETS_URL,
                data={"username": student_id, "password": password},
                timeout=self._client.timeout,
            )

            # 详细日志：记录响应状态码和完整响应体（用于调试）
            logger.debug(
                f"CAS /v1/tickets 响应: HTTP {resp.status_code}, "
                f"Content-Type={resp.headers.get('Content-Type', '?')}, "
                f"body={resp.text[:500]!r}"
            )

            if resp.status_code != 201:
                error = self._parse_tgt_error(resp)
                logger.error(f"CAS TGT 获取失败: HTTP {resp.status_code} - {error}")
                return False

            # 从响应中提取 TGT URL（优先使用 Location 头，其次解析 HTML）
            tgt_url = self._extract_tgt_url(resp)
            if not tgt_url:
                logger.error(
                    f"CAS 响应中未找到 TGT URL，"
                    f"Location={resp.headers.get('Location', '?')!r}, "
                    f"响应内容: {resp.text[:300]!r}"
                )
                return False

            logger.debug(f"TGT URL: {tgt_url}")

            # ── Step 2: 用 TGT 换取 ST ──
            service = self._build_service_url()
            resp2 = self._client.session.post(
                tgt_url,
                data={"service": service},
                timeout=self._client.timeout,
            )

            if resp2.status_code != 200:
                logger.error(f"CAS ST 获取失败: HTTP {resp2.status_code}")
                return False

            st = resp2.text.strip()
            if not st or not st.startswith("ST-"):
                logger.error(f"CAS ST 格式异常: {st[:80] if st else '(空)'}")
                return False

            logger.debug(f"ST: {st}")

            # ── Step 3: 用 ST 在 zhishulib 建立认证会话 ──
            callback_url = f"{service}&ticket={st}"
            self._client.session.get(
                callback_url,
                allow_redirects=True,
                timeout=self._client.timeout,
            )

            # ── Step 4: 验证登录状态 ──
            verify_resp = self._client.session.get(
                ZHISHU_BASE + "/",
                allow_redirects=False,
                timeout=self._client.timeout,
            )

            # 如果被重定向回 SSO，说明 ticket 无效
            if verify_resp.status_code in (301, 302):
                location = verify_resp.headers.get("Location", "")
                if "sso" in location.lower():
                    logger.error("ST 验证失败，被重定向回 SSO")
                    return False

            self._client._is_logged_in = True
            logger.info(f"CAS REST 登录成功：{student_id}")
            return True

        except Exception:
            logger.exception("登录异常")
            return False

    # ── TGT 提取 ──────────────────────────────────────────

    @staticmethod
    def _extract_tgt_url(resp) -> Optional[str]:
        """从 CAS /v1/tickets 的 201 响应中提取 TGT URL。

        支持两种格式：
        1. 标准 CAS REST: Location 响应头直接返回 TGT URL
        2. HTML form: <form action="TGT-xxx..." method="POST">

        Returns:
            TGT 的完整 URL，或 None
        """
        # 方式 1: 标准 CAS REST 协议的 Location 头
        location = resp.headers.get("Location", "")
        if location and ("TGT-" in location):
            # 如果是相对路径，补全为完整 URL
            return location if location.startswith("http") else f"{SSO_BASE}{location}"

        # 方式 2: 从 HTML form 的 action 属性提取
        html = resp.text
        match = re.search(r'action="([^"]*TGT-[^"]+)"', html)
        if match:
            url = match.group(1)
            return url if url.startswith("http") else f"{SSO_BASE}{url}"

        # 方式 3: 响应体直接就是 TGT URL 的纯文本
        if html.strip().startswith("http") and "TGT-" in html:
            return html.strip()

        return None

    # ── 错误解析 ──────────────────────────────────────────

    @staticmethod
    def _parse_tgt_error(resp) -> str:
        """从 CAS TGT 请求的失败响应中提取错误信息。"""
        # 常见：400 Bad Request（用户名密码错误）
        # 400 响应可能包含提示信息
        try:
            text = resp.text[:500]
            # CAS REST 协议的标准错误格式
            if resp.status_code == 400:
                return "用户名或密码错误"
            elif resp.status_code == 403:
                return "访问被拒绝（可能需要先访问登录页面获取 session）"
            return text.strip() or f"HTTP {resp.status_code}"
        except Exception:
            return f"HTTP {resp.status_code}"

    # ── 用户信息 ──────────────────────────────────────────

    def get_user_info(self) -> Optional[dict]:
        """获取当前登录用户的信息。

        Returns:
            用户信息 dict，失败返回 None
        """
        try:
            resp = self._client.get("/api/user/info")
            if resp.status_code == 200:
                data = resp.json()
                self._user_info = data.get("data") or data
                return self._user_info
            logger.warning(f"获取用户信息失败: HTTP {resp.status_code}")
            return None
        except Exception:
            logger.exception("获取用户信息异常")
            return None

    # ── 登出 ──────────────────────────────────────────────

    def logout(self) -> None:
        """登出当前会话。"""
        self._user_info = None
        self._client._is_logged_in = False
        logger.info("已登出")
