#!/usr/bin/env python3
"""
Web API entrypoint for the HDU library booking app.

This keeps the existing Python booking logic and exposes a small local HTTP API
for the React frontend.
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api import APIClient, AuthAPI, RoomAPI, SeatAPI
from api.seats import SeatInfo
from scheduler import BookingTask, TaskScheduler, TaskStatus
from utils.config import Config
from utils.logger import setup_logger

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))
DEFAULT_BASE_URL = "https://hdu.huitu.zhishulib.com"
KNOWN_AREAS = [
    {"category_id": 591, "content_id": 3, "name": "自习室", "space": ""},
    {"category_id": 591, "content_id": 115, "name": "生活区（求新书院&守正书院）", "space": ""},
    {"category_id": 591, "content_id": 76, "name": "阅览室（3-11楼）", "space": ""},
    {"category_id": 591, "content_id": 117, "name": "五楼特藏区", "space": ""},
    {"category_id": 591, "content_id": 39, "name": "教师休息室", "space": ""},
]


class LoginRequest(BaseModel):
    student_id: str = Field(alias="studentId")
    password: str
    remember: bool = False
    auto_login: bool = Field(False, alias="autoLogin")
    base_url: str = Field(DEFAULT_BASE_URL, alias="baseUrl")


class LoadAreaRequest(BaseModel):
    category_id: int = Field(alias="categoryId")
    content_id: int = Field(alias="contentId")


class SeatSearchRequest(LoadAreaRequest):
    date: str
    start_time: str = Field(alias="startTime")
    duration_hours: int = Field(4, alias="durationHours")


class BookSeatRequest(BaseModel):
    seat_id: int = Field(alias="seatId")
    date: str
    start_time: str = Field(alias="startTime")
    duration_hours: int = Field(4, alias="durationHours")


class CreateTaskRequest(LoadAreaRequest):
    open_time: str = Field("20:00:00", alias="openTime")
    start_time: str = Field("08:00", alias="startTime")
    end_time: str = Field("22:00", alias="endTime")
    pre_trigger_seconds: int = Field(3, alias="preTriggerSeconds")
    max_retries: int = Field(30, alias="maxRetries")
    retry_interval_seconds: int = Field(1, alias="retryIntervalSeconds")
    concurrent_requests: int = Field(3, alias="concurrentRequests")
    primary_seats: list[str] = Field(default_factory=list, alias="primarySeats")
    backup_seats: list[str] = Field(default_factory=list, alias="backupSeats")


class AppState:
    def __init__(self) -> None:
        self.config = Config()
        self.config.load()
        self.client: APIClient | None = None
        self.auth: AuthAPI | None = None
        self.seat_api: SeatAPI | None = None
        self.room_api: RoomAPI | None = None
        self.scheduler = TaskScheduler()
        self.scheduler.set_booking_function(self.execute_booking)
        self.lock = Lock()

    def require_login(self) -> None:
        if not self.client or not self.auth or not self.seat_api:
            raise HTTPException(status_code=401, detail="请先登录")

    def execute_booking(self, task: BookingTask) -> tuple[bool, str]:
        self.require_login()
        if not self.seat_api:
            return False, "未设置座位 API"

        try:
            cat_id = task.category_id or 591
            cont_id = task.content_id or 3
            if not self.seat_api.uid:
                self.seat_api.load_seat_page(cat_id, cont_id)
            if not self.seat_api.uid:
                return False, "无法获取用户 uid"

            start_dt = datetime.strptime(
                f"{task.date_str} {task.start_time}", "%Y-%m-%d %H:%M"
            ).replace(tzinfo=BEIJING_TZ)
            duration = task.duration_hours or _duration_hours(task.start_time, task.end_time)

            resp = self.seat_api.search_seats(cat_id, cont_id, start_dt, duration)
            seats = SeatAPI.parse_seats_from_response(resp)
            available = [seat for seat in seats if seat.status == 1]
            if not available:
                return False, f"没有可用座位（共 {len(seats)} 个）"

            primary = _resolve_seat_candidates(task.primary_seats, available)
            backup = _resolve_seat_candidates(task.backup_seats, available)
            if not primary and not backup:
                primary = available

            success, message = _try_book_candidates(
                self.seat_api,
                primary,
                start_dt,
                duration,
                task.concurrent_requests,
                "主选",
            )
            if success:
                return True, message

            if backup:
                backup_success, backup_message = _try_book_candidates(
                    self.seat_api,
                    backup,
                    start_dt,
                    duration,
                    task.concurrent_requests,
                    "备选",
                )
                if backup_success:
                    return True, backup_message
                return False, f"主选失败：{message}；备选失败：{backup_message}"

            return False, message
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("执行预约异常")
            return False, str(exc)


state = AppState()
app = FastAPI(title="HDU Library AutoBook API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "loggedIn": bool(state.auth and state.auth.is_logged_in)}


@app.post("/api/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    with state.lock:
        client = APIClient(base_url=payload.base_url or DEFAULT_BASE_URL)
        auth = AuthAPI(client)
        success = auth.login_by_password(payload.student_id, payload.password)
        if not success:
            raise HTTPException(status_code=401, detail="登录失败，请检查学号和密码")

        state.client = client
        state.auth = auth
        state.seat_api = SeatAPI(client)
        state.room_api = RoomAPI(client)

        if payload.remember:
            state.config.set("auth.student_id", payload.student_id)
            state.config.set("auth.password", payload.password)
            state.config.set("auth.remember", True)
        else:
            state.config.set("auth.password", "")
            state.config.set("auth.remember", False)
        state.config.set("auth.auto_login", payload.auto_login)
        state.config.set("api.base_url", payload.base_url or DEFAULT_BASE_URL)
        state.config.save()

    return {"ok": True, "user": {"studentId": payload.student_id}}


@app.post("/api/logout")
def logout() -> dict[str, bool]:
    if state.auth:
        state.auth.logout()
    state.client = None
    state.auth = None
    state.seat_api = None
    state.room_api = None
    return {"ok": True}


@app.get("/api/config")
def config() -> dict[str, Any]:
    return {
        "studentId": state.config.get("auth.student_id", ""),
        "remember": state.config.get("auth.remember", False),
        "autoLogin": state.config.get("auth.auto_login", False),
        "baseUrl": state.config.get("api.base_url", DEFAULT_BASE_URL),
    }


@app.get("/api/areas")
def areas() -> dict[str, Any]:
    state.require_login()
    assert state.seat_api
    try:
        items = state.seat_api.get_categories()
        usable = [
            {
                "categoryId": item.get("category_id", 0),
                "contentId": item.get("content_id", 0),
                "name": item.get("name", ""),
                "space": item.get("space", ""),
                "disabled": item.get("disabled", False),
            }
            for item in items
            if not item.get("disabled")
        ]
        return {"areas": usable or _known_areas()}
    except Exception as exc:
        logger.warning("区域 API 失败，使用本地预设", exc_info=True)
        return {"areas": _known_areas(), "warning": str(exc)}


@app.post("/api/areas/load")
def load_area(payload: LoadAreaRequest) -> dict[str, Any]:
    state.require_login()
    assert state.seat_api
    data = state.seat_api.load_seat_page(payload.category_id, payload.content_id)
    time_range = SeatAPI.parse_time_range(data)
    return {
        "ok": True,
        "uidReady": bool(state.seat_api.uid),
        "timeRange": _serialize_time_range(time_range),
    }


@app.post("/api/seats/search")
def search_seats(payload: SeatSearchRequest) -> dict[str, Any]:
    state.require_login()
    assert state.seat_api
    if not state.seat_api.uid:
        state.seat_api.load_seat_page(payload.category_id, payload.content_id)

    start_dt = datetime.strptime(
        f"{payload.date} {payload.start_time}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=BEIJING_TZ)
    resp = state.seat_api.search_seats(
        payload.category_id,
        payload.content_id,
        start_dt,
        payload.duration_hours,
    )
    seats = SeatAPI.parse_seats_from_response(resp)
    maps = state.seat_api.get_last_map_infos()
    available = sum(1 for seat in seats if seat.status == 1)
    return {
        "seats": [_serialize_seat(seat) for seat in seats],
        "availableCount": available,
        "venueCount": len({seat.area_name for seat in seats}),
        "maps": {name: asdict(info) for name, info in maps.items()},
    }


@app.post("/api/seats/book")
def book_seat(payload: BookSeatRequest) -> dict[str, Any]:
    state.require_login()
    assert state.seat_api
    start_dt = datetime.strptime(
        f"{payload.date} {payload.start_time}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=BEIJING_TZ)
    result = state.seat_api.book_seat(
        payload.seat_id,
        start_dt,
        payload.duration_hours,
    )
    return asdict(result)


@app.post("/api/tasks")
def create_task(payload: CreateTaskRequest) -> dict[str, Any]:
    state.require_login()
    task_id = f"seat_{datetime.now().strftime('%H%M%S_%f')}"
    duration = _duration_hours(payload.start_time, payload.end_time)
    task = state.scheduler.schedule_daily_task(
        task_id=task_id,
        task_type="seat",
        area_name=f"座位-{payload.start_time}-{payload.end_time}",
        start_time=payload.start_time,
        end_time=payload.end_time,
        open_time=payload.open_time,
        pre_trigger_seconds=payload.pre_trigger_seconds,
        max_retries=payload.max_retries,
        retry_interval_seconds=payload.retry_interval_seconds,
        primary_seats=payload.primary_seats,
        backup_seats=payload.backup_seats,
        concurrent_requests=payload.concurrent_requests,
        category_id=payload.category_id,
        content_id=payload.content_id,
        duration_hours=duration,
    )
    return {"task": _serialize_task(task)}


@app.get("/api/tasks")
def list_tasks() -> dict[str, Any]:
    return {"tasks": [_serialize_task(task) for task in state.scheduler.get_all_tasks()]}


@app.post("/api/tasks/{task_id}/start")
def start_task(task_id: str) -> dict[str, bool]:
    return {"ok": state.scheduler.start_task(task_id)}


@app.post("/api/tasks/{task_id}/run-now")
def run_task_now(task_id: str) -> dict[str, bool]:
    state.require_login()
    ok = state.scheduler.run_task_now(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="任务无法立即执行，请确认任务存在且未在运行中")
    return {"ok": True}


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, bool]:
    return {"ok": state.scheduler.cancel_task(task_id)}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str) -> dict[str, bool]:
    return {"ok": state.scheduler.remove_task(task_id)}


def _known_areas() -> list[dict[str, Any]]:
    return [
        {
            "categoryId": item["category_id"],
            "contentId": item["content_id"],
            "name": item["name"],
            "space": item["space"],
            "disabled": False,
        }
        for item in KNOWN_AREAS
    ]


def _serialize_seat(seat: SeatInfo) -> dict[str, Any]:
    return {
        "seatId": seat.seat_id,
        "seatLabel": seat.seat_label,
        "areaName": seat.area_name,
        "status": seat.status,
        "haveSocket": seat.have_socket,
        "x": seat.x,
        "y": seat.y,
        "width": seat.width,
        "height": seat.height,
    }


def _serialize_task(task: BookingTask) -> dict[str, Any]:
    return {
        "taskId": task.task_id,
        "taskType": task.task_type,
        "date": task.date_str,
        "startTime": task.start_time,
        "endTime": task.end_time,
        "triggerTime": task.trigger_time.isoformat() if task.trigger_time else "",
        "status": task.status.value,
        "statusMessage": task.status_message,
        "retryCount": task.retry_count,
        "maxRetries": task.max_retries,
        "primarySeats": task.primary_seats,
        "backupSeats": task.backup_seats,
        "concurrentRequests": task.concurrent_requests,
        "createdAt": task.created_at.isoformat(),
    }


def _serialize_time_range(time_range: dict[str, Any]) -> dict[str, Any]:
    result = dict(time_range)
    for key in ("max_date", "advance_date"):
        value = result.get(key)
        if isinstance(value, datetime):
            result[key] = value.date().isoformat()
    return result


def _duration_hours(start_time: str, end_time: str) -> int:
    start_h, start_m = map(int, start_time.split(":")[:2])
    end_h, end_m = map(int, end_time.split(":")[:2])
    minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
    return max(1, round(minutes / 60))


def _resolve_seat_candidates(tokens: list[str], available: list[SeatInfo]) -> list[SeatInfo]:
    resolved = []
    used_ids = set()
    for token in tokens:
        area_hint = ""
        label = token.strip()
        if "|" in label:
            area_hint, label = [part.strip() for part in label.split("|", 1)]

        for seat in available:
            if area_hint and area_hint not in (seat.area_name or ""):
                continue
            if label == str(seat.seat_id) or label == seat.seat_label:
                if seat.seat_id not in used_ids:
                    used_ids.add(seat.seat_id)
                    resolved.append(seat)
    return resolved


def _try_book_candidates(
    seat_api: SeatAPI,
    candidates: list[SeatInfo],
    start_dt: datetime,
    duration: int,
    concurrent_requests: int,
    group_name: str,
) -> tuple[bool, str]:
    if not candidates:
        return False, f"{group_name}没有匹配到可预约座位"

    max_workers = max(1, min(concurrent_requests or 1, len(candidates)))
    last_message = ""
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_to_seat = {
            executor.submit(seat_api.book_seat, seat.seat_id, start_dt, duration): seat
            for seat in candidates
        }
        for future in as_completed(future_to_seat):
            seat = future_to_seat[future]
            try:
                result = future.result()
            except Exception as exc:
                last_message = f"{seat.seat_label}: {exc}"
                continue
            if result.success:
                for pending in future_to_seat:
                    if pending is not future:
                        pending.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                return True, f"{group_name}预约成功：{seat.area_name} {seat.seat_label} #{result.booking_id}"
            last_message = f"{seat.seat_label}: {result.message}"
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return False, last_message or f"{group_name}全部失败"


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 HDU Library Web API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logger(verbose=args.verbose)
    import uvicorn

    uvicorn.run("hdu_library_autobook.web_api:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
