"""Behavioral specification for the production Chaoxing Quiz submitter."""

import ast
import inspect
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import linkforge.platforms.chaoxing.quiz_submitter as submitter_module
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserElementError
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizSubmissionError
from linkforge.platforms.chaoxing.quiz_dom import QUESTION_FRAME_PATH
from linkforge.platforms.chaoxing.quiz_submitter import ChaoxingQuizSubmitter
from tests.fakes import FakeBrowser, FakeDOMElement

MODULE_URL = "https://mooc1.chaoxing.com/ananas/modules/work/index.html?v=1"


class SequencedScopeBrowser(FakeBrowser):
    """Return one scripted element set for each scoped DOM inspection."""

    def __init__(self, scopes: list[tuple[BrowserElement, ...]]) -> None:
        super().__init__()
        self._scopes = iter(scopes)

    @contextmanager
    def element_scope(
        self,
        frame_url_contains: str,
        selector: str,
        *,
        ancestor_url: str,
    ) -> Iterator[tuple[BrowserElement, ...]]:
        self.action_calls.append(("element_scope", frame_url_contains, selector, ancestor_url))
        try:
            elements = next(self._scopes)
        except StopIteration as exc:
            raise AssertionError("Quiz submitter performed an unexpected extra DOM inspection.") from exc
        yield elements


def _control(
    name: str,
    events: list[str],
    *,
    element_id: str = "",
    element_type: str = "button",
    text: str = "",
    value: str = "",
    class_name: str = "",
    title: str = "",
    aria_label: str = "",
    visible: bool = True,
    enabled: bool = True,
) -> FakeDOMElement:
    return FakeDOMElement(
        name=name,
        events=events,
        inspect=lambda: {
            "tag": "button",
            "id": element_id,
            "type": element_type,
            "class": class_name,
            "text": text,
            "value": value,
            "title": title,
            "aria_label": aria_label,
            "visible": visible,
            "enabled": enabled,
        },
    )


def _submit(events: list[str], name: str = "submit") -> FakeDOMElement:
    return _control(
        name,
        events,
        element_id="submitTest",
        element_type="submit",
        text="提交",
        class_name="btn submit",
    )


def _confirm(events: list[str], name: str = "confirm") -> FakeDOMElement:
    return _control(
        name,
        events,
        element_id="submitBackOk",
        text="确定",
        class_name="btn confirm",
    )


def _next(events: list[str]) -> FakeDOMElement:
    return _control(
        "next",
        events,
        element_id="nextFocusButton",
        text="下一题",
        class_name="btn next",
    )


def _cancel(events: list[str]) -> FakeDOMElement:
    return _control(
        "cancel",
        events,
        element_id="submitBackCancel",
        text="取消",
        class_name="btn cancel",
    )


def test_submit_clicks_one_submit_target_then_one_dom_confirmation() -> None:
    events: list[str] = []
    browser = SequencedScopeBrowser(
        [
            (_next(events), _submit(events)),
            (_cancel(events), _confirm(events)),
        ]
    )

    ChaoxingQuizSubmitter().submit(browser, module_url=MODULE_URL)

    assert events == ["click:submit", "click:confirm"]
    assert browser.action_calls == [
        ("element_scope", QUESTION_FRAME_PATH, browser.action_calls[0][2], MODULE_URL),
        ("element_scope", QUESTION_FRAME_PATH, browser.action_calls[1][2], MODULE_URL),
    ]
    assert all(isinstance(call[2], str) and call[2] for call in browser.action_calls)


def test_submit_fails_closed_when_no_submit_target_exists() -> None:
    events: list[str] = []
    browser = SequencedScopeBrowser([(_next(events),)])

    with pytest.raises(ChaoxingQuizSubmissionError, match="(?i)submit"):
        ChaoxingQuizSubmitter().submit(browser, module_url=MODULE_URL)

    assert events == []


def test_submit_fails_closed_when_submit_target_is_ambiguous() -> None:
    events: list[str] = []
    browser = SequencedScopeBrowser([(_submit(events, "submit-1"), _submit(events, "submit-2"))])

    with pytest.raises(ChaoxingQuizSubmissionError, match="(?i)submit"):
        ChaoxingQuizSubmitter().submit(browser, module_url=MODULE_URL)

    assert events == []


def test_submit_fails_when_dom_confirmation_is_missing_without_resubmitting() -> None:
    events: list[str] = []
    browser = SequencedScopeBrowser([(_submit(events),), (_cancel(events),)])

    with pytest.raises(ChaoxingQuizSubmissionError, match="(?i)confirm"):
        ChaoxingQuizSubmitter().submit(browser, module_url=MODULE_URL)

    assert events == ["click:submit"]
    assert events.count("click:submit") == 1


def test_submit_click_failure_is_not_retried() -> None:
    events: list[str] = []
    submit = _submit(events)
    submit.click_error = BrowserElementError("submission result is unknown")
    browser = SequencedScopeBrowser([(submit,)])

    with pytest.raises(ChaoxingQuizSubmissionError, match="(?i)submit"):
        ChaoxingQuizSubmitter().submit(browser, module_url=MODULE_URL)

    assert events == ["click:submit"]
    assert events.count("click:submit") == 1


def test_submit_fails_when_dom_confirmation_is_ambiguous_without_clicking_confirmation() -> None:
    events: list[str] = []
    browser = SequencedScopeBrowser(
        [
            (_submit(events),),
            (_confirm(events, "confirm-1"), _confirm(events, "confirm-2")),
        ]
    )

    with pytest.raises(ChaoxingQuizSubmissionError, match="(?i)confirm"):
        ChaoxingQuizSubmitter().submit(browser, module_url=MODULE_URL)

    assert events == ["click:submit"]
    assert events.count("click:submit") == 1


def test_submitter_uses_browser_abstractions_without_smoke_or_playwright_dependencies() -> None:
    syntax_tree = ast.parse(inspect.getsource(submitter_module))
    imported_modules = {
        node.module
        for node in ast.walk(syntax_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name for node in ast.walk(syntax_tree) if isinstance(node, ast.Import) for alias in node.names
    )

    assert not any(
        module == "playwright" or module.startswith("playwright.") for module in imported_modules
    )
    assert not any(module.endswith("smoke_quiz") for module in imported_modules)
