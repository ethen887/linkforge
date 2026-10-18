"""独立作业的主页面 DOM、正常 UI 提交及被动响应确认；全部请求在本地拦截。"""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from linkforge.application.task_runner import TaskType
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.llm.base import LLM, LLMResponse
from linkforge.platforms.chaoxing.assignment_handler import (
    AssignmentDetector,
    AssignmentSubmitter,
    StandaloneAssignmentHandler,
)
from linkforge.platforms.chaoxing.assignment_page import (
    ASSIGNMENT_STATE_SCRIPT,
    ASSIGNMENT_SUBMIT_PATH,
    inspect_assignment_page,
)
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingQuizCompletionError,
    ChaoxingQuizStateError,
    ChaoxingQuizSubmissionError,
)
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizHandlerConfig
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver
from linkforge.platforms.chaoxing.runtime import ChaoxingPlatformRuntime
from linkforge.platforms.chaoxing.startup import ChaoxingStartupWait

URL = "https://mooc1-api.chaoxing.com/mooc-ans/mooc2/work/dowork?courseId=1&classId=2&workId=3"


def _html(mode="receipt") -> str:
    return """
    <style>.questionLi {padding:16px;width:600px} [role=radio] {padding:8px}</style>
    <a onclick="window.saved=true">Save</a>
    <a class="completeBtn">Submit</a>
    <form id="submitForm" method="post" action="/mooc-ans/work/addStudentWorkNewWeb">
      <input type="hidden" name="courseId" value="1">
      <input type="hidden" name="classId" value="2">
      <input type="hidden" name="workRelationId" value="3">
      <input type="hidden" id="pyFlag" name="pyFlag" value="1">
      <input type="hidden" name="totalQuestionNum" value="2">
      <div class="questionLi" id="question1">
        <h3 class="mark_name">1. (单选题) 选择 B</h3>
        <input type="hidden" id="answer1" name="answer1" value="">
        <div role="radio"><span class="num_option" data="A">A</span>甲</div>
        <div role="radio"><span class="num_option" data="B">B</span>乙</div>
      </div>
      <div class="questionLi" id="question2">
        <h3 class="mark_name">2. (判断题) 选择 B</h3>
        <input type="hidden" id="answer2" name="answer2" value="">
        <div role="radio"><span class="num_option" data="true">A</span>正确</div>
        <div role="radio"><span class="num_option" data="false">B</span>错误</div>
      </div>
    </form>
    <div id="workpop" style="display:none">
      <p id="popcontent">Submit?</p><a id="popok">Submit</a><a id="popno">Cancel</a>
    </div>
    <script>
      window.saved = false;
      document.querySelector('.completeBtn').onclick = () => {
        const form = document.getElementById('submitForm');
        if ('MODE' === 'autosave') {
          fetch(form.action, {method:'POST', body:new URLSearchParams(new FormData(form))});
        }
        document.getElementById('pyFlag').value = '';
        document.getElementById('workpop').style.display = 'block';
      };
      for (const question of document.querySelectorAll('.questionLi')) {
        for (const option of question.querySelectorAll('[role=radio]')) {
          option.onclick = () => {
            for (const other of question.querySelectorAll('[role=radio]')) {
              other.querySelector('.num_option').classList.remove('check_answer');
              other.setAttribute('aria-checked', 'false');
            }
            option.querySelector('.num_option').classList.add('check_answer');
            option.setAttribute('aria-checked', 'true');
            question.querySelector('input').value = option.querySelector('.num_option')
                .getAttribute('data');
          };
        }
      }
      document.getElementById('popok').onclick = async () => {
        if ('MODE' === 'close_without_receipt') {window.close(); return;}
        const form = document.getElementById('submitForm');
        await fetch(form.action, {method:'POST', body:new URLSearchParams(new FormData(form))});
        if ('MODE' === 'close') window.close();
      };
    </script>
    """.replace("MODE", mode)


class StubLLM(LLM):
    def __init__(self, on_call=lambda: None) -> None:
        self.calls = 0
        self.on_call = on_call

    def call_model(self, model, messages, tools):
        assert messages[-1].images[0].data.startswith(b"\x89PNG")
        self.calls += 1
        self.on_call()
        kind = "SINGLE_CHOICE" if self.calls == 1 else "TRUE_FALSE"
        return LLMResponse(json.dumps({"question_type": kind, "choices": ["B"]}))


def _open(browser, *, mode="receipt", response=True, body=None):
    requests = []

    def route(request):
        path = urlsplit(request.request.url).path
        if path == ASSIGNMENT_SUBMIT_PATH:
            fields = parse_qs(request.request.post_data or "", keep_blank_values=True)
            requests.append(fields)
            status = True if fields.get("pyFlag") == ["1"] else response
            request.fulfill(json={"status": status, "msg": "PRIVATE-RESPONSE"})
        elif path == "/mooc-ans/mooc2/work/dowork":
            request.fulfill(
                content_type="text/html; charset=utf-8", body=_html(mode) if body is None else body
            )
        else:
            request.abort()

    browser._require_page().route("**/*", route)
    browser.open(URL)
    return requests


@pytest.mark.parametrize("mode", ["receipt", "close"])
@pytest.mark.parametrize("question_count", ["2", "encoded-question-count"])
def test_direct_assignment_startup_answer_submit_and_complete_once(mode, question_count):
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        body = _html(mode).replace(
            'name="totalQuestionNum" value="2"', f'name="totalQuestionNum" value="{question_count}"'
        )
        requests = _open(browser, mode=mode, body=body)
        assert ChaoxingStartupWait(page_timeout_seconds=1).wait(
            browser=browser, course_url=URL, should_stop=lambda: False
        )
        llm = StubLLM()
        runtime = ChaoxingPlatformRuntime(quiz_submitter=SimpleNamespace(submit=lambda *_args: None))
        runner = runtime.build_runner(browser=browser, llm=llm, model="test-model")
        runner.run()
        assert llm.calls == 2
        assert len(requests) == 1
        assert requests[0]["answer1"] == ["B"]
        assert requests[0]["answer2"] == ["false"]
        assert runner.issues == []


def _handler(browser, llm):
    detector = AssignmentDetector(browser)
    handler = StandaloneAssignmentHandler(
        browser,
        solver=LLMQuizSolver(llm=llm, model="test-model"),
        submitter=AssignmentSubmitter(),
        detector=detector,
        config=ChaoxingQuizHandlerConfig(readiness_timeout_seconds=1, completion_timeout_seconds=0.3),
    )
    return handler, detector


@pytest.mark.parametrize("response", [False, 0, "true", None])
def test_rejected_or_malformed_result_is_not_retried_or_marked_complete(response, caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, response=response)
        handler, detector = _handler(browser, StubLLM())
        with pytest.raises(ChaoxingQuizSubmissionError):
            handler.run()
        assert len(requests) == 1
        assert not detector.completed
        assert "PRIVATE-RESPONSE" not in caplog.text


def test_stop_after_model_response_prevents_option_click_and_submit():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser)
        llm = StubLLM()
        handler, detector = _handler(browser, llm)
        handler.run_interruptibly(should_stop=lambda: llm.calls > 0)
        assert llm.calls == 1
        assert requests == []
        assert not detector.completed
        assert browser._require_page().locator(".check_answer").count() == 0


def test_assignment_changed_during_model_call_is_not_answered_or_submitted():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser)
        llm = StubLLM(on_call=lambda: browser.open(URL.replace("workId=3", "workId=4")))
        handler, detector = _handler(browser, llm)
        with pytest.raises(ChaoxingQuizStateError, match="changed"):
            handler.run()
        assert requests == []
        assert not detector.completed


def test_window_close_without_success_is_not_completion():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, mode="close_without_receipt")
        handler, detector = _handler(browser, StubLLM())
        with pytest.raises((ChaoxingQuizCompletionError, ChaoxingQuizSubmissionError)):
            handler.run()
        assert requests == []
        assert not detector.completed


def test_unloaded_or_partial_assignment_is_not_ready():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        _open(browser, body=_html().replace('value="2"', 'value="3"'))
        assert not inspect_assignment_page(browser).ready
        assert AssignmentDetector(browser).detect() is TaskType.UNKNOWN


def test_already_submitted_result_is_not_answered_again():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        browser._require_page().route(
            "**/*",
            lambda route: route.fulfill(content_type="text/html; charset=utf-8", body="<p>提交成功</p>"),
        )
        result_url = URL.replace("/dowork?", "/prompt?")
        browser.open(result_url)
        assert ChaoxingStartupWait(page_timeout_seconds=1).wait(
            browser=browser, course_url=result_url, should_stop=lambda: False
        )
        detector = AssignmentDetector(browser)
        assert detector.detect() is TaskType.COMPLETE


def test_identical_page_on_untrusted_host_is_not_an_assignment():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        browser._require_page().route(
            "**/*", lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=_html())
        )
        browser.open(URL.replace("mooc1-api.chaoxing.com", "chaoxing.com.evil.test"))
        assert browser.evaluate_in_frames(ASSIGNMENT_STATE_SCRIPT) == ({"assignment_page": False},)


def test_successful_save_does_not_mask_rejected_submission():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, mode="autosave", response=False)
        handler, detector = _handler(browser, StubLLM())
        with pytest.raises(ChaoxingQuizSubmissionError):
            handler.run()
        assert len(requests) == 2
        assert not detector.completed


def test_negative_result_text_is_not_a_success_marker():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        browser._require_page().route(
            "**/*",
            lambda route: route.fulfill(
                content_type="text/html; charset=utf-8", body="<p>未提交成功，请重试</p>"
            ),
        )
        browser.open(URL.replace("/dowork?", "/prompt?"))
        assert not inspect_assignment_page(browser).submitted


def test_stop_after_submit_dialog_prevents_final_confirmation():
    stopped = False

    class StopAfterDialog(AssignmentSubmitter):
        def _click_unique_submit(self, browser, *, module_url):
            nonlocal stopped
            super()._click_unique_submit(browser, module_url=module_url)
            stopped = True

    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser)
        handler, detector = _handler(browser, StubLLM())
        handler._submitter = StopAfterDialog()
        handler.run_interruptibly(should_stop=lambda: stopped)
        assert stopped
        assert requests == []
        assert not detector.completed


def test_unsupported_question_blocks_all_model_calls_and_submission():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=_html().replace('role="radio"', 'class="unsupported-control"'))
        llm = StubLLM()
        handler, detector = _handler(browser, llm)
        with pytest.raises(ChaoxingQuizStateError):
            handler.run()
        assert llm.calls == 0
        assert requests == []
        assert not detector.completed
