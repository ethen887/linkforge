"""问题内容的暂缓、导航恢复及脱敏记录。"""

import logging
from dataclasses import replace

import pytest

import linkforge.platforms.chaoxing.recovery as recovery_module
from linkforge.application.task_runner import TaskType, UnknownTaskError
from linkforge.browser.exceptions import BrowserClosedError
from linkforge.platforms.chaoxing.exceptions import ContentNavigationError, VideoPlaybackError
from linkforge.platforms.chaoxing.models import ChaoxingModuleState, ChaoxingPageState
from linkforge.platforms.chaoxing.recovery import ChaoxingTaskRecovery
from linkforge.platforms.chaoxing.video_state import VideoSession
from tests.fakes import FakeBrowser


def _state() -> ChaoxingPageState:
    return ChaoxingPageState(
        content_frame_url="https://example.test/mooc-ans/knowledge/cards?token=private",
        knowledge_id="100",
        active_tab_index=0,
        has_next_tab=True,
        modules=(
            ChaoxingModuleState("https://example.test/ananas/modules/video/one", True, False, (0, 0)),
            ChaoxingModuleState("https://example.test/ananas/modules/video/two", True, False, (0, 1)),
        ),
        videos=(),
    )


class FakeNavigator:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def skip_failed_card(self, expected, *, should_stop=None):
        self.calls += 1
        if self.fail:
            raise ContentNavigationError("token=private")
        return not (should_stop is not None and should_stop())


def _recovery(monkeypatch):
    state = _state()
    monkeypatch.setattr(recovery_module, "inspect_chaoxing_page", lambda browser: state)
    browser = FakeBrowser()
    navigator = FakeNavigator()
    session = VideoSession()
    recovery = ChaoxingTaskRecovery(browser, navigator, video_session=session)
    recovery.checkpoint()
    return recovery, browser, navigator, session, state


def test_failed_videos_are_deferred_individually_without_completing_them(monkeypatch, caplog):
    recovery, browser, navigator, session, state = _recovery(monkeypatch)
    error = VideoPlaybackError("token=private https://secret.example.test")
    with caplog.at_level(logging.WARNING):
        assert recovery.recover(TaskType.VIDEO, error, None)
        assert session.is_deferred(state, 0)
        assert not session.is_deferred(state, 1)
        assert not session.is_handled(state, 0)
        recovery.checkpoint()
        assert recovery.recover(TaskType.VIDEO, error, None)
    assert session.is_deferred(state, 1)
    assert navigator.calls == 0
    assert len(browser.frame_evaluation_calls) == 2
    assert len(recovery.issues) == 2
    assert "private" not in caplog.text
    assert "secret.example" not in caplog.text
    assert "待补做" in caplog.text
    assert not VideoSession().is_deferred(state, 0)


@pytest.mark.parametrize(
    "task_type", [TaskType.DOCUMENT, TaskType.COMMENT, TaskType.QUIZ, TaskType.UNKNOWN]
)
def test_failed_card_advances_once_and_does_not_loop(monkeypatch, task_type):
    recovery, _, navigator, _, _ = _recovery(monkeypatch)
    error = UnknownTaskError("private")
    assert recovery.recover(task_type, error, None)
    assert not recovery.recover(task_type, error, None)
    assert navigator.calls == 1


def test_failed_navigation_is_reported_and_not_retried(monkeypatch):
    recovery, _, navigator, _, _ = _recovery(monkeypatch)
    navigator.fail = True
    assert not recovery.recover(TaskType.VIDEO, ContentNavigationError("private"), None)
    assert len(recovery.issues) == 1
    assert "未能继续" in recovery.issues[0].outcome


def test_stop_records_issue_without_starting_recovery(monkeypatch):
    recovery, browser, navigator, _, _ = _recovery(monkeypatch)
    assert recovery.recover(TaskType.VIDEO, VideoPlaybackError("private"), lambda: True)
    assert navigator.calls == 0
    assert browser.frame_evaluation_calls == []
    assert "用户已停止" in recovery.issues[0].outcome


def test_browser_closed_in_exception_chain_is_fatal(monkeypatch):
    recovery, _, navigator, _, _ = _recovery(monkeypatch)
    error = VideoPlaybackError("private")
    error.__cause__ = BrowserClosedError("private")
    assert not recovery.recover(TaskType.VIDEO, error, None)
    assert navigator.calls == 0


def test_changed_video_card_is_not_deferred(monkeypatch):
    recovery, _, navigator, session, state = _recovery(monkeypatch)
    monkeypatch.setattr(
        recovery_module, "inspect_chaoxing_page", lambda browser: replace(state, active_tab_index=1)
    )
    # 视频暂缓拒绝变更后的页面；真实导航器还会再次校验原卡片身份。
    navigator.fail = True
    assert not recovery.recover(TaskType.VIDEO, VideoPlaybackError("private"), None)
    assert not session.is_deferred(state, 0)


def test_unexpected_programming_error_is_not_hidden(monkeypatch):
    recovery, _, navigator, _, _ = _recovery(monkeypatch)
    assert not recovery.recover(TaskType.VIDEO, TypeError("bug"), None)
    assert navigator.calls == 0
    assert recovery.issues == []
