"""
GUI 模块 - 座位预约面板

显示座位图形化地图（楼层平面图 + 座位标记），支持点击选座预约。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from dataclasses import replace
from pathlib import Path
import hashlib
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QDateEdit, QTimeEdit, QGroupBox,
    QMessageBox, QCheckBox, QApplication, QGraphicsView,
    QGraphicsScene, QSplitter, QListWidget, QListWidgetItem,
)
from PyQt6.QtCore import Qt, QDate, QTime, QRectF, QByteArray
from PyQt6.QtGui import (
    QColor, QBrush, QPen, QPixmap, QFont, QPainter,
    QTransform,
)
import logging
import requests

from api import APIClient, AuthAPI, SeatAPI, SeatInfo, SeatMapInfo

logger = logging.getLogger(__name__)

BEIJING_TZ = timezone(timedelta(hours=8))

# 默认已知区域
KNOWN_AREAS = [
    (591, 3, "自习室"),
    (591, 115, "生活区（求新书院&守正书院）"),
    (591, 76, "阅览室（3-11楼）"),
    (591, 117, "五楼特藏区"),
    (591, 39, "教师休息室"),
]

# 颜色
COLOR_AVAILABLE = QColor("#34a853")   # 绿色 可用
COLOR_OCCUPIED = QColor("#ff4655")    # 红色 不可约
COLOR_SELECTED = QColor("#1a73e8")    # 蓝色 选中
COLOR_HOVER = QColor("#fbbc04")       # 黄色 悬停
COLOR_TEXT = QColor("#ffffff")
MAP_CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache" / "seat_maps"


class SeatGraphicsItem:
    """图形化座位的可视化元素。"""

    def __init__(self, seat: SeatInfo, x: float, y: float, w: float, h: float):
        self.seat = seat
        self.rect = QRectF(x, y, w, h)
        self.is_selected = False


class SeatMapView(QGraphicsView):
    """显示楼层平面图和座位标记的图形视图。"""

    seat_clicked = None  # 将在外部连接

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._plan_pixmap: QPixmap | None = None
        self._plan_item = None
        self._seat_items: dict[int, tuple] = {}  # seat_id -> (rect_item, text_item|None, SeatGraphicsItem)
        self._scale_factor = 1.0
        self._selected_seat_id: int | None = None
        self._seat_callback = None
        self._allow_unavailable_selection = False

        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setMinimumHeight(400)
        self.setStyleSheet("background-color: #f5f5f5; border: 1px solid #ddd;")

    def wheelEvent(self, event):
        """鼠标滚轮缩放。"""
        factor = 1.15
        if event.angleDelta().y() > 0:
            self._scale_factor *= factor
            self.scale(factor, factor)
        else:
            self._scale_factor /= factor
            self.scale(1 / factor, 1 / factor)

    def zoom_in(self):
        self._scale_factor *= 1.2
        self.scale(1.2, 1.2)

    def zoom_out(self):
        self._scale_factor /= 1.2
        self.scale(1 / 1.2, 1 / 1.2)

    def reset_zoom(self):
        self.resetTransform()
        self._scale_factor = 1.0

    def fit_to_view(self):
        if not self._scene.items():
            return
        self.reset_zoom()
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def set_seat_callback(self, callback):
        """设置座位点击回调。"""
        self._seat_callback = callback

    def set_allow_unavailable_selection(self, allow: bool):
        """是否允许选择当前不可约座位。定时抢座候选配置会用到。"""
        self._allow_unavailable_selection = allow

    def load_plan(self, pixmap: QPixmap):
        """加载楼层平面图背景。"""
        self._scene.clear()
        self._seat_items.clear()
        self._plan_pixmap = pixmap
        self._plan_item = self._scene.addPixmap(pixmap)
        self._selected_seat_id = None
        self.reset_zoom()

    def add_seats(self, seats: list[SeatInfo], map_info: SeatMapInfo):
        """在平面图上叠加座位标记。"""
        self._seat_items.clear()
        self._selected_seat_id = None

        pw = map_info.map_width or 133
        ph = map_info.map_height or 86

        show_labels = len(seats) <= 120

        for seat in seats:
            if seat.x == 0 and seat.y == 0:
                continue  # 跳过无坐标座位

            # 坐标映射：API 坐标在 [0..pw, 0..ph] 范围
            sx = seat.x / pw if pw else 0
            sy = seat.y / ph if ph else 0
            sw = max(seat.width, 1) / pw if pw else 0.02
            sh = max(seat.height, 1) / ph if ph else 0.02

            # 如果有平面图，用像素坐标
            if self._plan_pixmap:
                p = self._plan_pixmap
                px = sx * p.width()
                py = sy * p.height()
                pw2 = sw * p.width()
                ph2 = sh * p.height()
            else:
                px = sx * 800
                py = sy * 600
                pw2 = max(sw * 800, 16)
                ph2 = max(sh * 600, 16)

            # 创建座位矩形
            seat_item = SeatGraphicsItem(seat, px, py, pw2, ph2)

            # 绘制带圆角的矩形
            color = COLOR_AVAILABLE if seat.status == 1 else COLOR_OCCUPIED
            brush = QBrush(color)
            pen = QPen(QColor("#ffffff"), 0.6)

            rect_item = self._scene.addRect(
                px, py, pw2, ph2, pen, brush
            )
            rect_item.setData(0, seat.seat_id)
            rect_item.setToolTip(f"{seat.seat_label} ({seat.area_name})")

            # 座位编号文字
            text_item = None
            if show_labels and pw2 >= 14 and ph2 >= 10:
                font = QFont("Arial", max(6, int(pw2 * 0.35)))
                text_item = self._scene.addText(seat.seat_label, font)
                text_item.setDefaultTextColor(COLOR_TEXT)
                tr = text_item.boundingRect()
                text_item.setPos(
                    px + (pw2 - tr.width()) / 2,
                    py + (ph2 - tr.height()) / 2,
                )
                text_item.setData(0, seat.seat_id)

            self._seat_items[seat.seat_id] = (rect_item, text_item, seat_item)

    def select_seat(self, seat_id: int, emit_callback: bool = True):
        """从外部选择座位，并把视图移动到该座位。"""
        if seat_id not in self._seat_items:
            return
        self._toggle_select(seat_id, emit_callback=emit_callback)
        rect_item, _, sg_item = self._seat_items[seat_id]
        self.centerOn(rect_item)
        if sg_item.rect.width() < 18 or sg_item.rect.height() < 18:
            self.ensureVisible(rect_item, 80, 80)

    def set_seat_color(self, seat_id: int, color: QColor, pen_color: QColor | None = None):
        """外部设置座位颜色，用于候选多选高亮。"""
        if seat_id not in self._seat_items:
            return
        rect_item, _, _ = self._seat_items[seat_id]
        rect_item.setBrush(QBrush(color))
        rect_item.setPen(QPen(pen_color or QColor("#ffffff"), 1.4))

    def clear_seats(self):
        """清除座位标记。"""
        # 保留平面图，移除其他所有项
        for sid, (rect_item, text_item, _) in self._seat_items.items():
            self._scene.removeItem(rect_item)
            if text_item:
                self._scene.removeItem(text_item)
        self._seat_items.clear()
        self._selected_seat_id = None

    def mousePressEvent(self, event):
        """处理鼠标点击选座。"""
        scene_pos = self.mapToScene(event.pos())
        item = self._scene.itemAt(scene_pos, QTransform())

        if item:
            seat_id = item.data(0)
            if seat_id is not None and seat_id in self._seat_items:
                self._toggle_select(seat_id)
                return

        super().mousePressEvent(event)

    def _toggle_select(self, seat_id: int, emit_callback: bool = True):
        """切换座位的选中状态。"""
        rect_item, text_item, sg_item = self._seat_items.get(seat_id)
        if not sg_item:
            return

        # 不能选已占用的
        if sg_item.seat.status != 1 and not self._allow_unavailable_selection:
            return

        # 取消之前的选中
        if self._selected_seat_id is not None and self._selected_seat_id in self._seat_items:
            prev_rect, _, prev_sg = self._seat_items[self._selected_seat_id]
            prev_sg.is_selected = False
            prev_rect.setBrush(QBrush(COLOR_AVAILABLE))
            prev_rect.setPen(QPen(Qt.GlobalColor.white, 1))

        # 切换当前选中
        if self._selected_seat_id == seat_id:
            self._selected_seat_id = None
            sg_item.is_selected = False
            rect_item.setBrush(QBrush(COLOR_AVAILABLE))
            rect_item.setPen(QPen(Qt.GlobalColor.white, 1))
        else:
            self._selected_seat_id = seat_id
            sg_item.is_selected = True
            rect_item.setBrush(QBrush(COLOR_SELECTED))
            rect_item.setPen(QPen(Qt.GlobalColor.white, 2))

        # 通知回调
        if emit_callback and self._seat_callback:
            selected = sg_item.seat if sg_item.is_selected else None
            self._seat_callback(selected)


class SeatBookingPanel(QWidget):
    """座位预约面板（图形化地图 + 列表双视图）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._seat_api: SeatAPI | None = None
        self._all_seats: list[SeatInfo] = []
        self._display_source_seats: list[SeatInfo] = []
        self._current_seats: list[SeatInfo] = []
        self._current_map_seats: list[SeatInfo] = []
        self._map_info: SeatMapInfo | None = None
        self._map_infos: dict[str, SeatMapInfo] = {}
        self._map_loaded = False
        self._selected_seat: SeatInfo | None = None
        self._syncing_selection = False
        self._time_range: dict = {}
        self._setup_ui()

    def set_api_client(self, client: APIClient, auth: AuthAPI):
        self._seat_api = SeatAPI(client)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 查询条件 ──
        search_group = QGroupBox("查询条件")
        search_layout = QVBoxLayout(search_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("预约区域："))
        self._area_combo = QComboBox()
        self._area_combo.setMinimumWidth(200)
        for cat_id, cont_id, name in KNOWN_AREAS:
            self._area_combo.addItem(name, (cat_id, cont_id))
        row1.addWidget(self._area_combo)

        self._refresh_areas_btn = QPushButton("加载区域信息")
        self._refresh_areas_btn.clicked.connect(self._on_load_area)
        row1.addWidget(self._refresh_areas_btn)
        row1.addStretch()
        search_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("日　期："))
        self._date_picker = QDateEdit()
        self._date_picker.setDate(QDate.currentDate())
        self._date_picker.setMinimumDate(QDate.currentDate())
        self._date_picker.setMaximumDate(QDate.currentDate().addDays(6))
        self._date_picker.setCalendarPopup(True)
        self._date_picker.setDisplayFormat("yyyy-MM-dd")
        row2.addWidget(self._date_picker)

        row2.addWidget(QLabel("开始时间："))
        self._start_time = QTimeEdit()
        now = QTime.currentTime()
        self._start_time.setTime(QTime(now.hour(), 0))
        self._start_time.setDisplayFormat("HH:mm")
        row2.addWidget(self._start_time)

        row2.addWidget(QLabel("时长(小时)："))
        self._duration_spin = QTimeEdit()
        self._duration_spin.setDisplayFormat("H")
        self._duration_spin.setTime(QTime(4, 0))
        row2.addWidget(self._duration_spin)

        self._query_btn = QPushButton("查询座位")
        self._query_btn.clicked.connect(self._on_query_seats)
        self._query_btn.setStyleSheet(
            "QPushButton { background-color: #1a73e8; color: white;"
            " border: none; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #1557b0; }"
        )
        row2.addWidget(self._query_btn)
        search_layout.addLayout(row2)

        # 图例
        row3 = QHBoxLayout()
        self._auto_select_cb = QCheckBox("自动选择最佳座位")
        self._auto_select_cb.setChecked(True)
        row3.addWidget(self._auto_select_cb)

        self._use_plan_image_cb = QCheckBox("加载官方平面图")
        self._use_plan_image_cb.setChecked(False)
        self._use_plan_image_cb.setToolTip(
            "默认使用应用原生座位图，速度更快；勾选后加载网页端官方平面图用于对照"
        )
        self._use_plan_image_cb.stateChanged.connect(self._on_plan_background_changed)
        row3.addWidget(self._use_plan_image_cb)

        row3.addWidget(QLabel("场馆："))
        self._venue_combo = QComboBox()
        self._venue_combo.setMinimumWidth(220)
        self._venue_combo.addItem("全部场馆", "")
        self._venue_combo.currentIndexChanged.connect(self._on_venue_changed)
        row3.addWidget(self._venue_combo)
        row3.addStretch()

        # 图例标签
        self._legend = QLabel(
            '<span style="color:#34a853">■</span> 可用  '
            '<span style="color:#ff4655">■</span> 不可约  '
            '<span style="color:#1a73e8">■</span> 选中'
        )
        row3.addWidget(self._legend)

        self._toggle_view_btn = QPushButton("列表视图")
        self._toggle_view_btn.setCheckable(True)
        self._toggle_view_btn.clicked.connect(self._toggle_view)
        row3.addWidget(self._toggle_view_btn)

        search_layout.addLayout(row3)
        layout.addWidget(search_group)

        # ── 座位显示区域（图形视图 + 表格，使用 QSplitter） ──
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        # 图形化座位地图
        self._map_view = SeatMapView()
        self._map_view.set_seat_callback(self._on_seat_selected_from_map)
        self._map_container = QWidget()
        map_layout = QVBoxLayout(self._map_container)
        map_layout.setContentsMargins(0, 0, 0, 0)

        # 房间名称标签
        self._room_name_label = QLabel("")
        self._room_name_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 4px;"
        )
        map_layout.addWidget(self._room_name_label)

        map_tools = QHBoxLayout()
        self._fit_map_btn = QPushButton("适应")
        self._fit_map_btn.clicked.connect(self._map_view.fit_to_view)
        map_tools.addWidget(self._fit_map_btn)
        self._zoom_in_btn = QPushButton("+")
        self._zoom_in_btn.setFixedWidth(32)
        self._zoom_in_btn.clicked.connect(self._map_view.zoom_in)
        map_tools.addWidget(self._zoom_in_btn)
        self._zoom_out_btn = QPushButton("-")
        self._zoom_out_btn.setFixedWidth(32)
        self._zoom_out_btn.clicked.connect(self._map_view.zoom_out)
        map_tools.addWidget(self._zoom_out_btn)
        self._reset_zoom_btn = QPushButton("重置")
        self._reset_zoom_btn.clicked.connect(self._map_view.reset_zoom)
        map_tools.addWidget(self._reset_zoom_btn)
        map_tools.addStretch()
        self._map_hint_label = QLabel("原生座位图即时渲染；右侧列表只列可预约座位")
        self._map_hint_label.setStyleSheet("color: #666;")
        map_tools.addWidget(self._map_hint_label)
        map_layout.addLayout(map_tools)

        self._map_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._map_splitter.addWidget(self._map_view)

        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(8, 0, 0, 0)
        self._map_available_title = QLabel("当前场馆可选座位")
        self._map_available_title.setStyleSheet("font-weight: bold; padding: 4px 0;")
        side_layout.addWidget(self._map_available_title)
        self._map_available_list = QListWidget()
        self._map_available_list.itemClicked.connect(self._on_map_list_item_clicked)
        side_layout.addWidget(self._map_available_list)
        self._map_splitter.addWidget(side_panel)
        self._map_splitter.setSizes([900, 260])
        map_layout.addWidget(self._map_splitter)
        self._splitter.addWidget(self._map_container)

        # 表格视图
        self._seat_table = QTableWidget()
        self._seat_table.setColumnCount(4)
        self._seat_table.setHorizontalHeaderLabels(["座位编号", "区域", "状态", "操作"])
        self._seat_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._seat_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._seat_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._seat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._seat_table.verticalHeader().setVisible(False)
        self._seat_table.setVisible(True)
        self._splitter.addWidget(self._seat_table)
        self._show_list_view()

        layout.addWidget(self._splitter, stretch=1)

        # ── 已选座位信息 ──
        info_layout = QHBoxLayout()
        self._selected_info = QLabel("未选择座位")
        self._selected_info.setStyleSheet(
            "padding: 6px; background-color: #e8f0fe; border-radius: 4px;"
        )
        info_layout.addWidget(self._selected_info, stretch=1)
        layout.addLayout(info_layout)

        # ── 预约操作栏 ──
        action_layout = QHBoxLayout()

        self._book_selected_btn = QPushButton("预约选中座位")
        self._book_selected_btn.setMinimumHeight(36)
        self._book_selected_btn.setStyleSheet(
            "QPushButton { background-color: #34a853; color: white;"
            " border: none; border-radius: 6px; font-size: 14px;"
            " font-weight: bold; padding: 0 20px; }"
            "QPushButton:hover { background-color: #2d9249; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._book_selected_btn.clicked.connect(self._on_book_selected)
        self._book_selected_btn.setEnabled(False)
        action_layout.addWidget(self._book_selected_btn)

        self._book_auto_btn = QPushButton("一键智能选座")
        self._book_auto_btn.setMinimumHeight(36)
        self._book_auto_btn.setStyleSheet(
            "QPushButton { background-color: #f9ab00; color: white;"
            " border: none; border-radius: 6px; font-size: 14px;"
            " font-weight: bold; padding: 0 20px; }"
            "QPushButton:hover { background-color: #e09a00; }"
            "QPushButton:disabled { background-color: #ccc; }"
        )
        self._book_auto_btn.clicked.connect(self._on_auto_book)
        self._book_auto_btn.setEnabled(False)
        action_layout.addWidget(self._book_auto_btn)
        action_layout.addStretch()

        self._status_label = QLabel("请先加载区域信息，再查询座位")
        self._status_label.setStyleSheet("padding: 4px;")
        action_layout.addWidget(self._status_label)
        layout.addLayout(action_layout)

    # ── 视图切换 ─────────────────────────────────────────

    def _toggle_view(self):
        """在地图和列表视图之间切换。"""
        is_list = self._toggle_view_btn.isChecked()
        self._map_container.setVisible(not is_list)
        self._seat_table.setVisible(is_list)
        self._toggle_view_btn.setText("地图视图" if is_list else "列表视图")
        if not is_list and not self._map_loaded and self._current_map_seats:
            self._load_plan_and_seats(self._current_map_seats)

    # ── 事件处理 ─────────────────────────────────────────

    def _on_load_area(self):
        """加载区域列表并获取页面数据。"""
        if not self._seat_api:
            QMessageBox.warning(self, "提示", "请先登录")
            return

        self._status_label.setText("Step 1/2: 正在获取区域列表...")
        QApplication.processEvents()

        area_source = "unknown"
        try:
            cats = self._seat_api.get_categories()
            if cats:
                self._area_combo.clear()
                count = 0
                for c in cats:
                    if not c["disabled"]:
                        label = f'{c["name"]}（{c["space"]}）' if c.get("space") else c["name"]
                        self._area_combo.addItem(label, (c["category_id"], c["content_id"]))
                        count += 1
                area_source = "API"
                self._status_label.setText(
                    f"Step 1/2: 从 API 获取到 {count} 个可用区域（共 {len(cats)} 个分类）"
                )
            else:
                raise Exception("API 返回空分类列表")
        except Exception as e:
            area_source = "本地"
            logger.warning(f"API 获取区域失败: {e}，回退到本地列表")
            self._area_combo.clear()
            for cat_id, cont_id, name in KNOWN_AREAS:
                self._area_combo.addItem(name, (cat_id, cont_id))
            self._status_label.setText(
                f"Step 1/2: API 获取失败({str(e)[:40]})，使用本地 {len(KNOWN_AREAS)} 个预设区域"
            )

        QApplication.processEvents()

        self._status_label.setText(
            self._status_label.text() + " | Step 2/2: 加载区域详情..."
        )
        QApplication.processEvents()

        idx = self._area_combo.currentIndex()
        if idx < 0:
            self._status_label.setText("❌ 区域列表为空，无法加载详情")
            return

        cat_id, cont_id = self._area_combo.currentData()
        logger.info(f"load_seat_page: cat_id={cat_id}, cont_id={cont_id}, source={area_source}")

        try:
            data = self._seat_api.load_seat_page(cat_id, cont_id)
            self._time_range = SeatAPI.parse_time_range(data)

            max_date = self._time_range.get("max_date")
            if max_date:
                self._date_picker.setMaximumDate(
                    QDate(max_date.year, max_date.month, max_date.day)
                )

            uid_ok = bool(self._seat_api.uid)
            self._status_label.setText(
                f"✅ 区域已加载 | uid={'有效' if uid_ok else '缺失❗'} | "
                f"来源={area_source} | "
                f"可约至 {max_date.strftime('%m-%d') if max_date else '?'}"
            )
            if not uid_ok:
                logger.error(
                    f"load_seat_page 返回成功但 uid 为空!"
                )
        except Exception as e:
            logger.exception("加载区域详情失败")
            self._status_label.setText(
                f"❌ 区域详情加载失败: {str(e)[:80]}"
            )

    def _on_query_seats(self):
        """查询座位并显示图形化地图。"""
        if not self._seat_api or not self._seat_api.uid:
            QMessageBox.warning(self, "提示", "请先加载区域信息")
            return

        idx = self._area_combo.currentIndex()
        if idx < 0:
            return
        cat_id, cont_id = self._area_combo.currentData()

        qdate = self._date_picker.date()
        qtime = self._start_time.time()
        begin_dt = datetime(
            qdate.year(), qdate.month(), qdate.day(),
            qtime.hour(), qtime.minute(), 0,
            tzinfo=BEIJING_TZ,
        )

        duration_hours = self._duration_spin.time().hour() or 4

        self._status_label.setText("查询中...")
        self._query_btn.setEnabled(False)

        try:
            resp = self._seat_api.search_seats(cat_id, cont_id, begin_dt, duration_hours)
            seats = SeatAPI.parse_seats_from_response(resp)
            self._all_seats = seats
            self._map_loaded = False
            self._map_info = self._seat_api.get_last_map_info()
            self._map_infos = self._seat_api.get_last_map_infos()

            available = [s for s in seats if s.status == 1]
            display_seats = available if available else seats
            self._display_source_seats = display_seats
            self._populate_venue_combo(seats)
            self._current_seats = self._filter_seats_by_venue(display_seats)
            self._current_map_seats = self._filter_seats_by_venue(seats)
            self._status_label.setText(
                f"共 {len(seats)} 个座位，可选 {len(available)} 个，场馆 {self._venue_count()} 个"
            )
            self._book_selected_btn.setEnabled(len(available) > 0)
            self._book_auto_btn.setEnabled(len(available) > 0)

            # 更新房间名
            room_name = self._map_info.room_name if self._map_info else "未知区域"
            self._room_name_label.setText(f"📍 {room_name}")

            self._map_view.clear_seats()

            # 表格优先展示可选座位，方便直接预约。
            self._populate_seat_table(self._current_seats)
            self._show_list_view()

        except Exception as e:
            logger.exception("查询座位失败")
            self._status_label.setText(f"查询失败: {e}")
        finally:
            self._query_btn.setEnabled(True)

    def _load_plan_and_seats(self, seats: list[SeatInfo]):
        """加载平面图，在上面绘制座位。"""
        self._map_view.clear_seats()
        self._populate_map_available_list(seats)

        venue = self._selected_venue()
        if not venue:
            self._load_grouped_native_maps(seats)
            return

        if venue:
            map_info = self._map_infos.get(venue) or SeatMapInfo(room_name=venue)
        else:
            map_info = self._map_info or SeatMapInfo(room_name=venue)
        self._room_name_label.setText(f"📍 {map_info.room_name or venue or '未知区域'}")

        pixmap = None
        use_plan_image = self._use_plan_image_cb.isChecked()
        if use_plan_image and map_info.plan_url:
            plan_url = map_info.plan_url
            try:
                logger.info(f"下载平面图: {plan_url}")
                content = self._download_plan_image(plan_url)
                if content:
                    img_data = QByteArray(content)
                    loaded = QPixmap()
                    loaded.loadFromData(img_data)
                    if not loaded.isNull():
                        pixmap = loaded
                        logger.info(
                            f"平面图加载成功: {pixmap.width()}x{pixmap.height()}"
                        )
            except Exception as e:
                logger.warning(f"平面图下载异常: {e}")

        # 如果没有平面图，创建空白背景
        if not pixmap or pixmap.isNull():
            logger.info("使用原生座位图背景")
            # 根据坐标范围创建一个合适的背景
            max_x = max((s.x + max(s.width, 1) for s in seats), default=133)
            max_y = max((s.y + max(s.height, 1) for s in seats), default=86)
            if not map_info.map_width:
                map_info.map_width = max_x
            if not map_info.map_height:
                map_info.map_height = max_y
            scale = 10
            margin = 40
            pw = max(map_info.map_width * scale + margin * 2, 800)
            ph = max(map_info.map_height * scale + margin * 2, 600)
            pixmap = QPixmap(pw, ph)
            pixmap.fill(QColor("#f0f0f0"))

        self._map_view.load_plan(pixmap)

        # 添加座位
        self._map_view.add_seats(seats, map_info)

        # 适应窗口
        self._map_view.fit_to_view()
        self._map_loaded = True

    def _load_grouped_native_maps(self, seats: list[SeatInfo]):
        """全部场馆视图：每个场馆使用独立坐标系分区摆放。"""
        grouped: dict[str, list[SeatInfo]] = {}
        for seat in seats:
            grouped.setdefault(seat.area_name or "未知场馆", []).append(seat)

        if not grouped:
            return

        scale = 10
        margin = 40
        title_h = 28
        section_gap = 48
        min_section_w = 800
        min_section_h = 220
        transformed: list[SeatInfo] = []
        sections: list[tuple[str, int, int, int, int]] = []
        y_cursor = margin
        canvas_w = min_section_w + margin * 2

        for venue_name, venue_seats in grouped.items():
            venue_map = self._map_infos.get(venue_name) or SeatMapInfo(room_name=venue_name)
            max_x = max((s.x + max(s.width, 1) for s in venue_seats), default=133)
            max_y = max((s.y + max(s.height, 1) for s in venue_seats), default=86)
            map_w = venue_map.map_width or max_x
            map_h = venue_map.map_height or max_y
            section_w = max(map_w * scale + margin * 2, min_section_w)
            section_h = max(map_h * scale + margin * 2 + title_h, min_section_h)
            x_offset = margin
            y_offset = y_cursor + title_h

            sections.append((venue_name, 0, y_cursor, section_w, section_h))
            canvas_w = max(canvas_w, section_w + margin * 2)

            for seat in venue_seats:
                transformed.append(replace(
                    seat,
                    x=x_offset + seat.x * scale,
                    y=y_offset + seat.y * scale,
                    width=max(seat.width, 1) * scale,
                    height=max(seat.height, 1) * scale,
                ))

            y_cursor += section_h + section_gap

        canvas_h = max(y_cursor + margin, 600)
        pixmap = QPixmap(canvas_w, canvas_h)
        pixmap.fill(QColor("#f0f0f0"))

        self._map_view.load_plan(pixmap)
        self._draw_group_sections(sections)
        self._map_view.add_seats(
            transformed,
            SeatMapInfo(room_name="全部场馆", map_width=canvas_w, map_height=canvas_h),
        )
        self._room_name_label.setText(f"📍 全部场馆（{len(grouped)} 个分区）")
        self._map_view.fit_to_view()
        self._map_loaded = True

    def _draw_group_sections(self, sections: list[tuple[str, int, int, int, int]]):
        """在全部场馆原生地图中绘制每个场馆的分区边界和标题。"""
        for venue_name, x, y, w, h in sections:
            self._map_view.scene().addRect(
                x + 12, y, w - 24, h,
                QPen(QColor("#d7dce2"), 1),
                QBrush(QColor("#f7f8fa")),
            )
            title = self._map_view.scene().addText(
                venue_name,
                QFont("Arial", 12, QFont.Weight.Bold),
            )
            title.setDefaultTextColor(QColor("#202124"))
            title.setPos(x + 28, y + 6)

    def _download_plan_image(self, plan_url: str) -> bytes | None:
        """短超时下载平面图，并缓存到本地，避免反复阻塞 UI。"""
        MAP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_key = hashlib.sha1(plan_url.encode("utf-8")).hexdigest()
        cache_file = MAP_CACHE_DIR / f"{cache_key}.img"
        if cache_file.exists() and cache_file.stat().st_size > 0:
            return cache_file.read_bytes()

        urls = [plan_url]
        if plan_url.startswith("https://"):
            urls.append("http://" + plan_url.removeprefix("https://"))

        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=0)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        headers = {}
        if self._seat_api:
            headers.update(self._seat_api._client.session.headers)

        for url in urls:
            try:
                resp = session.get(url, headers=headers, timeout=(2, 4), verify=False)
                if resp.status_code == 200 and resp.content:
                    cache_file.write_bytes(resp.content)
                    return resp.content
                logger.warning(f"平面图下载失败: HTTP {resp.status_code}, url={url}")
            except requests.RequestException as e:
                logger.warning(f"平面图下载失败: {e}, url={url}")
        return None

    def _show_list_view(self):
        """查询后自动展示座位列表。"""
        self._toggle_view_btn.setChecked(True)
        self._map_container.setVisible(False)
        self._seat_table.setVisible(True)
        self._toggle_view_btn.setText("地图视图")

    def _on_venue_changed(self):
        """按场馆刷新列表和地图，避免不同坐标系混在同一张图上。"""
        if not hasattr(self, "_seat_table"):
            return
        self._map_loaded = False
        self._selected_seat = None
        self._selected_info.setText("未选择座位")
        self._current_seats = self._filter_seats_by_venue(self._display_source_seats)
        self._current_map_seats = self._filter_seats_by_venue(self._all_seats)
        self._populate_seat_table(self._current_seats)
        self._map_view.clear_seats()
        if not self._toggle_view_btn.isChecked() and self._current_map_seats:
            self._load_plan_and_seats(self._current_map_seats)

    def _on_plan_background_changed(self):
        """切换官方平面图背景时重绘当前地图。"""
        self._map_loaded = False
        if not self._toggle_view_btn.isChecked() and self._current_map_seats:
            self._load_plan_and_seats(self._current_map_seats)

    def _populate_venue_combo(self, seats: list[SeatInfo]):
        """更新场馆筛选项，保留列表的全部场馆视图。"""
        current = self._selected_venue() if hasattr(self, "_venue_combo") else ""
        venues = []
        seen = set()
        for seat in seats:
            venue = seat.area_name or "未知场馆"
            if venue not in seen:
                seen.add(venue)
                venues.append(venue)

        self._venue_combo.blockSignals(True)
        self._venue_combo.clear()
        self._venue_combo.addItem("全部场馆", "")
        for venue in venues:
            count = sum(1 for seat in seats if (seat.area_name or "未知场馆") == venue)
            self._venue_combo.addItem(f"{venue}（{count}）", venue)
        idx = self._venue_combo.findData(current)
        self._venue_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._venue_combo.blockSignals(False)

    def _selected_venue(self) -> str:
        return str(self._venue_combo.currentData() or "")

    def _select_first_venue(self):
        if self._venue_combo.count() > 1:
            self._venue_combo.setCurrentIndex(1)

    def _filter_seats_by_venue(self, seats: list[SeatInfo]) -> list[SeatInfo]:
        venue = self._selected_venue()
        if not venue:
            return seats
        return [s for s in seats if (s.area_name or "未知场馆") == venue]

    def _venue_count(self) -> int:
        return max(self._venue_combo.count() - 1, 0)

    def _populate_map_available_list(self, seats: list[SeatInfo]):
        """刷新地图侧栏，只展示当前场馆可预约座位。"""
        self._map_available_list.clear()
        available = [seat for seat in seats if seat.status == 1]
        venue = self._selected_venue()
        if venue:
            self._map_available_title.setText(f"{venue} 可选座位")
        else:
            venues = {
                seat.area_name or "未知场馆"
                for seat in seats
                if seat.status == 1
            }
            self._map_available_title.setText(f"全部场馆可选座位（{len(venues)} 个场馆）")

        if not available:
            item = QListWidgetItem("暂无可预约座位")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._map_available_list.addItem(item)
            return

        for seat in available:
            suffix = " · 有插座" if seat.have_socket else ""
            if venue:
                label = f"{seat.seat_label}{suffix}"
            else:
                label = f"{seat.area_name or '未知场馆'} | {seat.seat_label}{suffix}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, seat.seat_id)
            item.setToolTip(f"{seat.seat_label} ({seat.area_name})")
            self._map_available_list.addItem(item)

    def _on_map_list_item_clicked(self, item: QListWidgetItem):
        """点击右侧可选座位列表时，在地图上定位并选中。"""
        seat_id = item.data(Qt.ItemDataRole.UserRole)
        if seat_id is None:
            return
        try:
            seat_id = int(seat_id)
        except (TypeError, ValueError):
            return
        self._map_view.select_seat(seat_id)

    def _on_seat_selected_from_map(self, seat: SeatInfo | None):
        """地图中选中/取消座位后的回调。"""
        self._selected_seat = seat
        if seat:
            self._selected_info.setText(
                f"✅ 已选座位: {seat.seat_label} ({seat.area_name})"
            )
            self._book_selected_btn.setEnabled(True)
            self._select_map_list_item(seat.seat_id)
        else:
            self._selected_info.setText("未选择座位")
            self._book_selected_btn.setEnabled(False)
            self._map_available_list.clearSelection()

    def _select_map_list_item(self, seat_id: int):
        """地图选中座位后，同步右侧列表选中状态。"""
        for idx in range(self._map_available_list.count()):
            item = self._map_available_list.item(idx)
            if item.data(Qt.ItemDataRole.UserRole) == seat_id:
                self._map_available_list.setCurrentItem(item)
                self._map_available_list.scrollToItem(item)
                return

    def _populate_seat_table(self, seats: list[SeatInfo]):
        """填充座位表格。"""
        for row in range(self._seat_table.rowCount()):
            self._seat_table.removeCellWidget(row, 3)
        self._seat_table.clearSpans()
        self._seat_table.clearContents()

        if not seats:
            self._seat_table.setRowCount(1)
            item = QTableWidgetItem("暂无可选座位。请确认已点击“查询座位”，或更换日期、时间、区域后重试。")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._seat_table.setItem(0, 0, item)
            self._seat_table.setSpan(0, 0, 1, 4)
            return

        self._seat_table.setRowCount(len(seats))

        for row, seat in enumerate(seats):
            self._seat_table.setItem(row, 0, QTableWidgetItem(seat.seat_label))
            self._seat_table.setItem(row, 1, QTableWidgetItem(seat.area_name))

            if seat.status == 1:
                status_text = "空闲"
                status_color = "#e6f4ea"
            else:
                status_text = "不可约"
                status_color = "#f1f3f4"

            status_item = QTableWidgetItem(status_text)
            status_item.setBackground(QColor(status_color))
            self._seat_table.setItem(row, 2, status_item)

            if seat.status == 1:
                book_btn = QPushButton("预约")
                book_btn.setStyleSheet(
                    "QPushButton { background-color: #1a73e8; color: white;"
                    " border: none; border-radius: 3px; padding: 4px 12px; }"
                    "QPushButton:hover { background-color: #1557b0; }"
                )
                book_btn.clicked.connect(
                    lambda checked, s=seat: self._book_single(s)
                )
                self._seat_table.setCellWidget(row, 3, book_btn)
            else:
                lbl = QLabel("不可预约")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setStyleSheet("color: #999;")
                self._seat_table.setCellWidget(row, 3, lbl)

    def _book_single(self, seat: SeatInfo):
        """预约单个座位。"""
        if not self._seat_api:
            return

        qdate = self._date_picker.date()
        qtime = self._start_time.time()
        begin_dt = datetime(
            qdate.year(), qdate.month(), qdate.day(),
            qtime.hour(), qtime.minute(), 0,
            tzinfo=BEIJING_TZ,
        )
        duration_hours = self._duration_spin.time().hour() or 4

        self._status_label.setText(f"正在预约 {seat.seat_label}...")

        try:
            result = self._seat_api.book_seat(seat.seat_id, begin_dt, duration_hours)

            if result.success:
                QMessageBox.information(
                    self, "预约成功",
                    f"座位 {seat.seat_label} 预约成功！\n"
                    f"区域：{seat.area_name}\n"
                    f"预约 ID：{result.booking_id}"
                )
                self._status_label.setText(f"预约成功 #{result.booking_id}")
                # 刷新座位状态
                self._on_query_seats()
            else:
                QMessageBox.warning(
                    self, "预约失败",
                    f"座位 {seat.seat_label} 预约失败：\n{result.message}"
                )
                self._status_label.setText(f"预约失败: {result.message}")

        except Exception as e:
            logger.exception("预约异常")
            self._status_label.setText(f"异常: {e}")

    def _on_book_selected(self):
        """预约地图或表格中选中的座位。"""
        if self._selected_seat:
            self._book_single(self._selected_seat)
        else:
            # 如果地图没选中，尝试表格当前行
            current = self._seat_table.currentRow()
            if current >= 0 and current < len(self._current_seats):
                self._book_single(self._current_seats[current])
            else:
                QMessageBox.warning(self, "提示", "请先在座位地图上点击选择一个空闲座位")

    def _on_auto_book(self):
        """一键智能选座。"""
        available = [s for s in self._current_seats if s.status == 1]
        if not available:
            QMessageBox.information(self, "提示", "当前没有可用座位")
            return

        target = available[0]
        reply = QMessageBox.question(
            self, "确认预约",
            f"将自动预约：{target.seat_label}\n"
            f"区域：{target.area_name}\n"
            f"确认预约？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._book_single(target)

    def set_status(self, message: str):
        self._status_label.setText(message)

    def _on_refresh_areas(self):
        self._on_load_area()
