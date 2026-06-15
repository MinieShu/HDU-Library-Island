"""
GUI 模块 - 登录面板

提供学号密码登录界面，支持记住密码功能。
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QCheckBox, QGroupBox,
    QFrame, QMessageBox, QSpacerItem, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
import logging

from api import APIClient, AuthAPI
from utils.config import Config

logger = logging.getLogger(__name__)


class LoginPanel(QWidget):
    """登录面板。"""

    login_success = pyqtSignal(dict)  # 登录成功后发送用户信息
    logout_signal = pyqtSignal()      # 登出信号

    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self._auth_api: AuthAPI | None = None
        self._is_logged_in = False
        self._user_info: dict | None = None
        self._setup_ui()
        self._load_saved_credentials()

    def _setup_ui(self):
        """初始化界面。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # ===== 标题 =====
        title = QLabel("杭电图书馆座位预约系统")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        subtitle = QLabel("HDU Library Auto Book")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #666; margin-bottom: 20px;")
        layout.addWidget(subtitle)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # ===== 登录表单 =====
        form_group = QGroupBox("用户登录")
        form_layout = QVBoxLayout(form_group)

        # 学号
        id_layout = QHBoxLayout()
        id_label = QLabel("学　号：")
        id_label.setFixedWidth(60)
        self._id_input = QLineEdit()
        self._id_input.setPlaceholderText("请输入学号")
        self._id_input.setMaxLength(20)
        id_layout.addWidget(id_label)
        id_layout.addWidget(self._id_input)
        form_layout.addLayout(id_layout)

        # 密码
        pwd_layout = QHBoxLayout()
        pwd_label = QLabel("密　码：")
        pwd_label.setFixedWidth(60)
        self._pwd_input = QLineEdit()
        self._pwd_input.setPlaceholderText("请输入数字杭电密码")
        self._pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pwd_input.returnPressed.connect(self._on_login_clicked)
        pwd_layout.addWidget(pwd_label)
        pwd_layout.addWidget(self._pwd_input)
        form_layout.addLayout(pwd_layout)

        # 记住密码 & 自动登录
        options_layout = QHBoxLayout()
        self._remember_cb = QCheckBox("记住密码")
        self._auto_login_cb = QCheckBox("启动时自动登录")
        options_layout.addWidget(self._remember_cb)
        options_layout.addWidget(self._auto_login_cb)
        options_layout.addStretch()
        form_layout.addLayout(options_layout)

        # API 地址配置（高级选项，可折叠）
        advanced_group = QGroupBox("高级设置")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        advanced_layout = QVBoxLayout(advanced_group)

        api_layout = QHBoxLayout()
        api_label = QLabel("API 地址：")
        api_label.setFixedWidth(80)
        self._api_input = QLineEdit()
        self._api_input.setPlaceholderText("https://hdu.huitu.zhishulib.com")
        self._api_input.setText(self._config.get("api.base_url", "https://hdu.huitu.zhishulib.com"))
        api_layout.addWidget(api_label)
        api_layout.addWidget(self._api_input)
        advanced_layout.addLayout(api_layout)

        api_hint = QLabel("杭电智慧图书馆系统，默认使用 zhishulib.com")
        api_hint.setStyleSheet("color: #999; font-size: 11px;")
        api_hint.setWordWrap(True)
        advanced_layout.addWidget(api_hint)

        form_layout.addWidget(advanced_group)

        # ===== 登录按钮 =====
        self._login_btn = QPushButton("登  录")
        self._login_btn.setMinimumHeight(40)
        self._login_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a73e8;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self._login_btn.clicked.connect(self._on_login_clicked)
        form_layout.addWidget(self._login_btn)

        # ===== 状态标签 =====
        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("padding: 8px; border-radius: 4px;")
        form_layout.addWidget(self._status_label)

        layout.addWidget(form_group)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # ===== 底部信息 =====
        footer = QLabel("仅供个人学习使用，请遵守学校图书馆规章制度")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(footer)

    def _load_saved_credentials(self):
        """加载保存的登录凭据。"""
        saved_id = self._config.get("auth.student_id", "")
        saved_pwd = self._config.get("auth.password", "")
        remember = self._config.get("auth.remember", False)
        auto_login = self._config.get("auth.auto_login", False)

        if saved_id:
            self._id_input.setText(saved_id)
        if saved_pwd:
            self._pwd_input.setText(saved_pwd)
        self._remember_cb.setChecked(remember)
        self._auto_login_cb.setChecked(auto_login)

    def _on_login_clicked(self):
        """点击登录按钮。"""
        student_id = self._id_input.text().strip()
        password = self._pwd_input.text()

        if not student_id or not password:
            self._show_status("请输入学号和密码", "error")
            return

        self._login_btn.setEnabled(False)
        self._login_btn.setText("登录中...")
        self._show_status("正在登录...", "info")

        try:
            base_url = self._api_input.text().strip() or "https://hdu.huitu.zhishulib.com"
            client = APIClient(
                base_url=base_url,
            )
            self._auth_api = AuthAPI(client)

            success = self._auth_api.login_by_password(student_id, password)

            if success:
                self._is_logged_in = True
                self._user_info = self._auth_api.user_info

                # 保存配置
                if self._remember_cb.isChecked():
                    self._config.set("auth.student_id", student_id)
                    self._config.set("auth.password", password)
                    self._config.set("auth.remember", True)
                else:
                    self._config.set("auth.password", "")
                    self._config.set("auth.remember", False)

                self._config.set("auth.auto_login", self._auto_login_cb.isChecked())
                self._config.set("api.base_url", base_url)
                self._config.save()

                self._show_status(f"登录成功！欢迎 {student_id}", "success")
                self._login_btn.setText("已登录")
                self._login_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #34a853;
                        color: white;
                        border: none;
                        border-radius: 6px;
                        font-size: 16px;
                        font-weight: bold;
                    }
                """)

                self.login_success.emit(self._user_info or {"student_id": student_id})
            else:
                self._show_status("登录失败，请检查学号和密码是否正确", "error")
                self._login_btn.setEnabled(True)
                self._login_btn.setText("登  录")

        except Exception as e:
            logger.exception(f"登录异常：{e}")
            self._show_status(f"登录异常：{e}", "error")
            self._login_btn.setEnabled(True)
            self._login_btn.setText("登  录")

    def _show_status(self, message: str, level: str = "info"):
        """显示状态信息。

        Args:
            message: 信息文本
            level: 'info', 'success', 'error', 'warning'
        """
        colors = {
            "info": "background-color: #e8f0fe; color: #1a73e8;",
            "success": "background-color: #e6f4ea; color: #137333;",
            "error": "background-color: #fce8e6; color: #c5221f;",
            "warning": "background-color: #fef7e0; color: #e37400;",
        }
        self._status_label.setStyleSheet(colors.get(level, colors["info"]))
        self._status_label.setText(message)

    def get_auth_api(self) -> AuthAPI | None:
        """获取认证 API 实例。"""
        return self._auth_api

    def get_api_client(self) -> APIClient | None:
        """获取 API 客户端实例。"""
        return self._auth_api._client if self._auth_api else None

    @property
    def is_logged_in(self) -> bool:
        return self._is_logged_in

    @property
    def user_info(self) -> dict | None:
        return self._user_info

    def try_auto_login(self) -> bool:
        """尝试自动登录（读取保存的凭据）。"""
        student_id = self._config.get("auth.student_id", "")
        password = self._config.get("auth.password", "")
        auto_login = self._config.get("auth.auto_login", False)

        if auto_login and student_id and password:
            self._id_input.setText(student_id)
            self._pwd_input.setText(password)
            self._on_login_clicked()
            return True
        return False
