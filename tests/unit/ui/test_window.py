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
from linkforge.config import MODEL_PROVIDERS
from linkforge.ui import MainWindow, RuntimeState
from linkforge.ui.settings import CREDENTIAL_SERVICE, UserSettings, UserSettingsStore
from tests.fakes import FakeCredentialStore


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


def test_gui_shows_manual_login_wait_and_course_readiness(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)
    startup_logger = logging.getLogger("linkforge.platforms.chaoxing.startup")
    previous_level = startup_logger.level
    try:
        startup_logger.setLevel(logging.INFO)
        window._set_state(RuntimeState.RUNNING, "LinkForge 正在运行")
        startup_logger.info("Chaoxing manual login required")
        qt_application.processEvents()
        assert "请在浏览器中完成学习通登录" in window.log_edit.toPlainText()
        assert "等待登录" in window.statusBar().currentMessage()
        startup_logger.info("Chaoxing course page ready")
        qt_application.processEvents()
        assert "课程页面已就绪，开始课程任务" in window.log_edit.toPlainText()
        assert window.statusBar().currentMessage() == "LinkForge 正在运行"
    finally:
        startup_logger.setLevel(previous_level)
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


def test_first_launch_preserves_default_model_and_empty_key(
    qt_application, isolated_settings_store
) -> None:
    window = MainWindow()
    try:
        provider = window.provider_combo.currentData()
        assert window.model_edit.text() == MODEL_PROVIDERS[provider]["default_model"]
        assert window.course_url_edit.text() == ""
        assert window.profile_dir_edit.text().endswith("browser-profile")
        assert window.api_key_edit.text() == ""
    finally:
        window.close()


def test_launch_restores_all_preferences_and_only_current_provider_key(
    qt_application, isolated_settings_store: UserSettingsStore
) -> None:
    settings = UserSettings("https://example.test/course", "deepseek", "custom-model", "test-profile")
    isolated_settings_store.save(settings)
    isolated_settings_store.save_api_key("deepseek", "test-deepseek-key")
    isolated_settings_store.save_api_key("openai", "test-openai-key")
    window = MainWindow()
    try:
        assert window.course_url_edit.text() == settings.course_url
        assert window.provider_combo.currentData() == "deepseek"
        assert window.model_edit.text() == "custom-model"
        assert window.profile_dir_edit.text() == "test-profile"
        assert window.api_key_edit.text() == "test-deepseek-key"
        assert window.api_key_edit.echoMode() == window.api_key_edit.EchoMode.Password
    finally:
        window.close()


def test_provider_switch_refreshes_key_and_remasks_it(qt_application, isolated_settings_store) -> None:
    for provider in ("deepseek", "openai"):
        isolated_settings_store.save_api_key(provider, f"test-{provider}-key")
    window = MainWindow()
    try:
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("deepseek"))
        assert window.api_key_edit.text() == "test-deepseek-key"
        window.api_key_toggle.click()
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("openai"))
        assert window.api_key_edit.text() == "test-openai-key"
        assert window.model_edit.text() == MODEL_PROVIDERS["openai"]["default_model"]
        assert window.api_key_edit.echoMode() == window.api_key_edit.EchoMode.Password
        assert not window.api_key_toggle.isChecked()
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("gemini"))
        assert window.api_key_edit.text() == ""
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("deepseek"))
        assert window.api_key_edit.text() == "test-deepseek-key"
    finally:
        window.close()


def test_unknown_saved_provider_uses_default_provider_and_model(
    qt_application, isolated_settings_store
) -> None:
    isolated_settings_store.save(UserSettings(provider="removed-provider", model="stale-model"))
    window = MainWindow()
    try:
        provider = window.provider_combo.currentData()
        assert provider == next(iter(MODEL_PROVIDERS))
        assert window.model_edit.text() == MODEL_PROVIDERS[provider]["default_model"]
        assert window.api_key_edit.text() == ""
    finally:
        window.close()


def test_credential_read_failure_on_launch_and_switch_clears_key_without_crashing(
    qt_application, isolated_settings_store, caplog
) -> None:
    credentials = isolated_settings_store._credentials
    assert isinstance(credentials, FakeCredentialStore)
    credentials.read_error = RuntimeError("test-sensitive-backend-key")
    window = MainWindow()
    try:
        assert window.api_key_edit.text() == ""
        window.api_key_edit.setText("test-old-key")
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("openai"))
        assert window.api_key_edit.text() == ""
        assert window.start_button.isEnabled()
        assert "test-sensitive-backend-key" not in caplog.text
        assert "test-sensitive-backend-key" not in window.log_edit.toPlainText()
    finally:
        window.close()


def test_start_saves_validated_values_before_worker_construction(
    qt_application, isolated_settings_store, monkeypatch
) -> None:
    events = []
    real_save = isolated_settings_store.save
    real_save_key = isolated_settings_store.save_api_key
    fake = BlockingApplication()

    def save(settings):
        events.append("preferences")
        assert settings == UserSettings(
            "https://example.test/course", "openai", "test-model", "browser-profile"
        )
        return real_save(settings)

    def save_key(provider, api_key):
        events.append("credential")
        assert provider == "openai" and api_key == "test-openai-key"
        return real_save_key(provider, api_key)

    def factory(config):
        events.append("runtime")
        assert config.course_url == "https://example.test/course"
        assert config.model_config.api_key == "test-openai-key"
        assert config.model_config.model_name == "test-model"
        assert config.browser_config.profile_dir == "browser-profile"
        return fake

    monkeypatch.setattr(isolated_settings_store, "save", save)
    monkeypatch.setattr(isolated_settings_store, "save_api_key", save_key)
    window = MainWindow(application_factory=factory)
    try:
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("openai"))
        _fill_valid_form(window, api_key="test-openai-key")
        assert events == []
        window.start_button.click()
        assert fake.run_started.wait(timeout=2)
        assert events == ["preferences", "credential", "runtime"]
        fake.release.set()
        _wait_until(qt_application, lambda: window._thread is None)
        assert isolated_settings_store.load().provider == "openai"
        assert isolated_settings_store.load_api_key("openai") == "test-openai-key"
    finally:
        fake.release.set()
        _wait_until(qt_application, lambda: window._thread is None)
        window.close()


@pytest.mark.parametrize("field", ["course_url_edit", "model_edit", "api_key_edit"])
def test_invalid_start_does_not_overwrite_saved_settings_or_credential(
    qt_application, isolated_settings_store, monkeypatch, field
) -> None:
    original = UserSettings(
        "https://example.test/original", "deepseek", "original-model", "original-profile"
    )
    isolated_settings_store.save(original)
    isolated_settings_store.save_api_key("deepseek", "test-deepseek-key")
    credentials = isolated_settings_store._credentials
    assert isinstance(credentials, FakeCredentialStore)
    writes_before = len(credentials.set_calls)
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: None)
    window = MainWindow()
    try:
        _fill_valid_form(window)
        getattr(window, field).setText("   ")
        window.start_button.click()
        assert window._thread is None
        assert isolated_settings_store.load() == original
        assert len(credentials.set_calls) == writes_before
    finally:
        window.close()


def test_persistence_write_failures_allow_runtime_and_do_not_expose_key(
    qt_application, isolated_settings_store, monkeypatch, caplog
) -> None:
    credentials = isolated_settings_store._credentials
    assert isinstance(credentials, FakeCredentialStore)
    credentials.write_error = RuntimeError("test-openai-key")
    monkeypatch.setattr(isolated_settings_store._settings, "setValue", lambda *_args: None)
    from PySide6.QtCore import QSettings

    monkeypatch.setattr(isolated_settings_store._settings, "status", lambda: QSettings.Status.AccessError)
    fake = BlockingApplication()
    window = MainWindow(application_factory=lambda _config: fake)
    try:
        window.provider_combo.setCurrentIndex(window.provider_combo.findData("openai"))
        _fill_valid_form(window, api_key="test-openai-key")
        window.start_button.click()
        assert fake.run_started.wait(timeout=2)
        fake.release.set()
        _wait_until(qt_application, lambda: window._thread is None)
        assert window.state is RuntimeState.FINISHED
        assert "部分配置未能保存" in window.log_edit.toPlainText()
        assert "test-openai-key" not in caplog.text
        assert "test-openai-key" not in window.log_edit.toPlainText()
        assert isolated_settings_store._settings.allKeys() == []
        assert credentials.set_calls == [(CREDENTIAL_SERVICE, "api_key:openai")]
    finally:
        fake.release.set()
        _wait_until(qt_application, lambda: window._thread is None)
        window.close()


def test_close_does_not_save_edited_preferences_or_key(qt_application, isolated_settings_store) -> None:
    window = MainWindow()
    _fill_valid_form(window)
    window.close()
    assert isolated_settings_store.load() == UserSettings()
    assert isolated_settings_store.load_api_key("qwen") is None


def test_corrupted_preferences_do_not_block_window_startup(
    qt_application, isolated_settings_store, caplog
) -> None:
    isolated_settings_store._settings.setValue("gui/provider", ["test-sensitive-details"])
    window = MainWindow()
    try:
        assert window.start_button.isEnabled()
        assert window.provider_combo.currentData() == next(iter(MODEL_PROVIDERS))
        assert window.course_url_edit.text() == window.api_key_edit.text() == ""
        assert "test-sensitive-details" not in caplog.text
    finally:
        window.close()
