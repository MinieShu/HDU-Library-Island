"""
GUI 模块 - 定时调度面板

管理自动预约的定时任务，支持每日定时抢座。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QTimeEdit, QSpinBox, QGroupBox, QComboBox,
    QMessageBox, QCheckBox, QRadioButton, QButtonGroup,
    QTextEdit, QTabWidget, QFrame, QGridLayout, QListWidget,
    QListWidgetItem, QSplitter,
)
from PyQt6.QtCore import Qt, QTime, QTimer
from PyQt6.QtGui import QColor, QPixmap, QFont, QPen, QBrush

from api import APIClient, SeatAPI, RoomAPI, SeatMapInfo
from scheduler import TaskScheduler, BookingTask, TaskStatus
from .seat_panel import KNOWN_AREAS, SeatMapView

CANDIDATE_PRIMARY_COLOR = QColor("#d93025")
CANDIDATE_BACKUP_COLOR = QColor("#1a73e8")

logger = logging.getLogger(__name__)


class SchedulePanel(QWidget):
    """定时调度管理面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scheduler = TaskScheduler()
        self._seat_api: SeatAPI | None = None
        self._room_api: RoomAPI | None = None
        self._candidate_primary: dict[str, str] = {}
        self._candidate_backup: dict[str, str] = {}
        self._candidate_seats_by_id = {}
        self._candidate_loaded_seats = []
        self._candidate_map_infos: dict[str, SeatMapInfo] = {}

        # 注册回调
        self._scheduler.on_task_start = self._on_task_start
        self._scheduler.on_task_progress = self._on_task_progress
        self._scheduler.on_task_complete = self._on_task_complete

        # 注册预约执行函数
        self._scheduler.set_booking_function(self._execute_booking)

        self._setup_ui()

        # 定时刷新任务列表
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh_task_table)
        self._refresh_timer.start(2000)

    def set_api_client(self, client: APIClient, seat_api: SeatAPI, room_api: RoomAPI):
        """设置 API 客户端。"""
        self._seat_api = seat_api
        self._room_api = room_api

    def _setup_ui(self):
        """初始化界面。"""
        layout = QVBoxLayout(self)

        # ===== 新建定时任务 =====
        create_group = QGroupBox("新建定时预约")
        create_layout = QVBoxLayout(create_group)

        # 任务类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("任务类型："))
        self._task_type_group = QButtonGroup(self)
        self._seat_radio = QRadioButton("座位预约")
        self._room_radio = QRadioButton("场地预约")
        self._seat_radio.setChecked(True)
        self._task_type_group.addButton(self._seat_radio, 1)
        self._task_type_group.addButton(self._room_radio, 2)
        type_layout.addWidget(self._seat_radio)
        self._room_radio.setVisible(False)
        type_layout.addStretch()
        create_layout.addLayout(type_layout)

        # 预约时间
        time_grid = QGridLayout()

        time_grid.addWidget(QLabel("系统开放时间："), 0, 0)
        self._open_time = QTimeEdit()
        self._open_time.setTime(QTime(20, 0, 0))
        self._open_time.setDisplayFormat("HH:mm:ss")
        time_grid.addWidget(self._open_time, 0, 1)

        time_grid.addWidget(QLabel("提前触发（秒）："), 0, 2)
        self._pre_trigger_spin = QSpinBox()
        self._pre_trigger_spin.setRange(0, 30)
        self._pre_trigger_spin.setValue(3)
        self._pre_trigger_spin.setSuffix(" 秒")
        time_grid.addWidget(self._pre_trigger_spin, 0, 3)

        time_grid.addWidget(QLabel("预约开始时间："), 1, 0)
        self._book_start_time = QTimeEdit()
        self._book_start_time.setTime(QTime(8, 0))
        self._book_start_time.setDisplayFormat("HH:mm")
        time_grid.addWidget(self._book_start_time, 1, 1)

        time_grid.addWidget(QLabel("预约结束时间："), 1, 2)
        self._book_end_time = QTimeEdit()
        self._book_end_time.setTime(QTime(22, 0))
        self._book_end_time.setDisplayFormat("HH:mm")
        time_grid.addWidget(self._book_end_time, 1, 3)

        create_layout.addLayout(time_grid)

        # 参数
        param_layout = QHBoxLayout()
        param_layout.addWidget(QLabel("最大重试次数："))
        self._retry_spin = QSpinBox()
        self._retry_spin.setRange(1, 100)
        self._retry_spin.setValue(30)
        param_layout.addWidget(self._retry_spin)

        param_layout.addWidget(QLabel("重试间隔（秒）："))
        self._retry_interval_spin = QSpinBox()
        self._retry_interval_spin.setRange(0, 10)
        self._retry_interval_spin.setValue(1)
        self._retry_interval_spin.setSuffix(" 秒")
        param_layout.addWidget(self._retry_interval_spin)

        param_layout.addWidget(QLabel("并发提交："))
        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 10)
        self._concurrent_spin.setValue(3)
        self._concurrent_spin.setSuffix(" 个")
        param_layout.addWidget(self._concurrent_spin)

        self._cancel_peers_cb = QCheckBox("成功后停止其它任务")
        self._cancel_peers_cb.setChecked(True)
        param_layout.addWidget(self._cancel_peers_cb)

        param_layout.addStretch()
        create_layout.addLayout(param_layout)

        seat_group = QGroupBox("抢座候选")
        seat_layout = QVBoxLayout(seat_group)

        pick_bar = QHBoxLayout()
        pick_bar.addWidget(QLabel("选座区域："))
        self._candidate_area_combo = QComboBox()
        for cat_id, cont_id, name in KNOWN_AREAS:
            self._candidate_area_combo.addItem(name, (cat_id, cont_id))
        pick_bar.addWidget(self._candidate_area_combo)

        self._load_candidate_map_btn = QPushButton("加载座位图")
        self._load_candidate_map_btn.clicked.connect(self._on_load_candidate_map)
        pick_bar.addWidget(self._load_candidate_map_btn)

        pick_bar.addWidget(QLabel("具体房间："))
        self._candidate_room_combo = QComboBox()
        self._candidate_room_combo.addItem("全部房间", "")
        self._candidate_room_combo.currentIndexChanged.connect(self._on_candidate_room_changed)
        pick_bar.addWidget(self._candidate_room_combo)

        pick_bar.addWidget(QLabel("点击加入："))
        self._candidate_target_group = QButtonGroup(self)
        self._candidate_primary_radio = QRadioButton("主选")
        self._candidate_backup_radio = QRadioButton("备选")
        self._candidate_primary_radio.setChecked(True)
        self._candidate_target_group.addButton(self._candidate_primary_radio, 1)
        self._candidate_target_group.addButton(self._candidate_backup_radio, 2)
        pick_bar.addWidget(self._candidate_primary_radio)
        pick_bar.addWidget(self._candidate_backup_radio)
        pick_bar.addStretch()
        seat_layout.addLayout(pick_bar)

        map_tool_bar = QHBoxLayout()
        self._candidate_fit_btn = QPushButton("适应")
        self._candidate_fit_btn.clicked.connect(self._candidate_map_view_fit)
        map_tool_bar.addWidget(self._candidate_fit_btn)
        self._candidate_zoom_in_btn = QPushButton("+")
        self._candidate_zoom_in_btn.setFixedWidth(32)
        self._candidate_zoom_in_btn.clicked.connect(self._candidate_map_view_zoom_in)
        map_tool_bar.addWidget(self._candidate_zoom_in_btn)
        self._candidate_zoom_out_btn = QPushButton("-")
        self._candidate_zoom_out_btn.setFixedWidth(32)
        self._candidate_zoom_out_btn.clicked.connect(self._candidate_map_view_zoom_out)
        map_tool_bar.addWidget(self._candidate_zoom_out_btn)
        self._candidate_reset_btn = QPushButton("重置")
        self._candidate_reset_btn.clicked.connect(self._candidate_map_view_reset)
        map_tool_bar.addWidget(self._candidate_reset_btn)
        map_tool_bar.addStretch()
        seat_layout.addLayout(map_tool_bar)

        candidate_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._candidate_map_view = SeatMapView()
        self._candidate_map_view.setMinimumHeight(520)
        self._candidate_map_view.set_allow_unavailable_selection(True)
        self._candidate_map_view.set_seat_callback(self._on_candidate_seat_clicked)
        candidate_splitter.addWidget(self._candidate_map_view)

        selected_panel = QWidget()
        selected_layout = QVBoxLayout(selected_panel)
        selected_layout.setContentsMargins(8, 0, 0, 0)

        selected_layout.addWidget(QLabel("主选座位"))
        self._primary_seats_list = QListWidget()
        selected_layout.addWidget(self._primary_seats_list)
        self._clear_primary_btn = QPushButton("清空主选")
        self._clear_primary_btn.clicked.connect(self._clear_primary_candidates)
        selected_layout.addWidget(self._clear_primary_btn)

        selected_layout.addWidget(QLabel("备选座位"))
        self._backup_seats_list = QListWidget()
        selected_layout.addWidget(self._backup_seats_list)
        self._clear_backup_btn = QPushButton("清空备选")
        self._clear_backup_btn.clicked.connect(self._clear_backup_candidates)
        selected_layout.addWidget(self._clear_backup_btn)

        candidate_splitter.addWidget(selected_panel)
        candidate_splitter.setSizes([1120, 240])
        seat_layout.addWidget(candidate_splitter)
        create_layout.addWidget(seat_group)

        # 说明文字
        hint = QLabel(
            "💡 系统每晚 20:00 开放后两天的座位预约。"
            "定时任务将在开放时刻并发提交主选座位，"
            "任一成功后任务结束；主选失败后再提交备选座位。"
        )
        hint.setStyleSheet("color: #666; font-size: 12px; padding: 4px;")
        hint.setWordWrap(True)
        create_layout.addWidget(hint)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self._add_task_btn = QPushButton("添加定时任务")
        self._add_task_btn.setMinimumHeight(32)
        self._add_task_btn.setStyleSheet("""
            QPushButton { background-color: #1a73e8; color: white;
                          border: none; border-radius: 4px; padding: 6px 20px; font-weight: bold; }
            QPushButton:hover { background-color: #1557b0; }
        """)
        self._add_task_btn.clicked.connect(self._on_add_task)
        btn_layout.addWidget(self._add_task_btn)

        self._start_all_btn = QPushButton("启动全部")
        self._start_all_btn.clicked.connect(self._on_start_all)
        btn_layout.addWidget(self._start_all_btn)

        self._stop_all_btn = QPushButton("停止全部")
        self._stop_all_btn.clicked.connect(self._on_stop_all)
        btn_layout.addWidget(self._stop_all_btn)
        btn_layout.addStretch()
        create_layout.addLayout(btn_layout)

        layout.addWidget(create_group)

        # ===== 任务列表 =====
        task_group = QGroupBox("任务列表")
        task_layout = QVBoxLayout(task_group)

        self._task_table = QTableWidget()
        self._task_table.setColumnCount(8)
        self._task_table.setHorizontalHeaderLabels([
            "任务 ID", "类型", "预约时段", "状态", "信息", "重试", "创建时间", "操作"
        ])
        self._task_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._task_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch
        )
        self._task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._task_table.verticalHeader().setVisible(False)
        task_layout.addWidget(self._task_table)

        # 状态汇总
        status_layout = QHBoxLayout()
        self._summary_label = QLabel("暂无任务")
        self._summary_label.setStyleSheet("color: #666;")
        status_layout.addWidget(self._summary_label)
        status_layout.addStretch()
        self._clear_task_btn = QPushButton("清除已完成任务")
        self._clear_task_btn.clicked.connect(self._on_clear_tasks)
        status_layout.addWidget(self._clear_task_btn)
        task_layout.addLayout(status_layout)

        layout.addWidget(task_group)

    def _on_add_task(self):
        """添加定时预约任务。"""
        task_type = "seat"

        open_time = self._open_time.time().toString("HH:mm:ss")
        start_time = self._book_start_time.time().toString("HH:mm")
        end_time = self._book_end_time.time().toString("HH:mm")
        primary_seats = list(self._candidate_primary.keys())
        backup_seats = list(self._candidate_backup.keys())

        task_id = f"{task_type}_{datetime.now().strftime('%H%M%S_%f')}"

        task_name = f"座位-{start_time}-{end_time}"

        task = self._scheduler.schedule_daily_task(
            task_id=task_id,
            task_type=task_type,
            area_name=task_name,
            start_time=start_time,
            end_time=end_time,
            open_time=open_time,
            pre_trigger_seconds=self._pre_trigger_spin.value(),
            max_retries=self._retry_spin.value(),
            retry_interval_seconds=self._retry_interval_spin.value(),
            primary_seats=primary_seats,
            backup_seats=backup_seats,
            concurrent_requests=self._concurrent_spin.value(),
            cancel_peers_on_success=self._cancel_peers_cb.isChecked(),
        )

        QMessageBox.information(
            self, "任务已添加",
            f"定时预约任务已创建：\n"
            f"类型：座位\n"
            f"开放时间：{open_time}（提前 {self._pre_trigger_spin.value()} 秒触发）\n"
            f"预约时段：{start_time} - {end_time}\n\n"
            f"主选：{', '.join(primary_seats) or '自动选择'}\n"
            f"备选：{', '.join(backup_seats) or '无'}\n"
            f"并发提交：{self._concurrent_spin.value()} 个"
        )

        self._refresh_task_table()

    def _parse_seat_candidates(self, text: str) -> list[str]:
        """解析座位候选输入，支持逗号、空格和换行。"""
        import re

        seen = set()
        seats = []
        for token in re.split(r"[\s,，;；]+", text.strip()):
            token = token.strip()
            if token and token not in seen:
                seen.add(token)
                seats.append(token)
        return seats

    def _on_load_candidate_map(self):
        """加载用于配置定时抢座候选的座位图。"""
        if not self._seat_api:
            QMessageBox.warning(self, "提示", "请先登录")
            return

        idx = self._candidate_area_combo.currentIndex()
        if idx < 0:
            return
        cat_id, cont_id = self._candidate_area_combo.currentData()

        try:
            if not self._seat_api.uid:
                self._seat_api.load_seat_page(cat_id, cont_id)

            start_dt = self._candidate_booking_datetime()
            duration = self._candidate_duration_hours()
            resp = self._seat_api.search_seats(cat_id, cont_id, start_dt, duration)
            seats = SeatAPI.parse_seats_from_response(resp)
            if not seats:
                QMessageBox.information(self, "提示", "没有解析到座位图数据")
                return

            self._candidate_seats_by_id = {seat.seat_id: seat for seat in seats}
            self._candidate_loaded_seats = seats
            self._candidate_map_infos = self._seat_api.get_last_map_infos()
            self._populate_candidate_room_combo(seats)
            self._render_current_candidate_room()
        except Exception as e:
            logger.exception("加载候选座位图失败")
            QMessageBox.warning(self, "加载失败", str(e))

    def _populate_candidate_room_combo(self, seats: list):
        """根据加载到的座位填充具体房间列表。"""
        current = self._candidate_room_combo.currentData() or ""
        rooms = []
        seen = set()
        for seat in seats:
            room = seat.area_name or "未知房间"
            if room not in seen:
                seen.add(room)
                rooms.append(room)

        self._candidate_room_combo.blockSignals(True)
        self._candidate_room_combo.clear()
        self._candidate_room_combo.addItem("全部房间", "")
        for room in rooms:
            count = sum(1 for seat in seats if (seat.area_name or "未知房间") == room)
            self._candidate_room_combo.addItem(f"{room}（{count}）", room)
        idx = self._candidate_room_combo.findData(current)
        self._candidate_room_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._candidate_room_combo.blockSignals(False)

    def _on_candidate_room_changed(self):
        """切换具体房间后只重绘本地座位图。"""
        if self._candidate_loaded_seats:
            self._render_current_candidate_room()

    def _render_current_candidate_room(self):
        room = str(self._candidate_room_combo.currentData() or "")
        if room:
            seats = [
                seat for seat in self._candidate_loaded_seats
                if (seat.area_name or "未知房间") == room
            ]
        else:
            seats = self._candidate_loaded_seats
        self._render_candidate_map(seats, self._candidate_map_infos)

    def _candidate_map_view_fit(self):
        self._candidate_map_view.fit_to_view()

    def _candidate_map_view_zoom_in(self):
        self._candidate_map_view.zoom_in()

    def _candidate_map_view_zoom_out(self):
        self._candidate_map_view.zoom_out()

    def _candidate_map_view_reset(self):
        self._candidate_map_view.reset_zoom()

    def _candidate_booking_datetime(self) -> datetime:
        now = datetime.now()
        h, m, s = map(int, self._open_time.time().toString("HH:mm:ss").split(":"))
        trigger_time = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if trigger_time <= now:
            trigger_time += timedelta(days=1)
        booking_date = trigger_time + timedelta(days=1)
        qtime = self._book_start_time.time()
        return booking_date.replace(hour=qtime.hour(), minute=qtime.minute(), second=0)

    def _candidate_duration_hours(self) -> int:
        start = self._book_start_time.time()
        end = self._book_end_time.time()
        start_minutes = start.hour() * 60 + start.minute()
        end_minutes = end.hour() * 60 + end.minute()
        return max(1, round((end_minutes - start_minutes) / 60))

    def _render_candidate_map(self, seats: list, map_infos: dict[str, SeatMapInfo]):
        grouped: dict[str, list] = {}
        for seat in seats:
            grouped.setdefault(seat.area_name or "未知场馆", []).append(seat)

        single_room = len(grouped) == 1
        scale = 26 if single_room else 18
        margin = 40
        title_h = 28
        section_gap = 48
        min_section_w = 360 if single_room else 760
        min_section_h = 260 if single_room else 240
        transformed = []
        sections = []
        y_cursor = margin
        canvas_w = min_section_w + margin * 2

        for venue_name, venue_seats in grouped.items():
            venue_map = map_infos.get(venue_name) or SeatMapInfo(room_name=venue_name)
            max_x = max((s.x + max(s.width, 1) for s in venue_seats), default=133)
            max_y = max((s.y + max(s.height, 1) for s in venue_seats), default=86)
            map_w = venue_map.map_width or max_x
            map_h = venue_map.map_height or max_y
            section_w = max(map_w * scale + margin * 2, min_section_w)
            section_h = max(map_h * scale + margin * 2 + title_h, min_section_h)
            sections.append((venue_name, 0, y_cursor, section_w, section_h))
            canvas_w = max(canvas_w, section_w + margin * 2)

            for seat in venue_seats:
                transformed.append(replace(
                    seat,
                    x=margin + seat.x * scale,
                    y=y_cursor + title_h + seat.y * scale,
                    width=max(seat.width, 1) * scale,
                    height=max(seat.height, 1) * scale,
                    status=1,
                ))
            y_cursor += section_h + section_gap

        canvas_h = max(y_cursor + margin, 560)
        pixmap = QPixmap(canvas_w, canvas_h)
        pixmap.fill(QColor("#f0f0f0"))
        self._candidate_map_view.load_plan(pixmap)

        for venue_name, x, y, w, h in sections:
            self._candidate_map_view.scene().addRect(
                x + 12, y, w - 24, h,
                QPen(QColor("#d7dce2"), 1),
                QBrush(QColor("#f7f8fa")),
            )
            title = self._candidate_map_view.scene().addText(
                venue_name,
                QFont("Arial", 12, QFont.Weight.Bold),
            )
            title.setDefaultTextColor(QColor("#202124"))
            title.setPos(x + 28, y + 6)

        self._candidate_map_view.add_seats(
            transformed,
            SeatMapInfo(room_name="候选座位图", map_width=canvas_w, map_height=canvas_h),
        )
        self._candidate_map_view.fit_to_view()
        self._apply_candidate_highlights()

    def _on_candidate_seat_clicked(self, seat):
        """点击候选座位图后加入主选或备选。"""
        if not seat:
            return
        key = self._candidate_key(seat)
        label = self._candidate_label(seat)
        if key in self._candidate_primary:
            self._candidate_primary.pop(key, None)
        elif key in self._candidate_backup:
            self._candidate_backup.pop(key, None)
        elif self._candidate_primary_radio.isChecked():
            self._candidate_primary[key] = label
            self._candidate_backup.pop(key, None)
        else:
            self._candidate_backup[key] = label
            self._candidate_primary.pop(key, None)
        self._refresh_candidate_lists()
        self._apply_candidate_highlights()

    def _candidate_key(self, seat) -> str:
        return f"{seat.area_name or '未知场馆'}|{seat.seat_label}"

    def _candidate_label(self, seat) -> str:
        return f"{seat.area_name or '未知场馆'} | {seat.seat_label}"

    def _refresh_candidate_lists(self):
        self._primary_seats_list.clear()
        for key, label in self._candidate_primary.items():
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._primary_seats_list.addItem(item)

        self._backup_seats_list.clear()
        for key, label in self._candidate_backup.items():
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self._backup_seats_list.addItem(item)

    def _apply_candidate_highlights(self):
        """把主选/备选高亮同步到候选地图。"""
        for key in self._candidate_primary:
            seat = self._find_visible_candidate_seat(key)
            if seat:
                self._candidate_map_view.set_seat_color(
                    seat.seat_id,
                    CANDIDATE_PRIMARY_COLOR,
                    QColor("#7f1d1d"),
                )
        for key in self._candidate_backup:
            seat = self._find_visible_candidate_seat(key)
            if seat:
                self._candidate_map_view.set_seat_color(
                    seat.seat_id,
                    CANDIDATE_BACKUP_COLOR,
                    QColor("#174ea6"),
                )

    def _find_visible_candidate_seat(self, key: str):
        for seat in self._candidate_seats_by_id.values():
            if self._candidate_key(seat) == key:
                return seat
        return None

    def _clear_primary_candidates(self):
        self._candidate_primary.clear()
        self._refresh_candidate_lists()
        self._render_current_candidate_room()

    def _clear_backup_candidates(self):
        self._candidate_backup.clear()
        self._refresh_candidate_lists()
        self._render_current_candidate_room()

    def _on_start_all(self):
        """启动所有待执行的任务。"""
        for task in self._scheduler.get_all_tasks():
            if task.status in (TaskStatus.IDLE, TaskStatus.FAILED):
                self._scheduler.start_task(task.task_id)
        self._refresh_task_table()

    def _on_stop_all(self):
        """停止所有任务。"""
        for task in self._scheduler.get_all_tasks():
            if task.status in (TaskStatus.WAITING, TaskStatus.RUNNING):
                self._scheduler.cancel_task(task.task_id)
        self._refresh_task_table()

    def _on_clear_tasks(self):
        """清除已完成或已取消的任务。"""
        for task in self._scheduler.get_all_tasks():
            if task.status in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self._scheduler.remove_task(task.task_id)
        self._refresh_task_table()

    def _refresh_task_table(self):
        """刷新任务列表表格。"""
        tasks = self._scheduler.get_all_tasks()
        self._task_table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            self._task_table.setItem(row, 0, QTableWidgetItem(task.task_id))
            self._task_table.setItem(
                row, 1,
                QTableWidgetItem("座位" if task.task_type == "seat" else "场地")
            )
            self._task_table.setItem(
                row, 2,
                QTableWidgetItem(f"{task.start_time}-{task.end_time}")
            )

            status_text = {
                TaskStatus.IDLE: "等待中",
                TaskStatus.WAITING: "等待中",
                TaskStatus.RUNNING: "执行中",
                TaskStatus.SUCCESS: "✓ 成功",
                TaskStatus.FAILED: "✗ 失败",
                TaskStatus.CANCELLED: "已取消",
            }.get(task.status, str(task.status.value))

            status_color = {
                TaskStatus.IDLE: None,
                TaskStatus.WAITING: "#e8f0fe",
                TaskStatus.RUNNING: "#fef7e0",
                TaskStatus.SUCCESS: "#e6f4ea",
                TaskStatus.FAILED: "#fce8e6",
                TaskStatus.CANCELLED: "#f0f0f0",
            }.get(task.status)

            status_item = QTableWidgetItem(status_text)
            if status_color:
                status_item.setBackground(QColor(status_color))
            self._task_table.setItem(row, 3, status_item)

            self._task_table.setItem(
                row, 4,
                QTableWidgetItem(self._task_info_text(task))
            )
            self._task_table.setItem(
                row, 5,
                QTableWidgetItem(f"{task.retry_count}")
            )
            self._task_table.setItem(
                row, 6,
                QTableWidgetItem(task.created_at.strftime("%H:%M:%S"))
            )

            # 操作按钮
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 1, 4, 1)

            if task.status == TaskStatus.WAITING:
                cancel_btn = QPushButton("取消")
                cancel_btn.setStyleSheet("color: #c5221f; font-size: 11px;")
                cancel_btn.clicked.connect(lambda checked, tid=task.task_id: self._scheduler.cancel_task(tid))
                action_layout.addWidget(cancel_btn)
            elif task.status == TaskStatus.FAILED:
                retry_btn = QPushButton("重试")
                retry_btn.setStyleSheet("color: #1a73e8; font-size: 11px;")
                retry_btn.clicked.connect(lambda checked, tid=task.task_id: self._scheduler.start_task(tid))
                action_layout.addWidget(retry_btn)

            remove_btn = QPushButton("删除")
            remove_btn.setStyleSheet("color: #999; font-size: 11px;")
            remove_btn.clicked.connect(lambda checked, tid=task.task_id: self._scheduler.remove_task(tid))
            action_layout.addWidget(remove_btn)

            self._task_table.setCellWidget(row, 7, action_widget)

        # 更新汇总信息
        if tasks:
            waiting = sum(1 for t in tasks if t.status == TaskStatus.WAITING)
            running = sum(1 for t in tasks if t.status == TaskStatus.RUNNING)
            success = sum(1 for t in tasks if t.status == TaskStatus.SUCCESS)
            failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)
            self._summary_label.setText(
                f"共 {len(tasks)} 个任务 | "
                f"等待中 {waiting} | 执行中 {running} | "
                f"成功 {success} | 失败 {failed}"
            )
        else:
            self._summary_label.setText("暂无任务")

    def _task_info_text(self, task: BookingTask) -> str:
        candidates = []
        if task.primary_seats:
            candidates.append(f"主选:{','.join(task.primary_seats)}")
        if task.backup_seats:
            candidates.append(f"备选:{','.join(task.backup_seats)}")
        if task.concurrent_requests:
            candidates.append(f"并发:{task.concurrent_requests}")
        if task.status_message:
            candidates.append(task.status_message)
        return " | ".join(candidates) if candidates else (task.status_message or "-")

    def _execute_booking(self, task: BookingTask) -> tuple[bool, str]:
        """执行预约（由调度器回调）。

        使用 zhishulib.com 真实 API：
        1. 加载区域页面数据（获取 uid）
        2. 搜索可用座位
        3. 预约第一个可用座位
        """
        from datetime import datetime, timezone, timedelta

        BEIJING_TZ = timezone(timedelta(hours=8))

        try:
            if task.task_type == "seat" and self._seat_api:
                cat_id = task.category_id or 591
                cont_id = task.content_id or 3

                # Step 1: 加载区域信息，获取 uid
                if not self._seat_api.uid:
                    self._seat_api.load_seat_page(cat_id, cont_id)
                if not self._seat_api.uid:
                    return False, "无法获取用户 uid"

                # Step 2: 构造预约时间
                start_dt = datetime.strptime(
                    f"{task.date_str} {task.start_time}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=BEIJING_TZ)

                duration = task.duration_hours or 4

                # Step 3: 搜索可用座位，用于把座位编号解析为 seat_id。
                resp = self._seat_api.search_seats(cat_id, cont_id, start_dt, duration)
                seats = SeatAPI.parse_seats_from_response(resp)
                available = [s for s in seats if s.status == 1]

                if not available:
                    return False, f"没有可用座位（共 {len(seats)} 个）"

                primary = self._resolve_seat_candidates(task.primary_seats, available)
                backup = self._resolve_seat_candidates(task.backup_seats, available)

                if not primary and not backup:
                    primary = available

                success, message = self._try_book_candidates(
                    primary,
                    start_dt,
                    duration,
                    task.concurrent_requests,
                    "主选",
                )
                if success:
                    return True, message

                if backup:
                    success, backup_message = self._try_book_candidates(
                        backup,
                        start_dt,
                        duration,
                        task.concurrent_requests,
                        "备选",
                    )
                    if success:
                        return True, backup_message
                    return False, f"主选失败：{message}；备选失败：{backup_message}"

                return False, message

            elif task.task_type == "room" and self._room_api:
                date_str = task.date_str or datetime.now().strftime("%Y-%m-%d")
                result = self._room_api.book_room(
                    room_id=task.room_id,
                    date_str=date_str,
                    start_time=task.start_time,
                    end_time=task.end_time,
                )
                return result.success, result.message

            return False, "未设置 API 客户端"

        except Exception as e:
            logger.exception(f"执行预约异常：{e}")
            return False, str(e)

    def _resolve_seat_candidates(self, tokens: list[str], available: list) -> list:
        """把用户输入的座位编号/ID解析为当前可预约 SeatInfo。"""
        if not tokens:
            return []

        resolved = []
        used_ids = set()
        for token in tokens:
            area_hint = ""
            label = token.strip()
            if "|" in label:
                area_hint, label = [part.strip() for part in label.split("|", 1)]

            matches = []
            for seat in available:
                if area_hint and area_hint not in (seat.area_name or ""):
                    continue
                if label == str(seat.seat_id) or label == seat.seat_label:
                    matches.append(seat)

            for seat in matches:
                if seat.seat_id not in used_ids:
                    used_ids.add(seat.seat_id)
                    resolved.append(seat)

        return resolved

    def _try_book_candidates(
        self,
        candidates: list,
        start_dt: datetime,
        duration: int,
        concurrent_requests: int,
        group_name: str,
    ) -> tuple[bool, str]:
        """并发提交一组候选座位，任一成功即返回成功。"""
        if not candidates:
            return False, f"{group_name}没有匹配到可预约座位"

        max_workers = max(1, min(concurrent_requests or 1, len(candidates)))
        last_message = ""
        logger.info(
            f"{group_name}并发预约: seats={[s.seat_label for s in candidates]}, workers={max_workers}"
        )

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_seat = {
                executor.submit(self._seat_api.book_seat, seat.seat_id, start_dt, duration): seat
                for seat in candidates
            }
            for future in as_completed(future_to_seat):
                seat = future_to_seat[future]
                try:
                    result = future.result()
                except Exception as e:
                    last_message = f"{seat.seat_label}: {e}"
                    logger.warning(f"{group_name}预约异常: {last_message}")
                    continue

                if result.success:
                    for pending in future_to_seat:
                        if pending is not future:
                            pending.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    return True, f"{group_name}预约成功：{seat.area_name} {seat.seat_label} #{result.booking_id}"

                last_message = f"{seat.seat_label}: {result.message}"
                logger.warning(f"{group_name}预约失败: {last_message}")
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return False, last_message or f"{group_name}全部失败"

    def _on_task_start(self, task_id: str):
        """任务开始回调。"""
        logger.info(f"任务开始：{task_id}")

    def _on_task_progress(self, task_id: str, attempt: int, total: int):
        """任务进度回调。"""
        pass

    def _on_task_complete(self, task_id: str, status: str, message: str):
        """任务完成回调。"""
        logger.info(f"任务完成：{task_id} status={status} msg={message}")

    def shutdown(self):
        """关闭调度器。"""
        self._refresh_timer.stop()
        self._scheduler.shutdown()
