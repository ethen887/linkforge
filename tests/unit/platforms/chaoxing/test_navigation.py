"""手动换页的稳定性确认、停止优先和续播位置同步。"""

import logging

import pytest

import linkforge.platforms.chaoxing.navigation as navigation_module
from linkforge.browser.exceptions import BrowserClosedError
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.models import ChaoxingModuleState, ChaoxingPageState
from linkforge.platforms.chaoxing.navigation import ChaoxingNavigationMonitor
from tests.fakes import FakeBrowser, ManualClock


def _state(chapter: str, card: int = 0) -> ChaoxingPageState:
    return ChaoxingPageState(
        content_frame_url=f"https://example.test/mooc-ans/knowledge/cards?knowledgeid={chapter}&num={card}",
        knowledge_id=chapter,
        active_tab_index=card,
        has_next_tab=True,
        modules=(ChaoxingModuleState("https://example.test/ananas/modules/video/", True, False),),
        videos=(),
    )


def _monitor(monkeypatch, states):
    pending = iter(states)

    def inspect(browser):
        value = next(pending)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(navigation_module, "inspect_chaoxing_page", inspect)
    clock = ManualClock()
    progress = []
    browser = FakeBrowser(url="https://example.test/mycourse/studentstudy?courseId=test&token=private")
    monitor = ChaoxingNavigationMonitor(
        browser,
        on_course_url_changed=progress.append,
        sleep=clock.sleep,
        monotonic=clock,
        poll_interval_seconds=0.25,
        timeout_seconds=1,
    )
    return monitor, clock, progress


def test_same_card_does_not_trigger_navigation(monkeypatch):
    monitor, clock, progress = _monitor(monkeypatch, [_state("100")])
    assert not monitor.follow_if_changed(_state("100"))
    assert clock.now == 0
    assert progress == []


@pytest.mark.parametrize("loading", [False, True])
def test_follows_latest_stable_selection_and_records_progress(monkeypatch, caplog, loading):
    states = [_state("200")]
    if loading:
        states.append(ChaoxingInspectionError("token=private"))
    states.extend([_state("300", 1), _state("300", 1)])
    monitor, _, progress = _monitor(monkeypatch, states)
    with caplog.at_level(logging.INFO):
        assert monitor.follow_if_changed(_state("100"))
    assert len(progress) == 1
    assert "chapterId=300&num=1" in progress[0]
    assert "Following the selected" in caplog.text
    assert "private" not in caplog.text


def test_returning_to_original_card_restarts_its_detection(monkeypatch):
    monitor, _, progress = _monitor(monkeypatch, [_state("200"), _state("100"), _state("100")])
    assert monitor.follow_if_changed(_state("100"))
    assert "chapterId=100" in progress[0]


def test_changing_pages_never_extend_navigation_deadline(monkeypatch):
    monitor, clock, progress = _monitor(monkeypatch, [_state(str(index)) for index in range(200, 205)])
    assert not monitor.follow_if_changed(_state("100"))
    assert clock.now == 1
    assert progress == []


def test_stop_during_confirmation_does_not_report_or_read_another_page(monkeypatch):
    monitor, clock, progress = _monitor(monkeypatch, [_state("200")])
    assert not monitor.follow_if_changed(_state("100"), should_stop=lambda: clock.now > 0)
    assert clock.now == 0.25
    assert progress == []


def test_closed_browser_during_confirmation_is_not_followed(monkeypatch):
    monitor, _, progress = _monitor(monkeypatch, [_state("200"), BrowserClosedError("private")])
    assert not monitor.follow_if_changed(_state("100"))
    assert progress == []


def test_unavailable_initial_page_does_not_imply_navigation(monkeypatch):
    monitor, _, progress = _monitor(monkeypatch, [ChaoxingInspectionError("loading")])
    assert not monitor.follow_if_changed(_state("100"))
    assert progress == []
