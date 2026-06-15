"""
GUI 模块 - 主窗口

整合登录、座位预约、定时调度等功能模块。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout,
    QLabel, QStatusBar, QMessageBox, QApplication,
    QMenuBar, QMenu, QSystemTrayIcon, QStyle,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon
import logging

from utils.config import Config
from api import APIClient, AuthAPI, SeatAPI, RoomAPI
from .login_panel import LoginPanel
from .seat_panel import SeatBookingPanel
from .schedule_panel import SchedulePanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """杭电图书馆座位预约系统主窗口。"""

    def __init__(self, config: Config):
        super().__init__()
        self._config = config
        self._api_client: APIClient | None = None
        self._auth_api: AuthAPI | None = None
        self._seat_api: SeatAPI | None = None
        self._room_api: RoomAPI | None = None

        self.setWindowTitle("杭电图书馆座位预约系统 v1.0")
        self.setMinimumSize(960, 680)
        self.resize(1100, 750)

        self._setup_menu()
        self._setup_ui()
        self._setup_status_bar()

    def _setup_menu(self):
        """设置菜单栏。"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")
        self._logout_action = QAction("重新登录", self)
        self._logout_action.triggered.connect(self._on_logout)
        self._logout_action.setEnabled(False)
        file_menu.addAction(self._logout_action)

        file_menu.addSeparator()

        exit_action = QAction("退出(&Q)", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        guide_action = QAction("使用说明", self)
        guide_action.triggered.connect(self._show_guide)
        help_menu.addAction(guide_action)

    def _setup_ui(self):
        """初始化主界面。"""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Tab 页
        self._tab_widget = QTabWidget()

        # 登录页
        self._login_panel = LoginPanel(self._config)
        self._login_panel.login_success.connect(self._on_login_success)
        self._tab_widget.addTab(self._login_panel, "🔐 登录")

        # 座位预约页（初始禁用）
        self._seat_panel = SeatBookingPanel()
        self._tab_widget.addTab(self._seat_panel, "💺 座位预约")
        self._tab_widget.setTabEnabled(1, False)

        # 定时调度页（初始禁用）
        self._schedule_panel = SchedulePanel()
        self._tab_widget.addTab(self._schedule_panel, "⏰ 定时抢座")
        self._tab_widget.setTabEnabled(2, False)

        layout.addWidget(self._tab_widget)

    def _setup_status_bar(self):
        """设置状态栏。"""
        self._status_label = QLabel("请先登录")
        self.statusBar().addWidget(self._status_label, 1)

        self._user_label = QLabel("")
        self.statusBar().addPermanentWidget(self._user_label)

    def _on_login_success(self, user_info: dict):
        """登录成功后的处理。"""
        client = self._login_panel.get_api_client()
        auth = self._login_panel.get_auth_api()

        if not client or not auth:
            return

        self._api_client = client
        self._auth_api = auth

        # 初始化各模块 API
        self._seat_api = SeatAPI(client)
        self._room_api = RoomAPI(client)

        # 更新各面板的 API 客户端
        self._seat_panel.set_api_client(client, auth)
        self._schedule_panel.set_api_client(client, self._seat_api, self._room_api)

        # 启用各面板
        self._tab_widget.setTabEnabled(1, True)
        self._tab_widget.setTabEnabled(2, True)

        # 记录用户信息
        student_id = self._config.get("auth.student_id", "未知")
        self._user_label.setText(f"用户：{student_id}")

        # 切换到座位预约页
        self._tab_widget.setCurrentIndex(1)
        self._tab_widget.setTabText(0, "✅ 已登录")

        # 首次自动刷新区域
        QTimer.singleShot(500, self._auto_refresh_areas)

        # 更新菜单
        self._logout_action.setEnabled(True)

        student_name = user_info.get("name") or user_info.get("studentId") or ""
        self._status_label.setText(f"登录成功！欢迎 {student_name}")

        logger.info("登录成功，所有模块已就绪")

    def _auto_refresh_areas(self):
        """自动刷新座位区域列表。"""
        self._seat_panel._on_refresh_areas()
        self._status_label.setText("已加载座位区域数据")

    def _on_logout(self):
        """重新登录。"""
        self._auth_api = None
        self._seat_api = None
        self._room_api = None

        self._schedule_panel.shutdown()

        # 重置面板状态
        self._tab_widget.setTabEnabled(1, False)
        self._tab_widget.setTabEnabled(2, False)
        self._tab_widget.setTabText(0, "🔐 登录")
        self._tab_widget.setCurrentIndex(0)

        self._status_label.setText("请先登录")
        self._user_label.setText("")
        self._logout_action.setEnabled(False)

        logger.info("已退出登录")

    def _show_about(self):
        """显示关于信息。"""
        QMessageBox.about(
            self,
            "关于 杭电图书馆座位预约系统",
            "<h3>杭电图书馆座位预约系统 v1.0</h3>"
            "<p>杭州电子科技大学图书馆座位自动预约工具</p>"
            "<hr>"
            "<p>功能特点：</p>"
            "<ul>"
            "<li>座位预约 - 查询/预约图书馆座位</li>"
            "<li>定时抢座 - 每晚 20:00 自动抢座</li>"
            "</ul>"
            "<hr>"
            "<p><b>免责声明</b></p>"
            "<p>本工具仅供个人学习交流使用。<br>"
            "请遵守杭州电子科技大学图书馆相关规章制度。<br>"
            "请勿利用本工具占座不去，以免影响他人正常使用。</p>"
            "<hr>"
            "<p style='color: #999;'>Python + PyQt6</p>"
        )

    def _show_guide(self):
        """显示使用说明。"""
        QMessageBox.information(
            self,
            "使用说明",
            "<h3>快速开始</h3>"
            "<ol>"
            "<li><b>登录</b> - 输入学号和数字杭电密码</li>"
            "<li><b>座位预约</b> - 选择区域、时间，查询并预约空闲座位</li>"
            "<li><b>定时抢座</b> - 设置定时任务，每晚 20:00 自动抢座</li>"
            "</ol>"
            "<h3>定时抢座说明</h3>"
            "<p>系统每晚 <b>20:00</b> 开放预约后两天的座位。</p>"
            "<p>定时任务支持在 20:00 准时发起预约，"
            "并可在失败时自动重试，大幅提高抢座成功率。</p>"
            "<h3>注意事项</h3>"
            "<ul>"
            "<li>请确保学号和密码正确</li>"
            "<li>如果系统 API 地址变更，请在登录页高级设置中修改</li>"
            "<li>签到需要到现场扫码或蓝牙签到</li>"
            "</ul>"
        )

    def closeEvent(self, event):
        """关闭窗口事件。"""
        self._schedule_panel.shutdown()
        event.accept()
