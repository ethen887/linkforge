"""Offscreen checks for startup reminders and explicit external-link routing."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QMessageBox

from linkforge.ui import MainWindow, RuntimeState, community
from linkforge.ui.settings import UserSettingsStore
from tests.fakes import FakeCredentialStore


@pytest.fixture(scope="session")
def qt_application() -> Iterator[QApplication]:
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def opened_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def open_url(url: QUrl) -> bool:
        urls.append(url.toString())
        return True

    monkeypatch.setattr(QDesktopServices, "openUrl", open_url)
    return urls


@pytest.fixture
def window(qt_application: QApplication, tmp_path: Path, opened_urls: list[str]) -> Iterator[MainWindow]:
    settings = UserSettingsStore(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
        credentials=FakeCredentialStore(),
    )
    window = MainWindow(settings_store=settings)
    yield window
    for notice in window.findChildren(QMessageBox):
        notice.close()
    window.close()
    qt_application.processEvents()


def test_startup_reminder_is_non_modal_and_never_opens_browser_automatically(
    window: MainWindow,
    qt_application: QApplication,
    opened_urls: list[str],
) -> None:
    assert not window.community_dialog.isVisible()
    window.show()
    qt_application.processEvents()
    assert window.community_dialog.isVisible()
    assert window.community_dialog.windowModality() is Qt.WindowModality.NonModal
    assert window.start_button.isEnabled()
    assert opened_urls == []
    window.community_dialog.later_button.click()
    assert not window.community_dialog.isVisible()
    assert window.isVisible()
    window.hide()
    window.show()
    qt_application.processEvents()
    assert not window.community_dialog.isVisible()


def test_new_window_gets_reminder_even_after_previous_window_dismissed(
    window: MainWindow,
    qt_application: QApplication,
) -> None:
    window.show()
    qt_application.processEvents()
    window.community_dialog.reject()
    window.close()
    next_window = MainWindow(settings_store=window._settings_store)
    try:
        next_window.show()
        qt_application.processEvents()
        assert next_window.community_dialog.isVisible()
    finally:
        next_window.close()


def test_close_before_queued_reminder_does_not_leave_a_dialog(
    window: MainWindow,
    qt_application: QApplication,
) -> None:
    window.show()
    window.close()
    qt_application.processEvents()
    assert not window.community_dialog.isVisible()


@pytest.mark.parametrize("dismissed", [False, True])
def test_closing_main_window_closes_feedback_notice(
    window: MainWindow,
    qt_application: QApplication,
    dismissed: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(community, "FEEDBACK_FORM_URL", "")
    window.show()
    qt_application.processEvents()
    if dismissed:
        window.community_dialog.reject()
    window.feedback_button.click()
    notice = window.community_dialog.findChild(QMessageBox)
    assert notice is not None and notice.isVisible()
    window.close()
    qt_application.processEvents()
    assert not notice.isVisible()


def test_unconfigured_feedback_shows_notice_without_fallback_or_browser(
    window: MainWindow,
    opened_urls: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(community, "FEEDBACK_FORM_URL", "")
    window.feedback_button.click()
    notice = window.community_dialog.findChild(QMessageBox)
    assert notice is not None
    assert "暂未开放" in notice.text()
    assert notice.windowModality() is Qt.WindowModality.NonModal
    assert opened_urls == []


def test_feedback_buttons_open_only_public_form_without_configuration_data(
    window: MainWindow,
    opened_urls: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    address = "https://jinshuju.net/f/example"
    monkeypatch.setattr(community, "FEEDBACK_FORM_URL", address)
    window.course_url_edit.setText("https://example.test/private-course")
    window.api_key_edit.setText("private-key")
    window.feedback_button.click()
    window.community_dialog.feedback_button.click()
    assert opened_urls == [address, address]


def test_repository_and_guide_routes_are_correct_and_available_while_running(
    window: MainWindow,
    opened_urls: list[str],
) -> None:
    window._set_state(RuntimeState.RUNNING, "运行中")
    assert window.feedback_button.isEnabled()
    assert window.development_button.isEnabled()
    window.development_button.click()
    window.community_dialog.development_button.click()
    window.community_dialog.guide_button.click()
    assert opened_urls == [community.REPOSITORY_URL, community.REPOSITORY_URL, community.CONTRIBUTING_URL]


def test_browser_open_failure_preserves_window_and_displays_manual_address(
    window: MainWindow,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window.community_dialog, "_url_opener", lambda _url: False)
    window.development_button.click()
    notice = window.community_dialog.findChild(QMessageBox)
    assert notice is not None
    assert "复制" in notice.text()
    assert community.REPOSITORY_URL in notice.text()
    assert window.state is RuntimeState.IDLE


@pytest.mark.parametrize(
    "address",
    [
        "http://example.test",
        "file:///tmp/form",
        "javascript:alert(1)",
        "https://user:password@example.test/form",
    ],
)
def test_invalid_feedback_link_is_not_opened(
    window: MainWindow,
    opened_urls: list[str],
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    monkeypatch.setattr(community, "FEEDBACK_FORM_URL", address)
    window.feedback_button.click()
    assert opened_urls == []
    notice = window.community_dialog.findChild(QMessageBox)
    assert notice is not None
    assert "正确配置" in notice.text()
    assert address not in notice.text()
