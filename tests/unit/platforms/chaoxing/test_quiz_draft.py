"""Draft saves are optional, unambiguous, interruptible ordinary UI clicks."""

import pytest

from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizStateError
from linkforge.platforms.chaoxing.quiz_draft import click_draft_save
from tests.fakes import FakeDOMElement


def control(*, visible=True, enabled=True, draft=True, events=None):
    return FakeDOMElement(
        inspect=lambda: dict(draft=draft, visible=visible, enabled=enabled),
        name="draft",
        events=events,
    )


@pytest.mark.parametrize("mode", ["missing", "hidden", "disabled", "ambiguous", "submit"])
def test_unavailable_draft_button_never_clicks_anything(mode):
    events = []
    elements = {
        "missing": (),
        "hidden": (control(visible=False, events=events),),
        "disabled": (control(enabled=False, events=events),),
        "ambiguous": (control(events=events), control(events=events)),
        "submit": (control(draft=False, events=events),),
    }[mode]
    assert not click_draft_save(elements, check_stop=lambda: None)
    assert events == []


def test_visible_duplicate_is_ignored_when_it_is_hidden():
    events = []
    assert click_draft_save(
        (control(events=events), control(visible=False, events=events)), check_stop=lambda: None
    )
    assert events == ["click:draft"]


def test_stop_before_draft_click_is_observed():
    events = []

    def stop():
        raise InterruptedError

    with pytest.raises(InterruptedError):
        click_draft_save((control(events=events),), check_stop=stop)
    assert events == []


def test_draft_click_failure_is_not_a_retryable_browser_error():
    button = control()
    button.click_error = BrowserError("PRIVATE-URL-OR-RESPONSE")
    with pytest.raises(ChaoxingQuizStateError, match="保存结果未确认") as caught:
        click_draft_save((button,), check_stop=lambda: None)
    assert "PRIVATE" not in str(caught.value)
