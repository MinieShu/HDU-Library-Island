"""
API 模块 - 场地/空间预约

处理杭电图书馆研讨间、讨论室等场地的预约。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional
from dataclasses import dataclass, field
import logging

from .client import APIClient

logger = logging.getLogger(__name__)


@dataclass
class RoomInfo:
    """场地/房间信息。"""
    room_id: int
    name: str
    floor: str
    capacity: int
    facilities: list[str] = field(default_factory=list)
    status: str = "unknown"
    available_segments: list[dict] = field(default_factory=list)


@dataclass
class RoomBookingResult:
    """场地预约结果。"""
    success: bool
    message: str
    booking_id: Optional[int] = None
    room_name: Optional[str] = None
    date_str: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class RoomAPI:
    """杭电图书馆场地/空间预约 API。"""

    ROOMS_PATH = "/api/v2/spaces"
    ROOM_DETAIL_PATH = "/api/v2/spaces"
    ROOM_BOOK_PATH = "/api/v2/spaces/book"
    ROOM_CANCEL_PATH = "/api/v2/spaces/cancel"
    ROOM_MY_BOOKINGS_PATH = "/api/v2/profile/room_books"
    ROOM_DAYS_PATH = "/api/v2/space_days"
    ROOM_TIME_BUCKETS_PATH = "/api/v2/space_time_buckets"

    def __init__(self, client: APIClient):
        self._client = client

    def get_available_days(self) -> list[str]:
        """获取可预约的日期列表。"""
        try:
            resp = self._client.get(self.ROOM_DAYS_PATH)
            if resp.status_code == 200:
                data = resp.json()
                days = data.get("data") or data.get("days") or []
                return [d if isinstance(d, str) else d.get("date", "") for d in days]
            return []
        except Exception as e:
            logger.exception(f"获取可预约日期异常：{e}")
            return []

    def get_time_buckets(self, date_str: str | None = None) -> list[dict]:
        """获取可预约的时间段列表。

        Returns:
            [{"start": "08:00", "end": "11:00"}, ...]
        """
        params = {}
        if date_str:
            params["date"] = date_str

        try:
            resp = self._client.get(self.ROOM_TIME_BUCKETS_PATH, params=params)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data") or data.get("buckets") or []
            return []
        except Exception as e:
            logger.exception(f"获取时间段异常：{e}")
            return []

    def get_rooms(
        self,
        area_id: int | None = None,
        date_str: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        min_capacity: int | None = None,
    ) -> list[RoomInfo]:
        """查询可用场地。

        Args:
            area_id: 区域 ID
            date_str: 日期 YYYY-MM-DD
            start_time: 开始时间 HH:MM
            end_time: 结束时间 HH:MM
            min_capacity: 最小容纳人数

        Returns:
            场地列表
        """
        params: dict[str, Any] = {}
        if area_id:
            params["area"] = area_id
        if date_str:
            params["date"] = date_str
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        try:
            resp = self._client.get(self.ROOMS_PATH, params=params)
            if resp.status_code == 200:
                data = resp.json()
                rooms_data = data.get("data") or data.get("spaces") or []
                rooms = self._parse_rooms(rooms_data)

                if min_capacity is not None:
                    rooms = [r for r in rooms if r.capacity >= min_capacity]

                return rooms
            return []
        except Exception as e:
            logger.exception(f"查询场地异常：{e}")
            return []

    def get_room_detail(self, room_id: int) -> Optional[RoomInfo]:
        """获取单个场地的详细信息。"""
        try:
            resp = self._client.get(f"{self.ROOM_DETAIL_PATH}/{room_id}")
            if resp.status_code == 200:
                data = resp.json()
                room_data = data.get("data") or data
                rooms = self._parse_rooms([room_data])
                return rooms[0] if rooms else None
            return None
        except Exception as e:
            logger.exception(f"获取场地详情异常：{e}")
            return None

    def book_room(
        self,
        room_id: int,
        date_str: str,
        start_time: str,
        end_time: str,
        title: str = "学习",
        attendees: int = 1,
        remark: str = "",
    ) -> RoomBookingResult:
        """预约场地/研讨间。

        Args:
            room_id: 场地 ID
            date_str: 日期 YYYY-MM-DD
            start_time: 开始时间 HH:MM
            end_time: 结束时间 HH:MM
            title: 用途说明
            attendees: 使用人数
            remark: 备注

        Returns:
            RoomBookingResult
        """
        logger.info(f"预约场地：room_id={room_id}, {date_str} {start_time}-{end_time}")

        payload = {
            "spaceId": room_id,
            "date": date_str,
            "startTime": start_time,
            "endTime": end_time,
            "title": title,
            "attendees": attendees,
            "remark": remark,
        }

        try:
            resp = self._client.post(self.ROOM_BOOK_PATH, json=payload)
            data = resp.json()

            if resp.status_code == 200 and (data.get("code") == 0 or data.get("status") == "success"):
                booking_data = data.get("data") or data
                return RoomBookingResult(
                    success=True,
                    message="预约成功",
                    booking_id=booking_data.get("id") or booking_data.get("bookingId"),
                    room_name=booking_data.get("roomName") or str(room_id),
                    date_str=date_str,
                    start_time=start_time,
                    end_time=end_time,
                )

            error_msg = data.get("message") or data.get("msg") or f"HTTP {resp.status_code}"
            return RoomBookingResult(success=False, message=error_msg)

        except Exception as e:
            return RoomBookingResult(success=False, message=str(e))

    def cancel_room_booking(self, booking_id: int) -> bool:
        """取消场地预约。"""
        try:
            resp = self._client.post(f"{self.ROOM_CANCEL_PATH}/{booking_id}")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("code") == 0 or data.get("status") == "success"
            return False
        except Exception as e:
            logger.exception(f"取消场地预约异常：{e}")
            return False

    def get_my_room_bookings(self) -> list[dict]:
        """获取当前用户的场地预约记录。"""
        try:
            resp = self._client.get(self.ROOM_MY_BOOKINGS_PATH)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data") or data.get("books") or []
            return []
        except Exception as e:
            logger.exception(f"获取场地预约记录异常：{e}")
            return []

    def _parse_rooms(self, data: list) -> list[RoomInfo]:
        """解析场地列表。"""
        rooms = []
        for item in data:
            room = RoomInfo(
                room_id=item.get("id") or item.get("spaceId", 0),
                name=item.get("name") or item.get("label", ""),
                floor=str(item.get("floor") or ""),
                capacity=item.get("capacity") or item.get("maxPeople", 0),
                facilities=item.get("facilities") or item.get("equipment") or [],
                status=item.get("status") or item.get("state", "unknown"),
                available_segments=item.get("segments") or item.get("availableSegments") or [],
            )
            rooms.append(room)
        return rooms
