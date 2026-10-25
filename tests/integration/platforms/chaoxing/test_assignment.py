"""独立作业的主页面 DOM、正常 UI 提交及被动响应确认；全部请求在本地拦截。"""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from linkforge.application.task_runner import TaskReviewRequiredError, TaskType
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


@pytest.mark.parametrize("question_count", ["2", "encoded-question-count"])
def test_direct_assignment_startup_answers_all_objective_questions_and_only_saves(question_count):
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        body = _with_draft_button().replace(
            'name="totalQuestionNum" value="2"', f'name="totalQuestionNum" value="{question_count}"'
        )
        requests = _open(browser, body=body)
        assert ChaoxingStartupWait(page_timeout_seconds=1).wait(
            browser=browser, course_url=URL, should_stop=lambda: False
        )
        llm = StubLLM()
        runtime = ChaoxingPlatformRuntime(quiz_submitter=SimpleNamespace(submit=lambda *_args: None))
        runner = runtime.build_runner(browser=browser, llm=llm, model="test-model")
        with pytest.raises(TaskReviewRequiredError) as caught:
            runner.run()
        assert caught.value.saved
        assert llm.calls == 2
        assert len(requests) == 3
        assert all(request["pyFlag"] == ["1"] for request in requests)
        assert requests[-1]["answer1"] == ["B"]
        assert requests[-1]["answer2"] == ["false"]
        assert not browser._require_page().locator("#workpop").is_visible()
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


def _with_draft_button(*, label="暂时保存", after_save="", multiple=False):
    body = _html().replace('<a onclick="window.saved=true">Save</a>', f'<a id="draft-save">{label}</a>')
    body = body.replace(
        "window.saved = false;",
        """
        window.saved = false;
        document.getElementById('draft-save').onclick = async () => {
          const form = document.getElementById('submitForm');
          await fetch(form.action, {method:'POST', body:new URLSearchParams(new FormData(form))});
          window.saved = true;
          AFTER_SAVE
        };
        """.replace("AFTER_SAVE", after_save),
    )
    if multiple:
        start = body.index('<div class="questionLi" id="question1">')
        end = body.index('<div class="questionLi" id="question2">')
        body = (
            body[:start]
            + body[start:end]
            .replace("单选题", "多选题")
            .replace('role="radio"', 'role="checkbox"')
            .replace('class="num_option"', 'class="num_option_dx"')
            + body[end:]
        )
        body = body.replace(
            "question.querySelectorAll('[role=radio]')",
            "question.querySelectorAll('[role=radio],[role=checkbox]')",
        )
        body = body.replace(
            "option.onclick = () => {",
            """option.onclick = () => {
              if (option.getAttribute('role') === 'checkbox') {
                const marker = option.querySelector('.num_option_dx');
                marker.classList.toggle('check_answer_dx');
                option.setAttribute('aria-checked', String(marker.classList.contains('check_answer_dx')));
                question.querySelector('input').value = [...question.querySelectorAll('.check_answer_dx')]
                    .map(item => item.getAttribute('data')).join('');
                return;
              }
            """,
        )
    return body


@pytest.mark.parametrize("label", ["暂时保存", "Save", "保存答案"])
def test_each_answer_is_saved_as_draft_before_next_model_call(label):
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=_with_draft_button(label=label))

        def check_previous_save():
            if llm.calls == 2:
                assert len(requests) == 1
                assert requests[0]["answer1"] == ["B"]
                assert requests[0]["answer2"] == [""]

        llm = StubLLM(on_call=check_previous_save)
        handler, detector = _handler(browser, llm)
        handler.answer_all()
        browser._require_page().wait_for_function("window.saved")
        assert llm.calls == 2
        assert len(requests) == 2
        assert all(fields["pyFlag"] == ["1"] for fields in requests)
        assert requests[-1]["answer2"] == ["false"]
        assert not detector.completed
        assert not browser._require_page().locator("#workpop").is_visible()


def test_each_multiselect_click_is_saved_and_model_is_not_called_again():
    class MultipleLLM(StubLLM):
        def call_model(self, model, messages, tools):
            self.calls += 1
            return LLMResponse(
                json.dumps(
                    {
                        "question_type": "MULTIPLE_CHOICE" if self.calls == 1 else "TRUE_FALSE",
                        "choices": ["A", "B"] if self.calls == 1 else ["B"],
                    }
                )
            )

    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=_with_draft_button(multiple=True))
        llm = MultipleLLM()
        handler, detector = _handler(browser, llm)
        handler.answer_all()
        assert llm.calls == 2
        assert len(requests) == 3
        assert [fields["answer1"] for fields in requests] == [["A"], ["AB"], ["AB"]]
        assert all(fields["pyFlag"] == ["1"] for fields in requests)
        assert not detector.completed


def test_question_replaced_after_draft_save_is_reacquired_without_repeating_model():
    after_save = (
        "document.getElementById('question1').replaceWith("
        "document.getElementById('question1').cloneNode(true));"
    )
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=_with_draft_button(after_save=after_save))
        llm = StubLLM()
        handler, _ = _handler(browser, llm)
        handler.answer_all()
        assert len(requests) == 2
        assert llm.calls == 2
        assert requests[-1]["answer1"] == ["B"]


def test_selection_lost_after_draft_save_stops_without_solving_next_question():
    after_save = """
      const question = document.getElementById('question1');
      question.querySelectorAll('[role=radio]').forEach(option => {
        option.setAttribute('aria-checked', 'false');
        option.querySelector('.num_option').classList.remove('check_answer');
      });
      question.querySelector('input').value = '';
    """
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=_with_draft_button(after_save=after_save))
        llm = StubLLM()
        handler, detector = _handler(browser, llm)
        with pytest.raises(ChaoxingQuizStateError, match="暂存后"):
            handler.answer_all()
        assert llm.calls == 1
        assert len(requests) == 1
        assert not detector.completed


def test_rejected_draft_response_stops_without_retry_or_next_model_request():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        _open(browser, body=_with_draft_button())
        saves = []

        def reject_save(route):
            saves.append(route.request.post_data)
            route.fulfill(json={"status": False, "msg": "PRIVATE-REJECTION"})

        browser._require_page().route("**/mooc-ans/work/addStudentWorkNewWeb", reject_save)
        llm = StubLLM()
        handler, detector = _handler(browser, llm)
        with pytest.raises(ChaoxingQuizStateError, match="暂存响应") as caught:
            handler.answer_all()
        assert llm.calls == 1
        assert len(saves) == 1
        assert "PRIVATE" not in str(caught.value)
        assert not detector.completed


def test_resume_with_new_handler_after_reload_skips_answer_saved_by_previous_run():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=_with_draft_button())
        first_llm = StubLLM()
        first_handler, _ = _handler(browser, first_llm)
        first_handler.run_interruptibly(should_stop=lambda: len(requests) >= 1)
        assert first_llm.calls == 1
        assert len(requests) == 1
        assert requests[0]["answer1"] == ["B"]
        assert requests[0]["answer2"] == [""]

        # 模拟服务器将暂存答案带回新文档；重建处理器，不能依赖上次运行的内存。
        body = (
            _with_draft_button()
            .replace('id="answer1" name="answer1" value=""', 'id="answer1" name="answer1" value="B"')
            .replace(
                '<span class="num_option" data="B">B</span>',
                '<span class="num_option check_answer" data="B">B</span>',
                1,
            )
        )
        resumed_requests = _open(browser, body=body)

        class RemainingQuestionLLM(StubLLM):
            def call_model(self, model, messages, tools):
                self.calls += 1
                return LLMResponse('{"question_type":"TRUE_FALSE","choices":["B"]}')

        resumed_llm = RemainingQuestionLLM()
        resumed_handler, detector = _handler(browser, resumed_llm)
        resumed_handler.answer_all()
        assert resumed_llm.calls == 1
        assert len(resumed_requests) == 1
        assert resumed_requests[0]["answer1"] == ["B"]
        assert resumed_requests[0]["answer2"] == ["false"]
        assert not detector.completed


def test_all_existing_answers_need_no_model_requests_and_still_require_real_submission():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        body = (
            _html()
            .replace('id="answer1" name="answer1" value=""', 'id="answer1" name="answer1" value="B"')
            .replace('id="answer2" name="answer2" value=""', 'id="answer2" name="answer2" value="false"')
            .replace(
                '<span class="num_option" data="B">B</span>',
                '<span class="num_option check_answer" data="B">B</span>',
            )
            .replace(
                '<span class="num_option" data="false">B</span>',
                '<span class="num_option check_answer" data="false">B</span>',
            )
        )
        requests = _open(browser, body=body)
        llm = StubLLM()
        handler, detector = _handler(browser, llm)
        handler.answer_all()
        assert llm.calls == 0
        assert requests == []
        assert not detector.completed
        handler.run()
        assert llm.calls == 0
        assert len(requests) == 1
        assert requests[0]["pyFlag"] == [""]
        assert detector.completed


@pytest.mark.parametrize(
    "button",
    [
        "",
        '<a style="display:none">暂时保存</a>',
        "<button disabled>暂时保存</button>",
        "<a>暂时保存</a><a>暂时保存</a>",
        '<a aria-label="提交作业">暂时保存</a>',
    ],
)
def test_optional_or_ambiguous_save_controls_never_click_submit(button):
    body = _html().replace('<a onclick="window.saved=true">Save</a>', button)
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        requests = _open(browser, body=body)
        llm = StubLLM()
        handler, detector = _handler(browser, llm)
        handler.answer_all()
        assert llm.calls == 2
        assert requests == []
        assert not detector.completed
        assert not browser._require_page().locator("#workpop").is_visible()


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
