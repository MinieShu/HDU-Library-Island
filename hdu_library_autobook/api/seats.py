"""
API 模块 - 座位预约

处理杭电智慧图书馆（zhishulib.com）的座位查询、预约、取消。
API 基于 HAR 抓包反向工程，全部使用 LAB_JSON=1 参数和表单编码。

关键发现：
- 所有时间均为 Unix 时间戳（秒），北京时区（UTC+8）
- POST 使用 application/x-www-form-urlencoded
- 响应格式：CODE="ok" 表示成功
- 每晚 20:00 开放预约（对应 advance_date 为当天 00:00）
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta, date
from typing import Any, Optional
from dataclasses import dataclass, field
import logging
import time

from .client import APIClient

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))


def _is_ok_code(code: Any) -> bool:
    """Return True for known successful API CODE values."""
    return str(code).strip().upper() == "OK"


def _has_booking_id(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    booking_id = data.get("bookingId")
    return booking_id not in (None, "", 0, "0")


@dataclass
class SeatArea:
    """座位区域信息。"""
    area_id: int
    name: str
    category_id: int = 0
    content_id: int = 0
    floor: str = ""
    total_seats: int = 0
    available_seats: int = 0


@dataclass
class SeatInfo:
    """单个座位信息。"""
    seat_id: int
    seat_label: str
    area_name: str
    status: int  # 0/1，1 表示可用
    have_socket: int = 0
    x: int = 0
    y: int = 0
    width: int = 2
    height: int = 2
    status_priority: int = 0  # 状态来源可信度，去重时使用


@dataclass
class BookingResult:
    """预约结果。"""
    success: bool
    message: str
    booking_id: Optional[int] = None
    seat_label: Optional[str] = None
    room_name: Optional[str] = None


@dataclass
class SeatMapInfo:
    """座位地图信息（楼层平面图 + 座位坐标）。"""
    room_name: str = ""
    plan_url: str = ""
    map_width: int = 0
    map_height: int = 0
    plan_width: int = 0   # 平面图实际像素宽度
    plan_height: int = 0  # 平面图实际像素高度
    seats: list = field(default_factory=list)


class SeatAPI:
    """杭电智慧图书馆座位预约 API。

    基于 zhishulib.com /Seat/Index/* 接口实现。
    """

    BASE = "/Seat/Index"
    BASE_URL = "https://hdu.huitu.zhishulib.com"

    def __init__(self, client: APIClient):
        self._client = client
        self._uid: Optional[int] = None
        self._page_data: Optional[dict] = None
        self._last_search_response: Optional[dict] = None
        # 设置 Referer，很多接口会检查
        self._client.set_referer(f"{self.BASE_URL}/")

    # ── 分类列表 ──────────────────────────────────────────

    def get_categories(self) -> list[dict]:
        """获取所有可预约的空间分类列表。

        调用 /Space/Category/list 接口，返回：
        [{"name": "自习室", "category_id": 591, "content_id": 3, "desc": "..."}, ...]

        Returns:
            分类列表
        """
        params = self._lab_params()
        resp = self._client.get("/Space/Category/list", params=params)
        data = resp.json()

        logger.debug(
            f"get_categories 响应: HTTP {resp.status_code}, "
            f"top_keys={list(data.keys())}, "
            f"content_keys={list(data.get('content', {}).keys()) if isinstance(data.get('content'), dict) else type(data.get('content'))}"
        )

        cats = []
        content = data.get("content", {})
        if not isinstance(content, dict):
            logger.warning(f"get_categories: content 不是 dict, type={type(content).__name__}")
            return cats

        for child in content.get("children", []):
            if not isinstance(child, dict):
                continue
            ui_type = child.get("ui_type", "")
            logger.debug(f"get_categories: child ui_type={ui_type}, keys={list(child.keys())[:8]}")

            if ui_type == "com.List":
                items = child.get("defaultItems", [])
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    link = item.get("link", {})
                    url = link.get("url", "")
                    # 从 URL 提取 category_id 和 content_id
                    import re
                    m_cat = re.search(r'category_id%5D=(\d+)', url)
                    m_cont = re.search(r'content_id%5D=(\d+)', url)
                    cats.append({
                        "name": item.get("name", ""),
                        "eng_name": item.get("engName", ""),
                        "space": item.get("space", ""),
                        "desc": item.get("desc", ""),
                        "category_id": int(m_cat.group(1)) if m_cat else 0,
                        "content_id": int(m_cont.group(1)) if m_cont else 0,
                        "disabled": item.get("disabled", False),
                    })

        logger.info(f"get_categories: 解析到 {len(cats)} 个分类")
        return cats

    # ── 工具方法 ──────────────────────────────────────────

    @staticmethod
    def _lab_params(**extra) -> dict:
        """所有 API 请求都需要 LAB_JSON=1 参数。"""
        params = {"LAB_JSON": "1"}
        params.update(extra)
        return params

    @staticmethod
    def _to_timestamp(dt: datetime) -> int:
        """datetime → Unix 时间戳（秒）。"""
        return int(dt.timestamp())

    @staticmethod
    def _from_timestamp(ts: int) -> datetime:
        """Unix 时间戳 → datetime（北京时区）。"""
        return datetime.fromtimestamp(ts, tz=BEIJING_TZ)

    @staticmethod
    def _date_to_midnight_ts(d: date) -> int:
        """日期 → 当天 00:00 的 Unix 时间戳（北京时间视为 UTC+8）。"""
        dt = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=BEIJING_TZ)
        return int(dt.timestamp())

    # ── 座位页面数据（区域信息、时间范围、uid）─────────────

    def load_seat_page(self, category_id: int, content_id: int) -> dict:
        """加载座位预约页面数据，获取时间范围、uid 等信息。

        这是进入座位预约页面的第一步。
        响应中的 data.range 包含：max_date, advance_date,
        minBeginTime, maxEndTime, min/max_duration 等。

        Args:
            category_id: 空间类别 ID（如 591）
            content_id:  内容 ID（如 3）

        Returns:
            API 响应的完整 data dict
        """
        params = self._lab_params(
            **{
                "space_category[category_id]": str(category_id),
                "space_category[content_id]": str(content_id),
            }
        )
        resp = self._client.get(f"{self.BASE}/searchSeats", params=params)
        data = resp.json()

        logger.debug(
            f"load_seat_page 响应: HTTP {resp.status_code}, "
            f"top_keys={list(data.keys())}, "
            f"data_keys={list(data.get('data', {}).keys()) if isinstance(data.get('data'), dict) else 'N/A'}"
        )

        # 提取 uid
        inner = data.get("data", {})
        if inner.get("uid"):
            self._uid = int(inner["uid"])
            logger.info(f"load_seat_page: uid={self._uid}")
        else:
            logger.warning(
                f"load_seat_page: 响应中没有 uid, data keys={list(inner.keys())[:10] if isinstance(inner, dict) else type(inner)}"
            )

        self._page_data = data
        return data

    # ── 搜索座位 ──────────────────────────────────────────

    def search_seats(
        self,
        category_id: int,
        content_id: int,
        begin_time: datetime,
        duration_hours: int = 1,
        num: int = 1,
    ) -> dict:
        """搜索可用座位（系统推荐模式）。

        Args:
            category_id:     空间类别 ID
            content_id:      内容 ID
            begin_time:      预约开始时间（datetime）
            duration_hours:  预约时长（小时）
            num:             预约人数

        Returns:
            API 响应 dict，其中的 content.children 包含座位推荐
        """
        data = {
            "beginTime": self._to_timestamp(begin_time),
            "duration": duration_hours * 3600,
            "num": num,
            "space_category[category_id]": str(category_id),
            "space_category[content_id]": str(content_id),
        }
        resp = self._client.post(
            f"{self.BASE}/searchSeats",
            data=data,
            params=self._lab_params(),
        )
        result = resp.json()
        self._last_search_response = result
        # 打印响应 body 大小
        body_size = len(resp.content)
        logger.info(
            f"search_seats 响应: HTTP {resp.status_code}, "
            f"body={body_size} bytes, "
            f"top_keys={list(result.keys())}, "
            f"content_type={type(result.get('content')).__name__}"
        )
        if isinstance(result.get("content"), dict):
            content = result["content"]
            logger.info(
                f"  content: ui_type={content.get('ui_type', '?')}, "
                f"children_count={len(content.get('children', [])) if isinstance(content.get('children'), list) else '?'}"
            )
        return result

    # ── 预约座位 ──────────────────────────────────────────

    def book_seat(
        self,
        seat_id: int,
        begin_time: datetime,
        duration_hours: int = 1,
        is_recommend: bool = True,
    ) -> BookingResult:
        """预约指定座位。

        Args:
            seat_id:         座位 ID（来自 search_seats 的 POIs.id）
            begin_time:      预约开始时间
            duration_hours:  预约时长（小时）
            is_recommend:    是否通过系统推荐预约（默认 True）

        Returns:
            BookingResult
        """
        if not self._uid:
            return BookingResult(success=False, message="uid 未知，请先调用 load_seat_page")

        data = {
            "beginTime": self._to_timestamp(begin_time),
            "duration": duration_hours * 3600,
            "seats[0]": str(seat_id),
            "is_recommend": "1" if is_recommend else "0",
            "api_time": int(time.time()),
            "seatBookers[0]": str(self._uid),
        }

        logger.info(
            f"预约座位：seat_id={seat_id}, begin={begin_time.isoformat()}, "
            f"duration={duration_hours}h, uid={self._uid}"
        )

        try:
            resp = self._client.post(
                f"{self.BASE}/bookSeats",
                data=data,
                params=self._lab_params(),
            )
            resp_data = resp.json()

            code = resp_data.get("CODE", "")
            msg = resp_data.get("MESSAGE", "")
            inner = resp_data.get("DATA", {})

            if _is_ok_code(code) or _has_booking_id(inner):
                return BookingResult(
                    success=True,
                    message=msg or "预约成功",
                    booking_id=int(inner.get("bookingId", 0) or 0),
                )

            return BookingResult(success=False, message=msg or f"CODE={code}")

        except Exception as e:
            logger.exception("预约座位异常")
            return BookingResult(success=False, message=str(e))

    # ── 预约详情 ──────────────────────────────────────────

    def get_booking_info(self, booking_id: int) -> dict:
        """获取预约详情。

        Args:
            booking_id: 预约 ID

        Returns:
            API 响应 dict
        """
        params = self._lab_params(bookingId=str(booking_id), fromType="4")
        resp = self._client.get(f"{self.BASE}/bookingInfo", params=params)
        return resp.json()

    # ── 取消预约 ──────────────────────────────────────────

    def cancel_booking(self, booking_id: int) -> bool:
        """取消预约。

        Args:
            booking_id: 预约 ID

        Returns:
            是否取消成功
        """
        try:
            params = self._lab_params(bookingId=str(booking_id))
            resp = self._client.post(
                f"{self.BASE}/cancelBooking",
                params=params,
            )
            data = resp.json()
            return _is_ok_code(data.get("CODE", ""))
        except Exception as e:
            logger.exception("取消预约异常")
            return False

    def get_cancel_limit(self, booking_id: int) -> dict:
        """查询取消次数限制。

        Args:
            booking_id: 预约 ID

        Returns:
            API 响应 dict，包含 tips 等信息
        """
        params = self._lab_params(bookingId=str(booking_id))
        resp = self._client.get(f"{self.BASE}/cancelTimesLimit", params=params)
        return resp.json()

    # ── 签到码 ────────────────────────────────────────────

    def get_sign_qrcode(self) -> dict:
        """获取签到二维码数据。"""
        params = self._lab_params()
        resp = self._client.get(f"{self.BASE}/mySignQRCode", params=params)
        return resp.json()

    # ── 解锁全部座位（重置座位显示状态） ────────────────

    def unlock_all_seats(self) -> bool:
        """解锁所有座位（用于重置座位选择状态）。"""
        try:
            resp = self._client.post(
                f"{self.BASE}/unlockAllSeats",
                params=self._lab_params(),
            )
            data = resp.json()
            return _is_ok_code(data.get("CODE", ""))
        except Exception:
            return False

    # ── 获取未读消息数 ──────────────────────────────────

    def get_unread_message_count(self) -> int:
        """获取未读消息数。

        Returns:
            未读消息数量
        """
        try:
            resp = self._client.get(
                f"/Station/Station/getUnreadMessageCount",
                params=self._lab_params(),
            )
            data = resp.json()
            return int(data.get("DATA", {}).get("unread_message_number", 0))
        except Exception:
            return 0

    # ── 解析辅助方法 ──────────────────────────────────────

    def get_last_map_info(self) -> SeatMapInfo | None:
        """从最近一次 search_seats 响应中提取座位地图信息。

        Returns:
            SeatMapInfo（含平面图 URL、座位坐标等），无数据返回 None
        """
        resp = self._last_search_response
        if not resp:
            return None

        try:
            data = resp.get("data", {})
            info = data.get("info", {}) if isinstance(data, dict) else {}
            plan_url = info.get("plan", "")
            width = int(info.get("width", 0) or 0)
            height = int(info.get("height", 0) or 0)

            # 从 data 层提取所有座位坐标
            pois = data.get("POIs", []) if isinstance(data, dict) else []

            map_info = SeatMapInfo(
                room_name=info.get("title", ""),
                plan_url=plan_url,
                map_width=width,
                map_height=height,
                seats=pois,
            )

            # 也尝试从 content.children 中找平面图尺寸
            if not width or not height:
                content = resp.get("content", {})
                children = content.get("children", []) if isinstance(content, dict) else []
                for child in children:
                    if isinstance(child, dict) and child.get("ui_type") == "com.CatCon":
                        cat_child = child.get("children")
                        if isinstance(cat_child, dict):
                            sm = cat_child.get("seatMap", {})
                            i2 = sm.get("info", {}) if isinstance(sm, dict) else {}
                            if i2.get("plan"):
                                map_info.plan_url = i2.get("plan", "")
                                map_info.map_width = int(i2.get("width", 0) or 0)
                                map_info.map_height = int(i2.get("height", 0) or 0)
                                break

            return map_info

        except Exception as e:
            logger.exception(f"解析座位地图信息异常: {e}")
            return None

    def get_last_map_infos(self) -> dict[str, SeatMapInfo]:
        """从最近一次 search_seats 响应中按场馆提取地图信息。"""
        resp = self._last_search_response
        if not resp:
            return {}

        maps: dict[str, SeatMapInfo] = {}
        for key in ("content", "allContent", "DATA", "data"):
            payload = resp.get(key)
            if isinstance(payload, (dict, list)):
                _collect_map_infos(payload, maps)
        return maps

    @property
    def uid(self) -> Optional[int]:
        return self._uid

    @property
    def page_data(self) -> Optional[dict]:
        return self._page_data

    @property
    def last_search_response(self) -> Optional[dict]:
        return self._last_search_response

    @staticmethod
    def parse_seats_from_response(response: dict) -> list[SeatInfo]:
        """从搜索响应中提取座位列表。

        Args:
            response: search_seats POST 的响应 dict

        Returns:
            SeatInfo 列表
        """
        seats: list[SeatInfo] = []
        try:
            content = response.get("content", {})
            children = content.get("children", []) if isinstance(content, dict) else []

            logger.debug(
                f"parse_seats: content_type={type(content).__name__}, "
                f"children_count={len(children) if isinstance(children, list) else '?'}"
            )

            for i, child in enumerate(children):
                if not isinstance(child, dict):
                    continue
                ui_type = child.get("ui_type", "")
                logger.debug(f"parse_seats child[{i}]: ui_type={ui_type}, keys={list(child.keys())[:8]}")

                # 系统推荐座位
                if ui_type == "com.CatCon":
                    cat_children = child.get("children")
                    if isinstance(cat_children, dict):
                        _extract_seats_from_item(cat_children, seats)
                    elif isinstance(cat_children, list):
                        for cc in cat_children:
                            _extract_seats_from_item(cc, seats)

            # 新版接口搜索结果常放在 DATA/allContent 中，不再返回 content.children。
            for key in ("DATA", "data", "allContent"):
                payload = response.get(key)
                if isinstance(payload, (dict, list)):
                    _extract_seats_from_payload(payload, seats)
        except Exception as e:
            logger.exception(f"解析座位列表异常: {e}")

        seats = _dedupe_seats(seats)
        logger.info(f"parse_seats: 共解析到 {len(seats)} 个座位")
        return seats

    @staticmethod
    def parse_time_range(response: dict) -> dict:
        """从页面数据响应中提取时间范围信息。

        Returns:
            {
                "min_begin_hour": 7,
                "max_end_hour": 22,
                "max_date": datetime,
                "advance_date": datetime,
                "min_duration_hours": 1,
                "max_duration_hours": 15,
                "max_num": 4,
            }
        """
        data = response.get("data", {})
        rng = data.get("range", {})
        return {
            "min_begin_hour": rng.get("minBeginTime", 7),
            "max_end_hour": rng.get("maxEndTime", 22),
            "max_date": SeatAPI._from_timestamp(rng.get("max_date", 0)),
            "advance_date": SeatAPI._from_timestamp(rng.get("advance_date", 0)),
            "min_duration_hours": rng.get("min_duration", 1),
            "max_duration_hours": rng.get("max_duration", 15),
            "max_num": rng.get("max_num", 4),
        }


def _extract_seats_from_item(item: dict, seats: list[SeatInfo]) -> None:
    """从单个推荐/分类节点中提取座位。"""
    area_name = (
        item.get("roomName") or
        item.get("name") or
        item.get("title") or
        ""
    )
    seat_map = item.get("seatMap")
    if not isinstance(seat_map, dict):
        logger.debug(f"_extract_seats_from_item: seatMap 不是 dict, type={type(seat_map).__name__}, keys={list(item.keys())[:10]}")
        return

    pois = seat_map.get("POIs", [])
    logger.debug(f"_extract_seats_from_item: area={area_name}, POIs_count={len(pois) if isinstance(pois, list) else '?'}")

    # 也尝试从 children（全部座位）中提取
    children = item.get("children")
    if isinstance(children, list):
        for c in children:
            if isinstance(c, dict) and c.get("ui_type") == "ht.Seat.RecommendSeatItem":
                _extract_pois(c.get("seatMap", {}), seats, area_name, 1, 3)
    elif isinstance(children, dict):
        if children.get("ui_type") == "ht.Seat.RecommendSeatItem":
            _extract_pois(children.get("seatMap", {}), seats, area_name, 1, 3)

    _extract_pois(seat_map, seats, area_name)


def _collect_map_infos(payload: dict | list, maps: dict[str, SeatMapInfo], area_name: str = "") -> None:
    """递归收集每个场馆自己的平面图和坐标系信息。"""
    if isinstance(payload, list):
        for item in payload:
            _collect_map_infos(item, maps, area_name)
        return

    if not isinstance(payload, dict):
        return

    next_area = (
        payload.get("roomName") or
        payload.get("areaName") or
        payload.get("spaceName") or
        area_name
    )
    if not next_area and not _looks_like_seat_record(payload):
        next_area = payload.get("name") or payload.get("title") or ""
    next_area = str(next_area or "")

    seat_map = payload.get("seatMap")
    if isinstance(seat_map, dict):
        info = seat_map.get("info", {}) if isinstance(seat_map.get("info"), dict) else {}
        plan_url = info.get("plan") or seat_map.get("plan") or ""
        width = _to_int(info.get("width") or seat_map.get("width") or 0)
        height = _to_int(info.get("height") or seat_map.get("height") or 0)
        pois = seat_map.get("POIs", [])
        if next_area and (plan_url or pois):
            maps[next_area] = SeatMapInfo(
                room_name=next_area,
                plan_url=str(plan_url),
                map_width=width,
                map_height=height,
                seats=pois if isinstance(pois, list) else [],
            )

    for key in (
        "children", "allContent", "content", "data", "DATA",
        "items", "list", "rows", "seats", "seatList",
    ):
        child = payload.get(key)
        if isinstance(child, (dict, list)):
            _collect_map_infos(child, maps, next_area)


def _extract_pois(
    seat_map: dict,
    seats: list[SeatInfo],
    area_name: str,
    default_status: int = 0,
    status_priority: int | None = None,
) -> None:
    """从 seatMap 中提取 POIs。"""
    pois = seat_map.get("POIs", [])
    for poi in pois:
        _append_seat_from_record(poi, seats, area_name, default_status, status_priority)


def _extract_seats_from_payload(
    payload: dict | list,
    seats: list[SeatInfo],
    area_name: str = "",
    default_status: int = 0,
    status_priority: int | None = None,
) -> None:
    """递归兼容 DATA 中不同命名的座位列表结构。"""
    if isinstance(payload, list):
        for item in payload:
            _extract_seats_from_payload(item, seats, area_name, default_status, status_priority)
        return

    if not isinstance(payload, dict):
        return

    next_area = (
        payload.get("roomName") or
        payload.get("areaName") or
        payload.get("spaceName") or
        area_name
    )
    if not next_area and not _looks_like_seat_record(payload):
        next_area = payload.get("name") or payload.get("title") or ""

    if isinstance(payload.get("seatMap"), dict):
        _extract_seats_from_item(payload, seats)

    if isinstance(payload.get("POIs"), list):
        _extract_pois(payload, seats, str(next_area or ""), default_status, status_priority)

    if _looks_like_seat_record(payload):
        _append_seat_from_record(
            payload, seats, str(next_area or ""), default_status, status_priority
        )

    for key in ("availableSeats", "recommendSeats"):
        child = payload.get(key)
        if isinstance(child, (dict, list)):
            _extract_seats_from_payload(child, seats, str(next_area or ""), 1, 3)

    for key in ("unavailableSeats", "occupiedSeats", "disabledSeats"):
        child = payload.get(key)
        if isinstance(child, (dict, list)):
            _extract_seats_from_payload(child, seats, str(next_area or ""), 0, 3)

    for key in ("seats", "seatList", "items", "list", "rows", "data", "DATA", "children"):
        child = payload.get(key)
        if isinstance(child, (dict, list)):
            _extract_seats_from_payload(
                child, seats, str(next_area or ""), default_status, status_priority
            )


def _looks_like_seat_record(record: dict) -> bool:
    """判断一个 dict 是否像单个座位，而不是普通容器节点。"""
    id_keys = ("id", "seatId", "seat_id", "sid")
    label_keys = ("title", "name", "label", "seatName", "seatNo", "no")
    status_keys = (
        "state", "status", "isFree", "isAvailable", "available",
        "disabled", "enabled", "enable", "canBook", "canBooking",
        "bookable", "isBook", "isBooked", "isUsed",
    )
    return (
        any(k in record for k in id_keys) and
        (any(k in record for k in label_keys) or any(k in record for k in status_keys))
    )


def _append_seat_from_record(
    record: dict,
    seats: list[SeatInfo],
    area_name: str,
    default_status: int = 0,
    status_priority: int | None = None,
) -> None:
    """将接口中的单个座位记录归一化为 SeatInfo。"""
    seat_id = (
        record.get("id") or
        record.get("seatId") or
        record.get("seat_id") or
        record.get("sid") or
        0
    )
    try:
        seat_id = int(seat_id)
    except (TypeError, ValueError):
        return
    if seat_id <= 0:
        return

    seat_label = (
        record.get("title") or
        record.get("name") or
        record.get("label") or
        record.get("seatName") or
        record.get("seatNo") or
        record.get("no") or
        str(seat_id)
    )
    seats.append(SeatInfo(
        seat_id=seat_id,
        seat_label=str(seat_label),
        area_name=area_name or str(record.get("areaName") or record.get("roomName") or ""),
        status=_parse_seat_status(record, default_status),
        have_socket=_to_int(record.get("have_socket") or record.get("haveSocket") or 0),
        x=_to_int(record.get("x") or record.get("left") or record.get("posX") or 0),
        y=_to_int(record.get("y") or record.get("top") or record.get("posY") or 0),
        width=max(_to_int(record.get("w") or record.get("width") or record.get("seatWidth") or 2), 1),
        height=max(_to_int(record.get("h") or record.get("height") or record.get("seatHeight") or 2), 1),
        status_priority=(
            status_priority
            if status_priority is not None
            else _status_priority(record, default_status)
        ),
    ))


def _parse_seat_status(record: dict, default_status: int = 0) -> int:
    """把不同接口状态统一成 1=可选，0=不可选。"""
    false_means_available = {
        "disabled", "isBook", "isBooked", "isUsed",
    }
    for key in (
        "state", "status", "isFree", "isAvailable", "available",
        "disabled", "enabled", "enable", "canBook", "canBooking",
        "bookable", "isBook", "isBooked", "isUsed",
    ):
        if key not in record:
            continue
        value = record.get(key)
        if isinstance(value, bool):
            if key in false_means_available:
                return 0 if value else 1
            return 1 if value else 0
        if isinstance(value, (int, float)):
            int_value = int(value)
            if key == "state":
                return 1 if int_value in {0, 2} else 0
            if key in false_means_available:
                return 0 if int_value == 1 else 1
            return 1 if int_value == 1 else 0
        if isinstance(value, str):
            normalized = value.strip().lower()
            if key == "state":
                if normalized in {"0", "2"}:
                    return 1
                if normalized == "1":
                    return 0
            if key in false_means_available:
                if normalized in {"1", "true", "yes", "busy", "occupied", "reserved", "used", "不可用", "占用", "已预约"}:
                    return 0
                if normalized in {"0", "false", "no", "free", "available", "idle", "empty", "可用", "空闲"}:
                    return 1
            if normalized in {"1", "true", "yes", "free", "available", "idle", "empty", "可用", "空闲"}:
                return 1
            if normalized in {"0", "false", "no", "busy", "occupied", "reserved", "used", "不可用", "占用", "已预约"}:
                return 0
    return default_status


def _status_priority(record: dict, default_status: int = 0) -> int:
    """估算状态来源可信度；显式状态字段高于默认值。"""
    status_keys = (
        "state", "status", "isFree", "isAvailable", "available",
        "disabled", "enabled", "enable", "canBook", "canBooking",
        "bookable", "isBook", "isBooked", "isUsed",
    )
    if any(key in record for key in status_keys):
        return 2
    return 1 if default_status in (0, 1) else 0


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _dedupe_seats(seats: list[SeatInfo]) -> list[SeatInfo]:
    deduped: dict[int, SeatInfo] = {}
    for seat in seats:
        current = deduped.get(seat.seat_id)
        if current is None:
            deduped[seat.seat_id] = seat
            continue

        if seat.status_priority > current.status_priority:
            deduped[seat.seat_id] = seat
        elif seat.status_priority == current.status_priority and seat.status == 0:
            # 同可信度冲突时保守处理，避免把不可约座位标绿。
            deduped[seat.seat_id] = seat
    return list(deduped.values())
