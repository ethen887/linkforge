"""独立作业路由、提交结果及停止边界。"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import linkforge.platforms.chaoxing.assignment_handler as assignment_module
from linkforge.browser.exceptions import BrowserClosedError
from linkforge.browser.models import BrowserJSONResponse
from linkforge.platforms.chaoxing.assignment_handler import AssignmentDetector, StandaloneAssignmentHandler
from linkforge.platforms.chaoxing.assignment_page import assignment_identity
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizCompletionError, ChaoxingQuizSubmissionError
from tests.fakes import FakeBrowser


@pytest.mark.parametrize("path", ["dowork", "prompt"])
def test_assignment_identity_keeps_route_secrets_out_of_identity(path):
    url = f"https://mooc1-api.chaoxing.com/mooc-ans/mooc2/work/{path}?courseId=1&classId=2&workId=3&enc=secret"
    identity = assignment_identity(url)
    assert identity == ("mooc1-api.chaoxing.com", "1", "2", "3")
    assert "secret" not in repr(identity)


@pytest.mark.parametrize(
    "url",
    [
        "https://chaoxing.com.evil.test/mooc-ans/mooc2/work/dowork?courseId=1&classId=2&workId=3",
        "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/dowork?courseId=1&classId=2",
        "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/dowork?courseId=1&classId=2&workId=3&workId=4",
        "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/dowork?courseId=1&classId=2&workId=3&WORKID=4",
        "https://mooc1.chaoxing.com/mycourse/studentstudy?courseId=1&classId=2&workId=3",
    ],
)
def test_unsupported_or_ambiguous_assignment_url_is_not_recognized(url):
    assert assignment_identity(url) is None


@pytest.mark.parametrize("status", [True, 1])
def test_only_positive_submission_receipt_is_completion(status):
    assert StandaloneAssignmentHandler._submission_confirmed([BrowserJSONResponse(200, {"status": status})])


@pytest.mark.parametrize("status", [False, 0, 1.0, "true", "1", None, [], {}])
def test_submission_receipt_requires_exact_success_contract(status):
    with pytest.raises(ChaoxingQuizSubmissionError):
        StandaloneAssignmentHandler._submission_confirmed([BrowserJSONResponse(200, {"status": status})])


def test_ambiguous_submission_receipts_do_not_claim_completion():
    response = BrowserJSONResponse(200, {"status": True, "secret": "private"})
    assert "private" not in repr(response)
    with pytest.raises(ChaoxingQuizCompletionError):
        StandaloneAssignmentHandler._submission_confirmed([response, response])


def test_stop_before_assignment_does_not_touch_browser_or_model():
    handler = StandaloneAssignmentHandler(FakeBrowser(), solver=None)
    handler.run_interruptibly(should_stop=lambda: True)
    assert handler.last_answers == ()


def test_response_arriving_during_window_close_is_still_verified(monkeypatch):
    browser = FakeBrowser()
    responses = []
    detector = AssignmentDetector(browser)
    handler = StandaloneAssignmentHandler(
        browser,
        solver=None,
        submitter=SimpleNamespace(submit=lambda *args, **kwargs: None),
        detector=detector,
    )
    url = "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/dowork?courseId=1&classId=2&workId=3"
    monkeypatch.setattr(handler, "_answer_all", lambda: (url, url))
    monkeypatch.setattr(handler, "_target", lambda: (url, url))
    handler._form_fields = {"courseId": "1", "classId": "2", "workRelationId": "3"}

    @contextmanager
    def capture(*args, **kwargs):
        yield responses

    def inspect(browser):
        responses.append(BrowserJSONResponse(200, {"status": True}))
        raise BrowserClosedError("local fixture closed after success")

    monkeypatch.setattr(browser, "capture_json_responses", capture)
    monkeypatch.setattr(assignment_module, "inspect_assignment_page", inspect)
    handler.run()
    assert detector.completed
