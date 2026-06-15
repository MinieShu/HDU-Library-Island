"""
调度模块 - 定时任务管理器

管理自动预约的定时任务，支持：
- 在每日开放预约时间（20:00）自动触发
- 提前数秒启动以抢占先机
- 失败自动重试
- 任务状态回调
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Callable, Optional
import logging

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态。"""
    IDLE = "idle"
    WAITING = "waiting"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BookingTask:
    """预约任务定义。"""
    task_id: str
    task_type: str  # "seat" 或 "room"
    seat_key: str = ""
    seat_id: int = 0
    primary_seats: list[str] = field(default_factory=list)
    backup_seats: list[str] = field(default_factory=list)
    concurrent_requests: int = 3
    room_id: int = 0
    area_name: str = ""
    date_str: str = ""
    start_time: str = ""
    end_time: str = ""
    library_id: int | None = None
    category_id: int = 0   # zhishulib 空间类别 ID
    content_id: int = 0    # zhishulib 内容 ID
    duration_hours: int = 4  # 预约时长（小时）

    # 调度参数
    trigger_time: Optional[datetime] = None
    pre_trigger_seconds: int = 3
    max_retries: int = 30
    retry_interval_seconds: int = 1
    cancel_peers_on_success: bool = True

    # 状态
    status: TaskStatus = TaskStatus.IDLE
    status_message: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    retry_count: int = 0


class TaskScheduler:
    """定时任务调度器。

    使用后台线程在指定时间触发预约任务。
    支持高精度定时（提前 N 秒开始轮询），确保在开放时刻第一时间发送请求。
    """

    def __init__(self):
        self._tasks: dict[str, BookingTask] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_flags: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

        # 回调
        self.on_task_start: Optional[Callable] = None
        self.on_task_progress: Optional[Callable] = None
        self.on_task_complete: Optional[Callable] = None
        self._booking_func: Optional[Callable] = None

    def set_booking_function(self, func: Callable) -> None:
        """设置预约执行函数。

        func 签名: func(task: BookingTask) -> tuple[bool, str]
        """
        self._booking_func = func

    def add_task(self, task: BookingTask) -> str:
        """添加预约任务到调度队列。

        Args:
            task: 预约任务

        Returns:
            任务 ID
        """
        with self._lock:
            self._tasks[task.task_id] = task
            logger.info(f"添加任务：{task.task_id} ({task.task_type}) 触发时间={task.trigger_time}")
        return task.task_id

    def remove_task(self, task_id: str) -> bool:
        """移除任务。"""
        with self._lock:
            if task_id in self._tasks:
                self._stop_flags[task_id].set()
                del self._tasks[task_id]
                logger.info(f"移除任务：{task_id}")
                return True
            return False

    def get_task(self, task_id: str) -> Optional[BookingTask]:
        """获取任务详情。"""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[BookingTask]:
        """获取所有任务。"""
        return list(self._tasks.values())

    def start_task(self, task_id: str) -> bool:
        """启动一个任务的定时执行。

        Args:
            task_id: 任务 ID

        Returns:
            启动成功返回 True
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.error(f"任务不存在：{task_id}")
            return False

        if task.status in (TaskStatus.RUNNING, TaskStatus.WAITING):
            logger.warning(f"任务已在运行中：{task_id}")
            return False

        stop_event = threading.Event()
        self._stop_flags[task_id] = stop_event

        thread = threading.Thread(
            target=self._run_task,
            args=(task, stop_event),
            daemon=True,
            name=f"scheduler-{task_id}",
        )
        self._threads[task_id] = thread
        thread.start()

        logger.info(f"启动任务调度：{task_id}")
        return True

    def run_task_now(self, task_id: str) -> bool:
        """立即执行一个任务，不等待开放时间。"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.error(f"任务不存在：{task_id}")
                return False

            if task.status == TaskStatus.RUNNING:
                logger.warning(f"任务正在执行中：{task_id}")
                return False

            existing_stop_event = self._stop_flags.get(task_id)
            if existing_stop_event:
                existing_stop_event.set()

            immediate_task = replace(
                task,
                status=TaskStatus.RUNNING,
                status_message="正在立即执行预约...",
                finished_at=None,
                retry_count=0,
            )
            self._tasks[task_id] = immediate_task

            stop_event = threading.Event()
            self._stop_flags[task_id] = stop_event

        thread = threading.Thread(
            target=self._run_task_immediately,
            args=(immediate_task, stop_event),
            daemon=True,
            name=f"scheduler-now-{task_id}",
        )
        self._threads[task_id] = thread
        thread.start()

        logger.info(f"立即执行任务：{task_id}")
        return True

    def cancel_task(self, task_id: str) -> bool:
        """取消正在等待或运行中的任务。

        Args:
            task_id: 任务 ID

        Returns:
            取消成功返回 True
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        stop_event = self._stop_flags.get(task_id)
        if stop_event:
            stop_event.set()

        task.status = TaskStatus.CANCELLED
        task.finished_at = datetime.now()
        task.status_message = "已取消"

        logger.info(f"取消任务：{task_id}")
        return True

    def _run_task_immediately(self, task: BookingTask, stop_event: threading.Event) -> None:
        """后台线程中立即执行预约任务。"""
        task.status = TaskStatus.RUNNING
        task.status_message = "正在立即执行预约..."
        task.retry_count = 0
        task.finished_at = None

        if self.on_task_start:
            self.on_task_start(task.task_id)

        try:
            self._execute_with_retry(task, stop_event)
        except Exception as e:
            logger.exception(f"[{task.task_id}] 立即执行异常：{e}")
            task.status = TaskStatus.FAILED
            task.status_message = f"异常：{e}"
            task.finished_at = datetime.now()
        finally:
            if self.on_task_complete:
                self.on_task_complete(task.task_id, task.status.value, task.status_message)

    def schedule_daily_task(
        self,
        task_id: str,
        task_type: str,
        seat_key: str = "",
        seat_id: int = 0,
        primary_seats: list[str] | None = None,
        backup_seats: list[str] | None = None,
        concurrent_requests: int = 3,
        room_id: int = 0,
        area_name: str = "",
        start_time: str = "08:00",
        end_time: str = "12:00",
        library_id: int | None = None,
        open_time: str = "20:00:00",
        pre_trigger_seconds: int = 3,
        max_retries: int = 30,
        retry_interval_seconds: int = 1,
        cancel_peers_on_success: bool = True,
        category_id: int = 0,
        content_id: int = 0,
        duration_hours: int = 4,
    ) -> BookingTask:
        """创建一个每日定时预约任务。

        Args:
            task_id: 任务唯一 ID
            task_type: 任务类型 "seat" 或 "room"
            seat_key: 座位 key（座位预约时使用）
            seat_id: 座位 ID
            room_id: 房间 ID（场地预约时使用）
            area_name: 区域名称
            start_time: 预约开始时间 HH:MM
            end_time: 预约结束时间 HH:MM
            library_id: 图书馆 ID
            open_time: 系统开放预约的时间 HH:MM:SS
            pre_trigger_seconds: 提前触发秒数
            max_retries: 最大重试次数
            retry_interval_seconds: 重试间隔秒数

        Returns:
            BookingTask
        """
        # 计算今天的触发时间
        now = datetime.now()
        h, m, s = map(int, open_time.split(":"))
        trigger_time = now.replace(hour=h, minute=m, second=s, microsecond=0)

        # 如果今天的触发时间已过，则设为明天
        if trigger_time <= now:
            trigger_time += timedelta(days=1)

        # 预约日期：如果触发明天的预约，则日期为明天
        # 系统在每晚 20:00 开放后两天的预约
        booking_date = trigger_time + timedelta(days=1)

        task = BookingTask(
            task_id=task_id,
            task_type=task_type,
            seat_key=seat_key,
            seat_id=seat_id,
            primary_seats=primary_seats or [],
            backup_seats=backup_seats or [],
            concurrent_requests=concurrent_requests,
            room_id=room_id,
            area_name=area_name,
            date_str=booking_date.strftime("%Y-%m-%d"),
            start_time=start_time,
            end_time=end_time,
            library_id=library_id,
            category_id=category_id,
            content_id=content_id,
            duration_hours=duration_hours,
            trigger_time=trigger_time,
            pre_trigger_seconds=pre_trigger_seconds,
            max_retries=max_retries,
            retry_interval_seconds=retry_interval_seconds,
            cancel_peers_on_success=cancel_peers_on_success,
        )

        self.add_task(task)
        self.start_task(task_id)
        return task

    def _run_task(self, task: BookingTask, stop_event: threading.Event) -> None:
        """在后台线程中执行任务调度。

        流程：
        1. 等待直到触发时间 - 提前秒数
        2. 在触发时间前精确等到开放时刻
        3. 执行预约，失败则重试
        """
        task.status = TaskStatus.WAITING
        task.status_message = "等待触发时间..."
        logger.info(f"[{task.task_id}] 开始等待，触发时间={task.trigger_time}")

        if self.on_task_start:
            self.on_task_start(task.task_id)

        try:
            # 阶段 1: 粗粒度等待（等到达触发时间附近）
            self._wait_until_near_trigger(task, stop_event)

            # 阶段 2: 精确定时（在触发时间前精确等到目标时刻）
            if not stop_event.is_set():
                self._precise_wait(task.trigger_time, stop_event, task.pre_trigger_seconds)

            # 阶段 3: 执行预约（带重试）
            if not stop_event.is_set():
                task.status = TaskStatus.RUNNING
                task.status_message = "正在执行预约..."
                self._execute_with_retry(task, stop_event)

        except Exception as e:
            logger.exception(f"[{task.task_id}] 任务执行异常：{e}")
            task.status = TaskStatus.FAILED
            task.status_message = f"异常：{e}"
            task.finished_at = datetime.now()

        finally:
            if self.on_task_complete:
                self.on_task_complete(task.task_id, task.status.value, task.status_message)

    def _wait_until_near_trigger(self, task: BookingTask, stop_event: threading.Event) -> None:
        """粗粒度等待：等到距离触发时间约 30 秒。"""
        while not stop_event.is_set():
            now = datetime.now()
            seconds_until = (task.trigger_time - now).total_seconds()
            # 加入提前量
            effective_seconds = seconds_until - task.pre_trigger_seconds

            if effective_seconds <= 30:
                break

            # 每次休眠不超过 5 秒
            sleep_time = min(effective_seconds - 25, 5.0)
            if sleep_time > 0:
                remaining_min = int(effective_seconds / 60)
                task.status_message = f"距离触发还有约 {remaining_min} 分钟..."
                logger.debug(f"[{task.task_id}] 等待中，剩余 {effective_seconds:.0f} 秒")
                stop_event.wait(sleep_time)

        if stop_event.is_set():
            task.status = TaskStatus.CANCELLED
            task.status_message = "已取消"

    def _precise_wait(
        self,
        trigger_time: datetime,
        stop_event: threading.Event,
        pre_seconds: int = 3,
    ) -> None:
        """精确定时：在触发时间前精确等待。

        在最后几秒使用高频率轮询，确保在系统开放的第一时间发出请求。
        """
        target_time = trigger_time

        while not stop_event.is_set():
            now = datetime.now()
            diff = (target_time - now).total_seconds()

            if diff <= 0:
                # 刚好到达或已过触发时间
                break

            if diff > 0.5:
                # 距离还远，休眠 100ms
                stop_event.wait(0.1)
            elif diff > 0.1:
                # 接近了，休眠 20ms
                stop_event.wait(0.02)
            elif diff > 0.01:
                # 非常接近，休眠 5ms
                stop_event.wait(0.005)
            else:
                # 最后几毫秒，忙等
                pass

        logger.info(f"精确定时完成，当前时间={datetime.now()}")

    def _execute_with_retry(self, task: BookingTask, stop_event: threading.Event) -> None:
        """执行预约，失败时重试。"""
        if not self._booking_func:
            task.status = TaskStatus.FAILED
            task.status_message = "未设置预约执行函数"
            return

        for attempt in range(task.max_retries):
            if stop_event.is_set():
                task.status = TaskStatus.CANCELLED
                task.status_message = "已取消"
                return

            task.retry_count = attempt + 1
            task.status_message = f"正在预约... (第 {attempt + 1}/{task.max_retries} 次)"

            if self.on_task_progress:
                self.on_task_progress(task.task_id, attempt + 1, task.max_retries)

            logger.info(f"[{task.task_id}] 尝试预约 #{attempt + 1}")

            success, message = self._booking_func(task)

            if stop_event.is_set():
                task.status = TaskStatus.CANCELLED
                task.status_message = "已取消"
                task.finished_at = datetime.now()
                return

            if success:
                task.status = TaskStatus.SUCCESS
                task.status_message = message
                task.finished_at = datetime.now()
                logger.info(f"[{task.task_id}] 预约成功！{message}")
                if task.cancel_peers_on_success:
                    self._cancel_peer_tasks(task)
                return

            logger.warning(f"[{task.task_id}] 预约失败 #{attempt + 1}: {message}")
            task.status_message = f"失败 (第{attempt + 1}次): {message}"

            if attempt < task.max_retries - 1:
                stop_event.wait(task.retry_interval_seconds)

        # 全部重试失败
        task.status = TaskStatus.FAILED
        task.status_message = f"预约失败（已重试 {task.max_retries} 次）"
        task.finished_at = datetime.now()
        logger.error(f"[{task.task_id}] 预约最终失败")

    def _cancel_peer_tasks(self, winner: BookingTask) -> None:
        """一个任务成功后，取消其它同类型座位任务，避免继续提交。"""
        with self._lock:
            peers = [
                task for task in self._tasks.values()
                if task.task_id != winner.task_id
                and task.task_type == winner.task_type
                and task.status in (TaskStatus.WAITING, TaskStatus.RUNNING)
            ]

        for task in peers:
            stop_event = self._stop_flags.get(task.task_id)
            if stop_event:
                stop_event.set()
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.now()
            task.status_message = f"已有任务成功，自动停止：{winner.task_id}"
            logger.info(f"[{winner.task_id}] 成功后取消同类任务：{task.task_id}")

    def shutdown(self) -> None:
        """关闭调度器，取消所有待执行的任务。"""
        logger.info("关闭调度器...")
        for task_id in list(self._tasks.keys()):
            self.cancel_task(task_id)
