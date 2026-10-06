"""User feedback and open-source participation, without uploading runtime data."""

from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

# Public feedback form; never append runtime configuration or credentials.
FEEDBACK_FORM_URL = "https://mhhvya3d.jsjform.com/f/NqrEmH"
REPOSITORY_URL = "https://github.com/ethen887/linkforge"
CONTRIBUTING_URL = f"{REPOSITORY_URL}/blob/main/CONTRIBUTING.md"


class CommunityDialog(QDialog):
    """A dismissible, non-modal reminder with explicit external-link actions."""

    def __init__(
        self,
        parent: QWidget,
        *,
        url_opener: Callable[[QUrl], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._url_opener = url_opener if url_opener is not None else QDesktopServices.openUrl
        self._notice: QMessageBox | None = None
        self.setObjectName("communityDialog")
        self.setWindowTitle("一起改进 LinkForge")
        self.setModal(False)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        introduction = QLabel(
            "使用过程中遇到问题，或有功能建议？欢迎通过用户反馈告诉我们。\n"
            "点击“反馈问题”即可打开在线反馈表单。"
        )
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        invitation = QLabel(
            "如果你是开发者，也欢迎参与 LinkForge 开源项目，开发你需要的功能。\n"
            "请先阅读贡献指南，通过 Issue 讨论需求和实现方案，再提交 Pull Request。"
        )
        invitation.setWordWrap(True)
        layout.addWidget(invitation)
        repository = QLabel(f"GitHub 仓库：{REPOSITORY_URL}")
        repository.setWordWrap(True)
        layout.addWidget(repository)
        self.guide_button = QPushButton("阅读贡献指南")
        self.guide_button.clicked.connect(self.open_contributing)
        layout.addWidget(self.guide_button)
        privacy = QLabel("反馈时请勿提供 API Key、Cookie、账号密码或完整课程链接。")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        actions = QHBoxLayout()
        self.feedback_button = QPushButton("反馈问题")
        self.feedback_button.clicked.connect(self.open_feedback)
        self.development_button = QPushButton("参与开发")
        self.development_button.clicked.connect(self.open_repository)
        self.later_button = QPushButton("稍后再说")
        self.later_button.clicked.connect(self.reject)
        self.later_button.setDefault(True)
        for button in (self.feedback_button, self.development_button, self.later_button):
            actions.addWidget(button)
        layout.addLayout(actions)

    def open_feedback(self) -> None:
        """Open only the configured form; do not fall back to a login-only service."""
        if not FEEDBACK_FORM_URL:
            self._show_notice("用户反馈", "反馈入口暂未开放，敬请期待。")
            return
        self._open_url(FEEDBACK_FORM_URL)

    def reject(self) -> None:
        """Dismiss child notices too, including when the reminder is hidden."""
        if self._notice is not None:
            self._notice.close()
        super().reject()

    def open_repository(self) -> None:
        self._open_url(REPOSITORY_URL)

    def open_contributing(self) -> None:
        self._open_url(CONTRIBUTING_URL)

    def _open_url(self, address: str) -> None:
        url = QUrl(address)
        if not url.isValid() or url.scheme() != "https" or not url.host() or url.userInfo():
            self._show_notice("无法打开页面", "入口链接尚未正确配置，请联系项目维护者。")
            return
        if not self._url_opener(url):
            self._show_notice(
                "无法打开页面", f"无法打开默认浏览器，请复制以下地址到浏览器访问：\n{address}"
            )

    def _show_notice(self, title: str, text: str) -> None:
        if self._notice is None:
            self._notice = QMessageBox(self)
            self._notice.setModal(False)
            self._notice.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._notice.setWindowTitle(title)
        self._notice.setText(text)
        self._notice.show()
