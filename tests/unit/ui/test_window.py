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
from linkforge.application.issues import RunIssue
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


@pytest.mark.parametrize("saved", [False, True])
def test_draft_review_is_distinct_from_completion_and_can_stop(qt_application, saved):
    release = threading.Event()

    class ReviewApplication:
        issues = []
        review_required = True

        def __init__(self, config):
            self.config = config

        def run(self):
            self.config.on_review_required(saved)
            assert release.wait(3)

        def stop(self):
            release.set()

    window = MainWindow(application_factory=ReviewApplication, error_presenter=lambda *_: None)
    _fill_valid_form(window)
    window.start_button.click()
    try:
        _wait_until(qt_application, lambda: window.state is RuntimeState.REVIEW)
        assert window.stop_button.isEnabled()
        assert not window.start_button.isEnabled()
        assert ("草稿已暂存" if saved else "未全部确认暂存") in window.statusBar().currentMessage()
        window.stop_button.click()
        _wait_until(qt_application, lambda: window._thread is None)
        assert "以网页为准" in window.statusBar().currentMessage()
        assert "运行已完成" not in window.log_edit.toPlainText()
    finally:
        release.set()
        window.close()


@pytest.mark.parametrize("outcome", ["complete", "stop", "error"])
def test_worker_checkpoint_updates_ui_and_persists_before_exit(
    qt_application: QApplication,
    isolated_settings_store: UserSettingsStore,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    latest = "https://example.test/mycourse/studentstudy?chapterId=200&num=1&enc=test-route-secret"
    release = threading.Event()
    main_thread = threading.get_ident()
    save_threads: list[int] = []
    real_save = isolated_settings_store.save_course_url

    def save(url: str) -> bool:
        save_threads.append(threading.get_ident())
        return real_save(url)

    monkeypatch.setattr(isolated_settings_store, "save_course_url", save)

    class ProgressApplication:
        def __init__(self, config: ApplicationConfig) -> None:
            self.config = config

        def run(self) -> None:
            assert threading.get_ident() != main_thread
            assert self.config.on_course_url_changed is not None
            self.config.on_course_url_changed(latest)
            assert release.wait(timeout=3)
            if outcome == "error":
                raise RuntimeError("test failure after navigation")

        def stop(self) -> None:
            release.set()

    window = MainWindow(application_factory=ProgressApplication, error_presenter=lambda *_args: None)  # type: ignore[arg-type]
    _fill_valid_form(window)
    window.start_button.click()
    try:
        _wait_until(qt_application, lambda: window.course_url_edit.text() == latest)
        assert isolated_settings_store.load().course_url == latest
        assert save_threads == [main_thread]
        assert "test-route-secret" not in window.log_edit.toPlainText()
        if outcome == "stop":
            window._request_stop()
        else:
            release.set()
        _wait_until(qt_application, lambda: window._thread is None)
        assert window.state is (RuntimeState.ERROR if outcome == "error" else RuntimeState.FINISHED)
        window.close()
        reopened = MainWindow(error_presenter=lambda *_args: None)
        assert reopened.course_url_edit.text() == latest
        reopened.close()
    finally:
        release.set()
        _wait_until(qt_application, lambda: window._thread is None)
        window.close()


def test_checkpoint_save_failure_keeps_latest_address_visible(
    qt_application: QApplication,
    isolated_settings_store: UserSettingsStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(isolated_settings_store, "save_course_url", lambda _url: False)
    window = MainWindow(error_presenter=lambda *_args: None)
    window._on_course_url_changed("https://example.test/latest")
    assert window.course_url_edit.text() == "https://example.test/latest"
    assert "未能保存" in window.log_edit.toPlainText()
    window.close()


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


def test_gui_translates_video_stall_recovery(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)
    video_logger = logging.getLogger("linkforge.platforms.chaoxing.video_handler")
    previous_level = video_logger.level
    try:
        video_logger.setLevel(logging.INFO)
        video_logger.info("Video stall recovery requested")
        qt_application.processEvents()
        assert "视频播放暂时停滞" in window.log_edit.toPlainText()
    finally:
        video_logger.setLevel(previous_level)
        window.close()


def test_gui_reports_formula_stages_without_raw_browser_errors(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)
    formula_logger = logging.getLogger("linkforge.platforms.chaoxing.written_formula")
    previous_level = formula_logger.level
    try:
        formula_logger.setLevel(logging.INFO)
        formula_logger.info("TEX 公式：%s", "等待新公式预览稳定")
        formula_logger.warning("TEX 公式：预览未就绪，确认前重新输入一次")
        formula_logger.info("TEX 公式：已确认预览，开始上传并等待插入（不重复确认）")
        formula_logger.error("PRIVATE-URL PRIVATE-FORMULA")
        qt_application.processEvents()
        shown = window.log_edit.toPlainText()
        assert "等待新公式预览稳定" in shown
        assert "确认前重新输入一次" in shown
        assert "开始上传并等待插入" in shown
        assert "PRIVATE-" not in shown
    finally:
        formula_logger.setLevel(previous_level)
        window.close()


def test_gui_reports_editor_wait_and_broken_formula_recovery(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)
    draft_logger = logging.getLogger("linkforge.platforms.chaoxing.written_assignment")
    previous_level = draft_logger.level
    try:
        draft_logger.setLevel(logging.INFO)
        draft_logger.info("第 %d 题：等待编辑器初始化、已有答案恢复或公式加载", 1)
        draft_logger.info("第 %d 题：编辑器已就绪，继续生成草稿", 1)
        draft_logger.warning("第 %d 题：已有公式图片加载失败，公式数据完整，将生成完整草稿后重做", 2)
        draft_logger.warning(
            "第 %d 题：等待编辑器就绪超时，原因：%s", 3, "大题编辑器正在初始化，正文尚不可编辑。"
        )
        draft_logger.error("PRIVATE-URL PRIVATE-ANSWER")
        qt_application.processEvents()
        shown = window.log_edit.toPlainText()
        assert "第 1 题：等待编辑器初始化" in shown
        assert "第 1 题：编辑器已就绪" in shown
        assert "第 2 题：已有公式图片加载失败" in shown
        assert "第 3 题：等待编辑器就绪超时" in shown
        assert "PRIVATE-" not in shown
    finally:
        draft_logger.setLevel(previous_level)
        window.close()


def test_gui_reports_following_the_selected_course_page(qt_application: QApplication) -> None:
    window = MainWindow(error_presenter=lambda *_args: None)
    navigation_logger = logging.getLogger("linkforge.platforms.chaoxing.navigation")
    previous_level = navigation_logger.level
    try:
        navigation_logger.setLevel(logging.INFO)
        navigation_logger.info("Following the selected Chaoxing course page")
        qt_application.processEvents()
        assert "正在跟随当前选择的内容" in window.log_edit.toPlainText()
    finally:
        navigation_logger.setLevel(previous_level)
        window.close()


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
    assert presented and presented[0][0] == "运行异常"
    visible_text = f"{presented!r}\n{window.log_edit.toPlainText()}"
    assert api_key not in visible_text
    assert "尚未分类" in presented[0][1]
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
    assert "取消模型等待" in window.statusBar().currentMessage()
    assert "当前任务完成后" not in window.log_edit.toPlainText()

    _wait_until(qt_application, lambda: window._thread is None)
    assert window.state is RuntimeState.FINISHED
    assert "运行已停止" in window.statusBar().currentMessage()

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


@pytest.mark.parametrize("action", ["stop", "close"])
def test_gui_cancels_inflight_model_and_cleans_resources(qt_application, monkeypatch, action):
    import asyncio
    from types import SimpleNamespace

    from linkforge.application.runtime import LinkForgeApplication
    from linkforge.llm.base import LLMMessage
    from linkforge.llm.openai import OpenAIInterface
    from tests.fakes import FakeBrowser

    monkeypatch.setattr(logging.getLogger("linkforge"), "level", logging.INFO)
    started = threading.Event()
    cleaned = threading.Event()
    submitted = []
    errors = []

    async def slow_stream(self, progress, options):
        started.set()
        try:
            await asyncio.sleep(300)
        finally:
            cleaned.set()

    monkeypatch.setattr(OpenAIInterface, "_stream", slow_stream)

    class Platform:
        def prepare(self, **kwargs):
            return True

        def build_runner(self, *, browser, llm, model):
            def run(**kwargs):
                llm.call_json_model(model, [LLMMessage("user", "PRIVATE-QUESTION")])
                submitted.append(True)

            return SimpleNamespace(run=run)

    browser = FakeBrowser()

    def factory(config):
        return LinkForgeApplication(config=config, platform=Platform(), browser_factory=lambda _: browser)

    window = MainWindow(application_factory=factory, error_presenter=lambda *args: errors.append(args))
    _fill_valid_form(window)
    window.show()
    window.start_button.click()
    _wait_until(qt_application, started.is_set)
    _wait_until(qt_application, lambda: window.state is RuntimeState.RUNNING)
    if action == "close":
        window.close()
    else:
        window.stop_button.click()
    _wait_until(qt_application, lambda: window._thread is None, timeout=2)
    assert cleaned.is_set()
    assert not submitted
    assert not errors
    assert window.state is RuntimeState.FINISHED
    if action == "stop":
        text = window.log_edit.toPlainText()
        assert "已取消，连接已关闭" in text
        assert "PRIVATE" not in text
        window.close()


@pytest.mark.parametrize("outcome", ["stop", "close", "finish", "error"])
def test_run_issues_are_shown_once_after_cleanup(qt_application: QApplication, outcome: str) -> None:
    issue = RunIssue("第 2 张卡片，第 1 个模块", "视频", "视频无法正常播放", "已暂缓，待补做")

    class ApplicationWithIssues(BlockingApplication):
        def __init__(self) -> None:
            super().__init__()
            self.issues = [issue]

        def run(self) -> None:
            super().run()
            if outcome == "error":
                raise RuntimeError("failure after a recoverable issue")

    fake = ApplicationWithIssues()
    summaries: list[str] = []

    def present(summary: str) -> None:
        summaries.append(summary)
        # 模拟问题弹窗的嵌套事件循环：后台线程结束不能提前关闭主窗口。
        qt_application.processEvents()
        assert window.isVisible()

    window = MainWindow(
        application_factory=lambda config: fake,  # type: ignore[arg-type]
        error_presenter=lambda *_args: None,
        issue_presenter=present,
    )
    _fill_valid_form(window)
    window.show()
    window.start_button.click()
    assert fake.run_started.wait(timeout=2)
    _wait_until(qt_application, lambda: window.state is RuntimeState.RUNNING)
    if outcome == "close":
        window.close()
    elif outcome == "stop":
        window.stop_button.click()
    else:
        fake.release.set()
    _wait_until(qt_application, lambda: window._thread is None and len(summaries) == 1)
    assert issue.describe() in summaries[0]
    assert issue.describe() in window.log_edit.toPlainText()
    assert window.state is (RuntimeState.ERROR if outcome == "error" else RuntimeState.FINISHED_WITH_ISSUES)
    if outcome == "close":
        _wait_until(qt_application, lambda: not window.isVisible())
    else:
        window.close()


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
