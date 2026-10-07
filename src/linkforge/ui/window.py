"""Main LinkForge desktop window."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTime, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFontDatabase, QShowEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from linkforge.application import ApplicationConfig
from linkforge.composition import create_application
from linkforge.config import MODEL_PROVIDERS, BrowserConfig, ModelConfig, create_model_config
from linkforge.ui.community import CommunityDialog
from linkforge.ui.settings import UserSettings, UserSettingsStore, default_profile_dir
from linkforge.ui.worker import ApplicationFactory, GuiLogHandler, RuntimeWorker

logger = logging.getLogger(__name__)

_PROVIDER_DISPLAY_NAMES = {
    "deepseek": "DeepSeek",
    "qwen": "通义千问 Qwen",
    "gemini": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
}


class RuntimeState(Enum):
    """User-visible runtime lifecycle states."""

    IDLE = "空闲"
    STARTING = "正在启动"
    RUNNING = "运行中"
    STOPPING = "正在停止"
    FINISHED = "已完成"
    ERROR = "发生错误"


class MainWindow(QMainWindow):
    """Collect runtime configuration and supervise one worker at a time."""

    def __init__(
        self,
        *,
        application_factory: ApplicationFactory = create_application,
        error_presenter: Callable[[str, str], None] | None = None,
        settings_store: UserSettingsStore | None = None,
        log_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._application_factory = application_factory
        self._settings_store = settings_store if settings_store is not None else UserSettingsStore()
        self._error_presenter = error_presenter or self._show_error_dialog
        self._log_dir = log_dir
        self._state = RuntimeState.IDLE
        self._thread: QThread | None = None
        self._worker: RuntimeWorker | None = None
        self._close_when_finished = False
        self._log_handler = GuiLogHandler()
        self._log_handler.emitter.message.connect(self._append_log)
        logging.getLogger("linkforge").addHandler(self._log_handler)
        self.community_dialog = CommunityDialog(self)
        self._community_reminder_scheduled = False

        self.setWindowTitle("LinkForge")
        self.resize(1000, 680)
        self.setMinimumSize(760, 560)
        self.setCentralWidget(self._build_central_widget())
        self.statusBar().showMessage("就绪")
        self._restore_settings()
        self._apply_state()

    @property
    def state(self) -> RuntimeState:
        return self._state

    def _build_central_widget(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)

        layout.addLayout(self._build_header())
        layout.addWidget(self._separator())
        layout.addLayout(self._build_configuration())
        layout.addLayout(self._build_controls())
        layout.addWidget(self._separator())
        layout.addLayout(self._build_log_area(), stretch=1)
        return root

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        title = QLabel("LinkForge")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(title)
        layout.addStretch()
        layout.addWidget(self.status_label)
        return layout

    def _build_configuration(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(10)

        course_heading = QLabel("课程")
        course_heading.setStyleSheet("font-weight: 600;")
        self.course_url_edit = QLineEdit()
        self.course_url_edit.setObjectName("courseUrlEdit")
        self.course_url_edit.setPlaceholderText("粘贴学习通课程页面地址")
        course_form = QFormLayout()
        course_form.addRow("课程地址", self.course_url_edit)
        layout.addWidget(course_heading)
        layout.addLayout(course_form)

        model_heading = QLabel("模型")
        model_heading.setStyleSheet("font-weight: 600;")
        self.provider_combo = QComboBox()
        self.provider_combo.setObjectName("providerCombo")
        for provider_key, provider_info in MODEL_PROVIDERS.items():
            display_name = _PROVIDER_DISPLAY_NAMES.get(provider_key, str(provider_info["display_name"]))
            self.provider_combo.addItem(display_name, provider_key)

        self.model_edit = QLineEdit()
        self.model_edit.setObjectName("modelEdit")
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setObjectName("apiKeyEdit")
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_toggle = QPushButton("显示")
        self.api_key_toggle.setCheckable(True)
        self.api_key_toggle.setObjectName("apiKeyToggle")
        self.api_key_toggle.toggled.connect(self._toggle_api_key)
        api_layout = QHBoxLayout()
        api_layout.setContentsMargins(0, 0, 0, 0)
        api_layout.addWidget(self.api_key_edit)
        api_layout.addWidget(self.api_key_toggle)
        api_widget = QWidget()
        api_widget.setLayout(api_layout)

        provider_model_layout = QHBoxLayout()
        provider_form = QFormLayout()
        provider_form.addRow("模型服务商", self.provider_combo)
        model_form = QFormLayout()
        model_form.addRow("模型", self.model_edit)
        provider_model_layout.addLayout(provider_form)
        provider_model_layout.addLayout(model_form)
        model_form_full = QFormLayout()
        model_form_full.addRow("API Key", api_widget)
        layout.addWidget(model_heading)
        layout.addLayout(provider_model_layout)
        layout.addLayout(model_form_full)

        browser_heading = QLabel("浏览器")
        browser_heading.setStyleSheet("font-weight: 600;")
        self.profile_dir_edit = QLineEdit()
        self.profile_dir_edit.setObjectName("profileDirEdit")
        self.profile_dir_edit.setPlaceholderText("选择或输入浏览器用户目录")
        self.profile_browse_button = QPushButton("选择目录")
        self.profile_browse_button.clicked.connect(self._choose_profile_directory)
        profile_layout = QHBoxLayout()
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self.profile_dir_edit)
        profile_layout.addWidget(self.profile_browse_button)
        profile_widget = QWidget()
        profile_widget.setLayout(profile_layout)
        profile_form = QFormLayout()
        profile_form.addRow("浏览器用户目录", profile_widget)
        help_label = QLabel("用于保存学习通登录状态；登录过期时需要重新登录。")
        help_label.setStyleSheet("color: #606770;")
        layout.addWidget(browser_heading)
        layout.addLayout(profile_form)
        layout.addWidget(help_label)

        self._configuration_widgets = (
            self.course_url_edit,
            self.provider_combo,
            self.model_edit,
            self.api_key_edit,
            self.api_key_toggle,
            self.profile_dir_edit,
            self.profile_browse_button,
        )
        self._set_default_model()
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        return layout

    def _build_controls(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.feedback_button = QPushButton("用户反馈")
        self.feedback_button.setObjectName("feedbackButton")
        self.feedback_button.clicked.connect(self.community_dialog.open_feedback)
        self.development_button = QPushButton("参与开发")
        self.development_button.setObjectName("developmentButton")
        self.development_button.clicked.connect(self.community_dialog.open_repository)
        layout.addWidget(self.feedback_button)
        layout.addWidget(self.development_button)
        layout.addStretch()
        self.start_button = QPushButton("开始运行")
        self.start_button.setObjectName("startButton")
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self._request_stop)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        return layout

    def _build_log_area(self) -> QVBoxLayout:
        layout = QVBoxLayout()
        header = QHBoxLayout()
        heading = QLabel("运行日志")
        heading.setStyleSheet("font-weight: 600;")
        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self._clear_log)
        header.addWidget(heading)
        header.addStretch()
        self.open_logs_button = QPushButton("打开日志文件夹")
        self.open_logs_button.setEnabled(self._log_dir is not None)
        self.open_logs_button.clicked.connect(self._open_log_directory)
        header.addWidget(self.open_logs_button)
        header.addWidget(clear_button)
        self.log_edit = QTextEdit()
        self.log_edit.setObjectName("runtimeLogEdit")
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_edit.setStyleSheet(
            "QTextEdit { background: #fafafa; border: 1px solid #c8ccd0; border-radius: 4px; }"
        )
        layout.addLayout(header)
        layout.addWidget(self.log_edit)
        return layout

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        return separator

    def _set_default_model(self) -> None:
        provider = self.provider_combo.currentData()
        if isinstance(provider, str):
            self.model_edit.setText(str(MODEL_PROVIDERS[provider]["default_model"]))

    def _toggle_api_key(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.api_key_edit.setEchoMode(mode)
        self.api_key_toggle.setText("隐藏" if visible else "显示")

    def _restore_settings(self) -> None:
        settings = self._settings_store.load()
        self.course_url_edit.setText(settings.course_url)
        self.profile_dir_edit.setText(settings.profile_dir or default_profile_dir())
        index = self.provider_combo.findData(settings.provider)
        if index >= 0:
            self.provider_combo.blockSignals(True)
            self.provider_combo.setCurrentIndex(index)
            self.provider_combo.blockSignals(False)
            self._set_default_model()
            if settings.model:
                self.model_edit.setText(settings.model)
        self._load_provider_api_key()

    def _on_provider_changed(self) -> None:
        self._set_default_model()
        self._load_provider_api_key()

    def _load_provider_api_key(self) -> None:
        # Clear the previous provider's key before any credential lookup.
        self.api_key_edit.clear()
        self.api_key_toggle.setChecked(False)
        self._toggle_api_key(False)
        provider = self.provider_combo.currentData()
        if isinstance(provider, str):
            self.api_key_edit.setText(self._settings_store.load_api_key(provider) or "")

    def _choose_profile_directory(self) -> None:
        initial = self.profile_dir_edit.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(self, "选择浏览器用户目录", initial)
        if selected:
            self.profile_dir_edit.setText(selected)

    def _start(self) -> None:
        if self._thread is not None:
            return
        validated = self._validated_config()
        if validated is None:
            return
        settings, model_config, browser_config = validated
        saved_settings = self._settings_store.save(settings)
        saved_key = self._settings_store.save_api_key(settings.provider, model_config.api_key)
        if not saved_settings or not saved_key:
            self._append_log("部分配置未能保存，本次运行仍将继续。")
        config = ApplicationConfig(
            course_url=settings.course_url,
            browser_config=browser_config,
            model_config=model_config,
        )

        self._set_state(RuntimeState.STARTING, "正在启动 LinkForge…")
        self._append_log("正在启动 LinkForge")
        thread = QThread(self)
        worker = RuntimeWorker(config, self._application_factory)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.running.connect(self._on_running)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _validated_config(self) -> tuple[UserSettings, ModelConfig, BrowserConfig] | None:
        course_url = self.course_url_edit.text().strip()
        provider = self.provider_combo.currentData()
        model = self.model_edit.text().strip()
        api_key = self.api_key_edit.text().strip()
        profile_dir = self.profile_dir_edit.text().strip() or None
        if not course_url:
            self._validation_error("请输入课程地址。")
            return None
        if not isinstance(provider, str) or not provider:
            self._validation_error("请选择模型服务商。")
            return None
        if not model:
            self._validation_error("请输入模型。")
            return None
        if not api_key:
            self._validation_error("请输入 API Key。")
            return None
        try:
            model_config = create_model_config(provider=provider, api=api_key, model_name=model)
            browser_config = BrowserConfig(headless=False, profile_dir=profile_dir)
            settings = UserSettings(course_url, provider, model, profile_dir or "")
            return settings, model_config, browser_config
        except ValueError as exc:
            logger.error("GUI configuration validation failed with %s", type(exc).__name__)
            self._validation_error("运行配置无效，请检查输入内容。")
            return None

    def _validation_error(self, message: str) -> None:
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "无法开始运行", message)

    def _request_stop(self) -> None:
        if self._worker is None or self._state not in {
            RuntimeState.STARTING,
            RuntimeState.RUNNING,
        }:
            return
        self._worker.request_stop()
        self._set_state(RuntimeState.STOPPING, "当前任务完成后将安全退出。")
        self._append_log("正在停止，当前任务完成后将安全退出")

    def _on_running(self) -> None:
        if self._state is not RuntimeState.STOPPING:
            self._set_state(RuntimeState.RUNNING, "LinkForge 正在运行")
            self._append_log("LinkForge 已开始运行")

    def _on_completed(self) -> None:
        self._set_state(RuntimeState.FINISHED, "运行已完成，可以再次开始。")
        self._append_log("运行已完成")

    def _on_failed(self, error_type: str, summary: str) -> None:
        self._set_state(RuntimeState.ERROR, "运行失败，可以修改配置后重试。")
        self._append_log(f"运行出错：{error_type}")
        self._error_presenter(error_type, summary)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._apply_state()
        if self._close_when_finished:
            QTimer.singleShot(0, self.close)

    def _set_state(self, state: RuntimeState, status_message: str) -> None:
        self._state = state
        self.statusBar().showMessage(status_message)
        self._apply_state()

    def _apply_state(self) -> None:
        active = self._thread is not None
        editable = (
            self._state
            in {
                RuntimeState.IDLE,
                RuntimeState.FINISHED,
                RuntimeState.ERROR,
            }
            and not active
        )
        for widget in self._configuration_widgets:
            widget.setEnabled(editable)
        self.start_button.setEnabled(editable)
        self.stop_button.setEnabled(self._state is RuntimeState.RUNNING and active)
        color = "#b42318" if self._state is RuntimeState.ERROR else "#374151"
        self.status_label.setText(f"● {self._state.value}")
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def _append_log(self, message: str) -> None:
        if self._state is RuntimeState.RUNNING:
            if message.startswith("等待登录："):
                self.statusBar().showMessage("等待登录：请在浏览器中完成学习通登录。")
            elif message == "课程页面已就绪，开始课程任务":
                self.statusBar().showMessage("LinkForge 正在运行")
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        self.log_edit.append(f"{timestamp}  {message}")
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_log(self) -> None:
        self.log_edit.clear()

    def _open_log_directory(self) -> None:
        if self._log_dir is None:
            return
        try:
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_dir.resolve())))
        except Exception:
            opened = False
        if not opened:
            QMessageBox.warning(self, "无法打开日志文件夹", f"请手动打开以下目录：\n{self._log_dir}")

    def _show_error_dialog(self, error_type: str, summary: str) -> None:
        QMessageBox.critical(
            self,
            "运行出错",
            f"LinkForge 在执行课程任务时发生错误。\n\n{summary}\n\n错误类型：{error_type}",
        )

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._community_reminder_scheduled:
            self._community_reminder_scheduled = True
            QTimer.singleShot(0, self._show_community_reminder)

    def _show_community_reminder(self) -> None:
        if self.isVisible():
            self.community_dialog.show()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._thread is not None:
            self._close_when_finished = True
            self._request_stop()
            event.ignore()
            return
        logging.getLogger("linkforge").removeHandler(self._log_handler)
        self._log_handler.close()
        self.community_dialog.reject()
        event.accept()
