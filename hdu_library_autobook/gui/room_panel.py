"""
GUI 模块 - 场地预约面板

提供研讨间、讨论室的查询和预约功能。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QDateEdit, QTimeEdit, QGroupBox,
    QMessageBox, QSpinBox, QLineEdit, QTextEdit,
    QSplitter, QFormLayout,
)
from PyQt6.QtCore import Qt, QDate, QTime
from PyQt6.QtGui import QColor
import logging

from api import APIClient, AuthAPI, RoomAPI, RoomInfo, RoomBookingResult

logger = logging.getLogger(__name__)


class RoomBookingPanel(QWidget):
    """场地/研讨间预约面板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._room_api: RoomAPI | None = None
        self._current_rooms: list[RoomInfo] = []
        self._setup_ui()

    def set_api_client(self, client: APIClient, auth: AuthAPI):
        """设置 API 客户端。"""
        self._room_api = RoomAPI(client)

    def _setup_ui(self):
        """初始化界面。"""
        layout = QVBoxLayout(self)

        # ===== 查询条件 =====
        search_group = QGroupBox("场地查询")
        search_layout = QVBoxLayout(search_group)

        # 第一行
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("选择日期："))
        self._date_picker = QDateEdit()
        self._date_picker.setDate(QDate.currentDate())
        self._date_picker.setMinimumDate(QDate.currentDate())
        self._date_picker.setMaximumDate(QDate.currentDate().addDays(6))
        self._date_picker.setCalendarPopup(True)
        self._date_picker.setDisplayFormat("yyyy-MM-dd")
        row1.addWidget(self._date_picker)

        row1.addWidget(QLabel("开始时间："))
        self._start_time = QTimeEdit()
        self._start_time.setTime(QTime(8, 0))
        self._start_time.setDisplayFormat("HH:mm")
        row1.addWidget(self._start_time)

        row1.addWidget(QLabel("结束时间："))
        self._end_time = QTimeEdit()
        self._end_time.setTime(QTime(22, 0))
        self._end_time.setDisplayFormat("HH:mm")
        row1.addWidget(self._end_time)

        row1.addWidget(QLabel("最少容纳："))
        self._capacity_spin = QSpinBox()
        self._capacity_spin.setRange(1, 20)
        self._capacity_spin.setValue(1)
        self._capacity_spin.setSuffix(" 人")
        row1.addWidget(self._capacity_spin)

        self._query_btn = QPushButton("查询场地")
        self._query_btn.clicked.connect(self._on_query_rooms)
        self._query_btn.setStyleSheet("""
            QPushButton { background-color: #1a73e8; color: white;
                          border: none; border-radius: 4px; padding: 6px 16px; }
            QPushButton:hover { background-color: #1557b0; }
        """)
        row1.addWidget(self._query_btn)
        row1.addStretch()
        search_layout.addLayout(row1)

        layout.addWidget(search_group)

        # ===== 场地表格 =====
        self._room_table = QTableWidget()
        self._room_table.setColumnCount(6)
        self._room_table.setHorizontalHeaderLabels([
            "场地名称", "楼层", "容量", "设施", "状态", "操作"
        ])
        self._room_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._room_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._room_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._room_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._room_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._room_table.verticalHeader().setVisible(False)
        layout.addWidget(self._room_table)

        # ===== 预约表单 =====
        form_group = QGroupBox("预约信息")
        form_layout = QFormLayout(form_group)

        # 用途
        self._title_input = QLineEdit()
        self._title_input.setPlaceholderText("如：小组讨论、学习")
        form_layout.addRow("使用用途：", self._title_input)

        # 人数
        self._attendees_spin = QSpinBox()
        self._attendees_spin.setRange(1, 20)
        self._attendees_spin.setValue(2)
        self._attendees_spin.setSuffix(" 人")
        form_layout.addRow("使用人数：", self._attendees_spin)

        # 备注
        self._remark_input = QLineEdit()
        self._remark_input.setPlaceholderText("选填")
        form_layout.addRow("备注：", self._remark_input)

        # 操作按钮
        btn_layout = QHBoxLayout()

        self._book_btn = QPushButton("预约选中场地")
        self._book_btn.setMinimumHeight(36)
        self._book_btn.setStyleSheet("""
            QPushButton {
                background-color: #34a853; color: white;
                border: none; border-radius: 6px;
                font-size: 14px; font-weight: bold; padding: 0 20px;
            }
            QPushButton:hover { background-color: #2d9249; }
            QPushButton:disabled { background-color: #ccc; }
        """)
        self._book_btn.clicked.connect(self._on_book_room)
        self._book_btn.setEnabled(False)
        btn_layout.addWidget(self._book_btn)

        btn_layout.addStretch()
        form_layout.addRow(btn_layout)

        layout.addWidget(form_group)

        # 状态栏
        self._status_label = QLabel("请先查询可用场地")
        self._status_label.setStyleSheet("padding: 4px; color: #666;")
        layout.addWidget(self._status_label)

    def _on_query_rooms(self):
        """查询可用场地。"""
        if not self._room_api:
            QMessageBox.warning(self, "提示", "请先登录")
            return

        date_str = self._date_picker.date().toString("yyyy-MM-dd")
        start = self._start_time.time().toString("HH:mm")
        end = self._end_time.time().toString("HH:mm")
        min_capacity = self._capacity_spin.value()

        self._status_label.setText("正在查询场地...")
        self._query_btn.setEnabled(False)

        try:
            rooms = self._room_api.get_rooms(
                date_str=date_str,
                start_time=start,
                end_time=end,
                min_capacity=min_capacity,
            )
            self._current_rooms = rooms
            self._populate_room_table(rooms)

            available = sum(1 for r in rooms if r.status == "available")
            self._status_label.setText(
                f"共找到 {len(rooms)} 个场地，可用 {available} 个"
            )
            self._book_btn.setEnabled(available > 0)

        except Exception as e:
            logger.exception(f"查询场地异常：{e}")
            self._status_label.setText(f"查询失败：{e}")
        finally:
            self._query_btn.setEnabled(True)

    def _populate_room_table(self, rooms: list[RoomInfo]):
        """填充场地表格。"""
        self._room_table.setRowCount(len(rooms))

        status_map = {
            "available": ("可预约", "#e6f4ea"),
            "occupied": ("已占用", "#fce8e6"),
            "reserved": ("已预约", "#fef7e0"),
            "unknown": ("未知", "#f0f0f0"),
        }

        for row, room in enumerate(rooms):
            status_text, status_color = status_map.get(
                room.status, ("未知", "#f0f0f0")
            )

            self._room_table.setItem(row, 0, QTableWidgetItem(room.name))
            self._room_table.setItem(row, 1, QTableWidgetItem(room.floor))
            self._room_table.setItem(row, 2, QTableWidgetItem(f"{room.capacity} 人"))

            facilities_text = "、".join(room.facilities) if room.facilities else "-"
            self._room_table.setItem(row, 3, QTableWidgetItem(facilities_text))

            status_item = QTableWidgetItem(status_text)
            status_item.setBackground(QColor(status_color))
            self._room_table.setItem(row, 4, status_item)

            if room.status == "available":
                book_btn = QPushButton("预约")
                book_btn.setStyleSheet("""
                    QPushButton { background-color: #1a73e8; color: white;
                                  border: none; border-radius: 3px; padding: 4px 12px; }
                    QPushButton:hover { background-color: #1557b0; }
                """)
                book_btn.clicked.connect(lambda checked, r=room: self._book_single(r))
                self._room_table.setCellWidget(row, 5, book_btn)
            else:
                lbl = QLabel("不可预约")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("color: #999;")
                self._room_table.setCellWidget(row, 5, lbl)

    def _book_single(self, room: RoomInfo):
        """预约单个场地。"""
        if not self._room_api:
            return

        date_str = self._date_picker.date().toString("yyyy-MM-dd")
        start = self._start_time.time().toString("HH:mm")
        end = self._end_time.time().toString("HH:mm")
        title = self._title_input.text().strip() or "学习"
        attendees = self._attendees_spin.value()
        remark = self._remark_input.text().strip()

        reply = QMessageBox.question(
            self, "确认预约",
            f"场地：{room.name}\n"
            f"日期：{date_str}\n"
            f"时间：{start}-{end}\n"
            f"人数：{attendees}\n\n"
            "确认预约？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            result = self._room_api.book_room(
                room_id=room.room_id,
                date_str=date_str,
                start_time=start,
                end_time=end,
                title=title,
                attendees=attendees,
                remark=remark,
            )

            if result.success:
                QMessageBox.information(self, "预约成功",
                    f"{room.name} 预约成功！\n"
                    f"时间：{date_str} {start}-{end}"
                )
                self._status_label.setText(f"预约成功：{room.name}")
                self._on_query_rooms()
            else:
                QMessageBox.warning(self, "预约失败",
                    f"预约失败：{result.message}"
                )
                self._status_label.setText(f"失败：{result.message}")

        except Exception as e:
            logger.exception(f"场地预约异常：{e}")
            self._status_label.setText(f"异常：{e}")

    def _on_book_room(self):
        """预约当前选中的场地。"""
        current_row = self._room_table.currentRow()
        if current_row < 0 or current_row >= len(self._current_rooms):
            QMessageBox.warning(self, "提示", "请先选中一个场地")
            return

        room = self._current_rooms[current_row]
        self._book_single(room)
