"""Offscreen tests for the LinkForge GUI lifecycle."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Iterator

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from linkforge.application import ApplicationConfig
from linkforge.ui import MainWindow, RuntimeState


@pytest.fixture(scope="session")
def qt_application() -> Iterator[QApplication]:
    application = QApplication.instance() or QApplication([])
    yield application


def _wait_until(
    application: QApplication,
    condition: Callable[[], bool],
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        application.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for Qt state change")


def _fill_valid_form(window: MainWindow, *, api_key: str = "test-secret") -> None:
    window.course_url_edit.setText("https://example.test/course")
    window.model_edit.setText("test-model")
    window.api_key_edit.setText(api_key)
    window.profile_dir_edit.setText("browser-profile")


class BlockingApplication:
    def __init__(self) -> None:
        self.run_started = threading.Event()
        self.release = threading.Event()
        self.stop_called = threading.Event()
        self.run_thread_id: int | None = None

    def run(self) -> None:
        self.run_thread_id = threading.get_ident()
        self.run_started.set()
        if not self.release.wait(timeout=3):
            raise RuntimeError("test application did not receive release")

    def stop(self) -> None:
        self.stop_called.set()
        self.release.set()


def test_main_window_constructs_with_idle_controls(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)

    assert window.state is RuntimeState.IDLE
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.api_key_edit.echoMode() == window.api_key_edit.EchoMode.Password
    assert window.log_edit.isReadOnly()

    window.close()
    qt_application.processEvents()


def test_start_validates_input_without_creating_worker(
    qt_application: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    factory_calls = 0

    def factory(_config: ApplicationConfig) -> BlockingApplication:
        nonlocal factory_calls
        factory_calls += 1
        return BlockingApplication()

    window = MainWindow(application_factory=factory, error_presenter=lambda *_args: None)  # type: ignore[arg-type]
    window.start_button.click()

    assert warnings == ["请输入课程地址。"]
    assert factory_calls == 0
    assert window.state is RuntimeState.IDLE
    assert window.start_button.isEnabled()

    window.close()
    qt_application.processEvents()


def test_gui_log_shows_only_translated_user_messages(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)
    runtime_logger = logging.getLogger("linkforge.application.task_runner")
    previous_level = runtime_logger.level
    runtime_logger.setLevel(logging.INFO)

    runtime_logger.info("Detected task type: VIDEO")
    runtime_logger.error("Authorization: secret-value")
    qt_application.processEvents()

    visible_log = window.log_edit.toPlainText()
    assert "当前任务：视频" in visible_log
    assert "secret-value" not in visible_log
    runtime_logger.setLevel(previous_level)
    window.close()
    qt_application.processEvents()


def test_runtime_runs_off_main_thread_and_can_run_again(
    qt_application: QApplication,
) -> None:
    fake = BlockingApplication()
    main_thread_id = threading.get_ident()
    factory_calls = 0

    def factory(_config: ApplicationConfig) -> BlockingApplication:
        nonlocal factory_calls
        factory_calls += 1
        return fake

    window = MainWindow(application_factory=factory, error_presenter=lambda *_args: None)  # type: ignore[arg-type]
    _fill_valid_form(window)
    window.start_button.click()

    assert fake.run_started.wait(timeout=2)
    _wait_until(qt_application, lambda: window.state is RuntimeState.RUNNING)
    assert fake.run_thread_id != main_thread_id
    assert not window.start_button.isEnabled()
    assert window.stop_button.isEnabled()

    fake.release.set()
    _wait_until(qt_application, lambda: window._thread is None)
    assert window.state is RuntimeState.FINISHED
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert factory_calls == 1

    window.close()
    qt_application.processEvents()


def test_worker_error_is_visible_and_api_key_is_redacted(
    qt_application: QApplication,
) -> None:
    api_key = "top-secret-api-key"
    presented: list[tuple[str, str]] = []

    class FailingApplication:
        def run(self) -> None:
            raise RuntimeError(f"provider rejected credential {api_key}")

        def stop(self) -> None:
            pass

    window = MainWindow(
        application_factory=lambda _config: FailingApplication(),  # type: ignore[arg-type]
        error_presenter=lambda error_type, summary: presented.append((error_type, summary)),
    )
    _fill_valid_form(window, api_key=api_key)
    window.start_button.click()

    _wait_until(qt_application, lambda: window._thread is None)
    assert window.state is RuntimeState.ERROR
    assert presented and presented[0][0] == "RuntimeError"
    visible_text = f"{presented!r}\n{window.log_edit.toPlainText()}"
    assert api_key not in visible_text
    assert "[已隐藏]" in presented[0][1]
    assert window.start_button.isEnabled()

    window.close()
    qt_application.processEvents()


def test_stop_calls_application_stop_and_prevents_duplicate_start(
    qt_application: QApplication,
) -> None:
    fake = BlockingApplication()
    factory_calls = 0

    def factory(_config: ApplicationConfig) -> BlockingApplication:
        nonlocal factory_calls
        factory_calls += 1
        return fake

    window = MainWindow(application_factory=factory, error_presenter=lambda *_args: None)  # type: ignore[arg-type]
    _fill_valid_form(window)
    window.start_button.click()
    assert fake.run_started.wait(timeout=2)
    _wait_until(qt_application, lambda: window.state is RuntimeState.RUNNING)

    window.start_button.click()
    assert factory_calls == 1
    window.stop_button.click()
    assert window.state is RuntimeState.STOPPING
    assert fake.stop_called.wait(timeout=1)
    assert not window.stop_button.isEnabled()

    _wait_until(qt_application, lambda: window._thread is None)
    assert window.state is RuntimeState.FINISHED

    window.close()
    qt_application.processEvents()


def test_close_running_window_requests_safe_stop(qt_application: QApplication) -> None:
    fake = BlockingApplication()
    window = MainWindow(
        application_factory=lambda _config: fake,  # type: ignore[arg-type]
        error_presenter=lambda *_args: None,
    )
    _fill_valid_form(window)
    window.show()
    window.start_button.click()
    assert fake.run_started.wait(timeout=2)
    _wait_until(qt_application, lambda: window.state is RuntimeState.RUNNING)

    assert not window.close()
    assert window.state is RuntimeState.STOPPING
    assert fake.stop_called.wait(timeout=1)
    _wait_until(qt_application, lambda: window._thread is None)
    _wait_until(qt_application, lambda: not window.isVisible())
