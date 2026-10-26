"""本地 UEditor/TEX 替身验证输入、异步公式图片、暂存及人工检查边界。"""

import json

import pytest

from linkforge.application.task_runner import TaskReviewRequiredError
from linkforge.browser.exceptions import BrowserElementError
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.browser.playwright_element import _Element
from linkforge.llm.base import LLM, LLMResponse
from linkforge.platforms.chaoxing.assignment_handler import AssignmentDetector, AssignmentSubmitter
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizHandlerConfig
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver
from linkforge.platforms.chaoxing.written_answer import LLMWrittenSolver
from linkforge.platforms.chaoxing.written_assignment import DraftingAssignmentHandler
from linkforge.platforms.chaoxing.written_review import LLMWrittenReviewer
from tests.integration.platforms.chaoxing.test_assignment import _html, _open

PNG = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
    "QVR42mP8/x8AAwMCAO+jM1sAAAAASUVORK5CYII="
)


def _body():
    base = _html()
    start = base.index('<div class="questionLi" id="question1">')
    end = base.index('<div class="questionLi" id="question2">')
    base = (
        base[:start]
        + """
    <div class="questionLi" id="question1">
      <h3 class="mark_name">1. (简答题) 本地测试：计算积分并写出单位</h3>
      <iframe id="ueditor_1" srcdoc="<body contenteditable='true'><p><br></p></body>"></iframe>
      <textarea id="answer1" name="answer1" style="display:none"></textarea>
      <button type="button" title="TEX" onclick="openTex('ueditor_1')">TEX</button>
    </div>
    """
        + base[end:]
    )
    base = base.replace('<a onclick="window.saved=true">Save</a>', '<a id="saveDraft">Save</a>')
    return (
        base
        + """
    <style>iframe {height:140px;width:500px} #texDialog {height:300px}</style>
    <script>
      window.openTex = editorId => {
        window.activeEditorId = editorId;
        const frame = document.createElement('iframe'); frame.id='texDialog';
        frame.src='/ananas/common-modules/latex/html/mooc1-index.html';
        document.body.append(frame);
      };
      document.querySelector('#saveDraft').onclick = async () => {
        for (const question of document.querySelectorAll('.questionLi')) {
          const editor = question.querySelector('iframe[id^=ueditor_]');
          if (editor) question.querySelector('textarea').value = editor.contentDocument.body.innerHTML;
        }
        const form = document.querySelector('#submitForm');
        document.querySelector('#pyFlag').value='1';
        await fetch(form.action, {method:'POST',body:new URLSearchParams(new FormData(form))});
        if (window.afterSave) window.afterSave();
      };
    </script>
    """
    )


def _tex():
    return """
    <textarea id="txta_input"></textarea><div id="wrap_output"></div>
    <span class="confirmBtn">Confirm</span>
    <script>
      document.querySelector('textarea').oninput = () => {
        document.querySelector('#wrap_output').innerHTML = document.querySelector('textarea').value
          ? '<svg><path d="M0 0L1 1"/></svg>' : '';
      };
      document.querySelector('.confirmBtn').onclick = () => {
        const latex = document.querySelector('textarea').value;
        setTimeout(() => {
          const body = parent.document.getElementById(parent.activeEditorId).contentDocument.body;
          const image = body.ownerDocument.createElement('img');
          image.className='ans-latex-moudle';image.setAttribute('data',escape(JSON.stringify(latex)));
          image.src='PNG';body.append(image);
        }, 30);
        frameElement.style.display='none';
      };
    </script>
    """.replace("PNG", PNG)


class DraftModel(LLM):
    def __init__(
        self, callback=lambda: None, *, rewrite=False, formula_first=False, formula=r"\frac{x^2}{2}"
    ):
        self.calls = []
        self.review_calls = []
        self.audit_calls = []
        self.rewrite = rewrite
        self.formula_first = formula_first
        self.formula = formula
        self.callback = callback

    def call_model(self, model, messages, tools):
        assert messages[-1].images[0].data.startswith(b"\x89PNG")
        if messages[-1].content.startswith('{"audit_answer":'):
            self.audit_calls.append(json.loads(messages[-1].content))
            return LLMResponse('{"passed":true,"issues":[]}')
        if messages[-1].content.startswith('{"existing_answer":'):
            self.review_calls.append(json.loads(messages[-1].content))
            self.callback()
            return LLMResponse(json.dumps({"rewrite": self.rewrite}))
        self.calls.append(messages[-1].content)
        self.callback()
        if messages[-1].content == "请按正式考试答卷格式完成这道题的所有小问。":
            blocks = [
                {"kind": "text", "content": "第一步 <script>只是文字</script>"},
                {"kind": "latex", "content": self.formula},
                {"kind": "text", "content": "最终结果：0.5 m。"},
            ]
            if self.formula_first:
                blocks[0], blocks[1] = blocks[1], blocks[0]
            return LLMResponse(json.dumps({"blocks": blocks}))
        return LLMResponse('{"question_type":"TRUE_FALSE","choices":["B"]}')


def _handler(browser, model):
    handler = DraftingAssignmentHandler(
        browser,
        solver=LLMQuizSolver(llm=model, model="test"),
        submitter=AssignmentSubmitter(),
        detector=AssignmentDetector(browser),
        config=ChaoxingQuizHandlerConfig(
            readiness_timeout_seconds=1,
            completion_timeout_seconds=0.3,
            formula_preview_timeout_seconds=1,
            formula_insert_timeout_seconds=1,
        ),
    )
    handler.written_solver = LLMWrittenSolver(llm=model, model="test")
    handler.written_reviewer = LLMWrittenReviewer(llm=model, model="test")
    return handler


def _setup(browser, body=None):
    requests = _open(browser, body=_body() if body is None else body)
    browser._require_page().route(
        "**/ananas/common-modules/latex/html/*",
        lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=_tex()),
    )
    browser._require_page().frame_locator("#ueditor_1").locator("body[contenteditable=true]").wait_for()
    return requests


def test_mixed_assignment_writes_formula_saves_preserves_on_restart_and_never_submits():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        model = DraftModel()
        handler = _handler(browser, model)
        with pytest.raises(TaskReviewRequiredError):
            handler.run()
        assert len(model.calls) == 2
        assert len(requests) == 3
        assert all(request["pyFlag"] == ["1"] for request in requests)
        assert "ans-latex-moudle" in requests[-1]["answer1"][0]
        assert "最终结果" in requests[-1]["answer1"][0]
        assert requests[-1]["answer2"] == ["false"]
        page = browser._require_page()
        assert page.frame_locator("#ueditor_1").locator("script").count() == 0
        assert not handler._detector.completed
        second_model = DraftModel()
        with pytest.raises(TaskReviewRequiredError):
            _handler(browser, second_model).run()
        assert second_model.calls == []
        assert len(second_model.review_calls) == 1
        assert len(requests) == 5


def test_format_repair_happens_before_page_input_and_then_continues_all_questions():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        body = browser._require_page().frame_locator("#ueditor_1").locator("body")

        class Model(DraftModel):
            repaired = False

            def call_model(self, model, messages, tools):
                if not messages[-1].images:
                    assert not body.inner_text().strip()
                    assert not requests
                    self.repaired = True
                    return LLMResponse('{"blocks":[{"kind":"text","content":"完整答卷结果为 2 m。"}]}')
                result = super().call_model(model, messages, tools)
                if "所有小问" in messages[-1].content:
                    return LLMResponse("```json\n" + result.content + "\n```")
                return result

        model = Model()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert model.repaired
        assert len(model.calls) == 2
        assert "完整答卷结果" in requests[-1]["answer1"][0]
        assert requests[-1]["answer2"] == ["false"]
        assert all(request["pyFlag"] == ["1"] for request in requests)


@pytest.mark.parametrize("mode", ["inline_source", "repair_with_delimiters", "repair_with_fence"])
def test_local_math_conversion_prevents_repeated_format_failures_and_reaches_audit(mode):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)

        class Model(DraftModel):
            repairs = 0

            def call_model(self, model, messages, tools):
                if not messages[-1].images:
                    self.repairs += 1
                    assert mode.startswith("repair_with_") and self.repairs == 1
                    return LLMResponse(
                        json.dumps(
                            {
                                "blocks": [
                                    {"kind": "text", "content": "解：由"},
                                    {
                                        "kind": "latex",
                                        "content": "```latex\nx=2\n```"
                                        if mode == "repair_with_fence"
                                        else "$$x=2$$",
                                    },
                                    {"kind": "text", "content": "得，故"},
                                    {"kind": "latex", "content": r"\[y=\frac{x}{2}=1\]"},
                                ]
                            }
                        )
                    )
                result = super().call_model(model, messages, tools)
                if "所有小问" in messages[-1].content:
                    if mode.startswith("repair_with_"):
                        return LLMResponse('{"wrong_schema":true}')
                    return LLMResponse(
                        json.dumps(
                            {
                                "blocks": [
                                    {
                                        "kind": "text",
                                        "content": r"解：由 $x=2$ 得，故 $$y=\frac{x}{2}=1$$。",
                                    }
                                ]
                            }
                        )
                    )
                return result

        model = Model()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert model.repairs == (1 if mode.startswith("repair_with_") else 0)
        assert len(model.audit_calls) == 1
        data = model.audit_calls[0]["audit_answer"]
        assert data["formulas"] == ["x=2", r"y=\frac{x}{2}=1"]
        assert "$" not in data["text"] and "\\frac" not in data["text"]
        assert len(requests) == 3
        assert all(r["pyFlag"] == ["1"] for r in requests)


def test_pause_logs_fixed_specific_reason_instead_of_only_exception_type(caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        _setup(browser, _body().replace('title="TEX"', 'title="Other"'))
        with caplog.at_level("WARNING"), pytest.raises(TaskReviewRequiredError):
            _handler(browser, DraftModel()).run()
        assert "作业草稿暂停原因：未找到唯一的 TEX 公式按钮" in caplog.text


def test_tex_receives_single_backslashes_and_toolbar_changes_do_not_change_question():
    body = (
        _body()
        .replace(
            '<iframe id="ueditor_1"',
            '<div class="edui-editor"><span id="fontLabel">字体 字号</span><iframe id="ueditor_1"',
        )
        .replace("TEX</button>", "TEX</button></div>")
    )
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser, body)
        page = browser._require_page()
        canonical = r"\lambda=632.8\,\text{nm}=632.8\times10^{-9}\,\text{m}"
        model = DraftModel(
            lambda: page.evaluate("() => document.querySelector('#fontLabel').textContent='arial 16px'"),
            formula=canonical.replace("\\", "\\\\"),
        )
        # 正常保存可以改变百分号编码的大小写，但公式语义应保持相同。
        page.evaluate("""() => {window.afterSave=()=>{
            const field=document.querySelector('#answer1');
            field.value=field.value.replace(/%5C/g,'%5c');
        }}""")
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert len(model.calls) == 2
        formula = (
            page.frame_locator("#ueditor_1")
            .locator("img")
            .evaluate("i => JSON.parse(unescape(i.getAttribute('data')))")
        )
        assert formula == canonical
        assert requests[-1]["answer2"] == ["false"]


def test_tex_input_changed_by_component_is_never_confirmed():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        tex = _tex().replace(
            "document.querySelector('textarea').oninput = () => {",
            "document.querySelector('textarea').oninput = () => {"
            "document.querySelector('textarea').value=document.querySelector('textarea').value.replaceAll('\\\\','');",
        )
        browser._require_page().route(
            "**/latex/html/*", lambda route: route.fulfill(content_type="text/html", body=tex)
        )
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, DraftModel()).run()
        assert not caught.value.saved
        assert not requests
        assert browser._require_page().frame_locator("#ueditor_1").locator("img").count() == 0


def test_existing_raw_source_is_recorded_rewritten_and_visually_reaudited(caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.frame_locator("#ueditor_1").locator("body").fill(r"解：由 $x=\frac{1}{2}$ 得。")
        model = DraftModel()
        handler = _handler(browser, model)
        with caplog.at_level("INFO"), pytest.raises(TaskReviewRequiredError) as caught:
            handler.run()
        assert caught.value.saved
        assert len(model.audit_calls) == 2
        assert len(model.calls) == 2  # 原答案先保留；审核后只重做这道大题，客观题不重复做。
        assert handler.audit_history[0].issues[0].code == "raw_latex"
        assert handler.audit_history[-1].issues == ()
        assert "$" not in page.frame_locator("#ueditor_1").locator("body").inner_text()
        assert "最终结果" in requests[-1]["answer1"][0]
        assert requests[-1]["answer2"] == ["false"]
        assert all(r["pyFlag"] == ["1"] for r in requests)
        assert "第 1 轮审核问题" in caplog.text
        assert "第 2 轮作答审核通过" in caplog.text


@pytest.mark.parametrize("always_fail", [False, True])
def test_audit_feedback_drives_rework_and_never_loops_forever(always_fail, caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)

        class Model(DraftModel):
            audits = 0
            feedback = []

            def call_model(self, model, messages, tools):
                if messages[-1].content.startswith('{"audit_answer":'):
                    self.audits += 1
                    assert len(messages[-1].images) >= 2
                    if self.audits == 1 or always_fail:
                        return LLMResponse(
                            json.dumps(
                                {
                                    "passed": False,
                                    "issues": [
                                        {
                                            "code": "exam_style",
                                            "detail": "PRIVATE-FEEDBACK 请使用正式答卷语句并给出结论。",
                                        }
                                    ],
                                }
                            )
                        )
                    return LLMResponse('{"passed":true,"issues":[]}')
                if "所有小问" in messages[-1].content:
                    data = json.loads(messages[-2].content)
                    if data["review_issues"]:
                        self.feedback.append(data["review_issues"])
                        assert "PRIVATE-FEEDBACK" in data["review_issues"][0]
                        assert "本地测试" in data["question_text"]
                return super().call_model(model, messages, tools)

        model = Model()
        handler = _handler(browser, model)
        with caplog.at_level("INFO"), pytest.raises(TaskReviewRequiredError) as caught:
            handler.run()
        assert caught.value.saved is not always_fail
        assert model.audits == (3 if always_fail else 2)
        assert len(model.feedback) == (2 if always_fail else 1)
        assert len(model.calls) == (4 if always_fail else 3)
        assert "PRIVATE-FEEDBACK" not in caplog.text
        assert all(r["pyFlag"] == ["1"] for r in requests)


@pytest.mark.parametrize("mode", ["invalid", "edit", "stop"])
def test_failed_audit_or_user_interruption_does_not_start_rework(mode):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        stopped = []

        class Model(DraftModel):
            def call_model(self, model, messages, tools):
                if messages[-1].content.startswith('{"audit_answer":'):
                    if mode == "invalid":
                        return LLMResponse('{"passed":"yes","issues":[]}')
                    if mode == "edit":
                        page.frame_locator("#ueditor_1").locator("body").fill("用户新内容")
                    if mode == "stop":
                        stopped.append(True)
                    return LLMResponse(
                        '{"passed":false,"issues":[{"code":"rendering","detail":"修复公式"}]}'
                    )
                return super().call_model(model, messages, tools)

        model = Model()
        handler = _handler(browser, model)
        if mode == "stop":
            handler.run_interruptibly(should_stop=lambda: bool(stopped))
        else:
            with pytest.raises(TaskReviewRequiredError) as caught:
                handler.run()
            assert not caught.value.saved
        assert len(model.calls) == 2
        assert len(requests) == 3
        if mode == "edit":
            assert page.frame_locator("#ueditor_1").locator("body").inner_text() == "用户新内容"


@pytest.mark.parametrize("editor_placeholders", [False, True])
def test_two_written_questions_are_both_completed_before_review(caplog, editor_placeholders):
    body = _body()
    start = body.index('<div class="questionLi" id="question2">')
    end = body.index("</form>", start)
    body = (
        body[:start]
        + """
      <div class="questionLi" id="question2">
        <h3 class="mark_name">2. (计算题) 本地测试：第二道完整计算题</h3>
        <iframe id="ueditor_2" srcdoc="<body contenteditable='true'><p><br></p></body>"></iframe>
        <textarea id="answer2" name="answer2" style="display:none"></textarea>
        <button type="button" title="TEX" onclick="openTex('ueditor_2')">TEX</button>
      </div>
    """
        + body[end:]
    )
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser, body)
        if editor_placeholders:
            page = browser._require_page()
            page.frame_locator("#ueditor_2").locator("body[contenteditable=true]").wait_for()
            page.evaluate("""() => {
                for (const frame of document.querySelectorAll('iframe[id^=ueditor_]')) {
                    frame.contentDocument.body.innerHTML='<p>\u200b\ufeff<br></p>';
                }
            }""")
            tex = _tex().replace(
                "image.src='", "body.append(body.ownerDocument.createTextNode('\\u200b'));image.src='"
            )
            page.route(
                "**/latex/html/*",
                lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=tex),
            )
        model = DraftModel()
        with caplog.at_level("INFO"), pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert len(model.calls) == 2
        assert len(requests) == 3
        assert all(request["pyFlag"] == ["1"] for request in requests)
        for field in ("answer1", "answer2"):
            assert "最终结果" in requests[-1][field][0]
            assert "ans-latex-moudle" in requests[-1][field][0]
        assert "第 2 题：第 3/3 段已核验" in caplog.text
        assert "整份作业 2 题已处理并确认暂存" in caplog.text
        assert not browser._require_page().locator("#workpop").is_visible()


@pytest.mark.parametrize("mode", ["during_model", "missing_save", "lost_content", "unsupported_editor"])
def test_draft_failure_preserves_content_and_does_not_submit(mode):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        body = _body()
        if mode == "missing_save":
            body = body.replace('<a id="saveDraft">Save</a>', '<a id="saveDraft">Other</a>')
        if mode == "unsupported_editor":
            body = body.replace('title="TEX"', 'title="Other"')
        requests = _setup(browser, body)
        page = browser._require_page()
        if mode == "lost_content":
            page.evaluate(
                "() => {window.afterSave=()=>{"
                "document.querySelector('#ueditor_1').contentDocument.body.innerHTML='';}}"
            )
        callback = (
            (lambda: page.frame_locator("#ueditor_1").locator("body").fill("用户输入"))
            if mode == "during_model"
            else lambda: None
        )
        model = DraftModel(callback)
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert not caught.value.saved
        assert len(model.calls) == 1
        assert all(request["pyFlag"] == ["1"] for request in requests)
        if mode == "during_model":
            assert page.frame_locator("#ueditor_1").locator("body").inner_text() == "用户输入"
        if mode == "missing_save":
            assert "最终结果" in page.frame_locator("#ueditor_1").locator("body").inner_text()


def test_stop_during_model_does_not_write_or_save():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        stopped = []
        model = DraftModel(lambda: stopped.append(True))
        _handler(browser, model).run_interruptibly(should_stop=lambda: bool(stopped))
        assert not requests
        assert (
            browser._require_page().frame_locator("#ueditor_1").locator("body").inner_text().strip() == ""
        )


@pytest.mark.parametrize(
    "mode", ["rejected", "missing_receipt", "page_changed", "render_failed", "not_synced"]
)
def test_unconfirmed_save_or_formula_retains_browser_for_review(mode):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        if mode == "not_synced":
            page.evaluate("""() => {window.afterSave=()=>{
                document.querySelector('#answer1').value='';
            }}""")
        if mode == "rejected":
            page.route("**/work/addStudentWorkNewWeb", lambda route: route.fulfill(json={"status": False}))
        if mode == "missing_receipt":
            page.evaluate("() => document.querySelector('#saveDraft').onclick = () => {}")
        if mode == "render_failed":
            page.route(
                "**/latex/html/*",
                lambda route: route.fulfill(
                    content_type="text/html",
                    body=_tex().replace('<svg><path d="M0 0L1 1"/></svg>', "<p>error</p>"),
                ),
            )
        callback = (
            (
                lambda: page.evaluate(
                    "() => document.querySelector('.mark_name').textContent='1. (简答题) changed'"
                )
            )
            if mode == "page_changed"
            else lambda: None
        )
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, DraftModel(callback)).run()
        assert not caught.value.saved
        assert not page.is_closed()
        assert all(item["pyFlag"] == ["1"] for item in requests)


def test_successful_save_with_editor_replacement_is_reread():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.evaluate("""() => {window.afterSave=()=>{
            const old = document.querySelector('#ueditor_1');
            const fresh = old.cloneNode(); fresh.srcdoc=old.contentDocument.body.outerHTML;
            old.replaceWith(fresh);
        }}""")
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, DraftModel()).run()
        assert caught.value.saved
        assert len(requests) == 3


def test_existing_answer_ai_decides_to_keep_and_saves_without_overwrite():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.frame_locator("#ueditor_1").locator("body").fill("用户已有推导")
        model = DraftModel()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert len(model.calls) == 1  # 只有第二题的客观题请求。
        assert len(model.review_calls) == 1
        assert model.review_calls[0]["existing_answer"]["text"] == "用户已有推导"
        assert "用户已有推导" in requests[0]["answer1"][0]


@pytest.mark.parametrize("formula_first", [False, True])
def test_incomplete_answer_is_replaced_only_after_complete_draft_is_generated(formula_first):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.frame_locator("#ueditor_1").locator("body").fill("das")
        page.evaluate(
            """() => {
            const body = document.querySelector('#ueditor_1').contentDocument.body;
            const img = body.ownerDocument.createElement('img');
            img.className='ans-latex-moudle'; img.setAttribute('data',escape(JSON.stringify('x=0')));
            img.src='PNG'; body.append(img);
            document.querySelector('#answer1').value=body.innerHTML;
        }""".replace("PNG", PNG)
        )
        page.frame_locator("#ueditor_1").locator("img").evaluate("i => i.decode()")
        model = DraftModel(rewrite=True, formula_first=formula_first)

        def check_old_answer_still_present():
            # review 和大题生成期间保留原文；客观题调用发生在覆盖后。
            if len(model.calls) <= 1:
                assert "das" in page.frame_locator("#ueditor_1").locator("body").inner_text()

        model.callback = check_old_answer_still_present
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert len(model.review_calls) == 1
        assert model.review_calls[0]["existing_answer"]["formulas"] == ["x=0"]
        assert len(model.calls) == 2
        saved = requests[-1]["answer1"][0]
        assert "das" not in saved
        assert "最终结果" in saved
        assert page.frame_locator("#ueditor_1").locator("img").count() == 1
        assert all(request["pyFlag"] == ["1"] for request in requests)


@pytest.mark.parametrize(
    "mode",
    ["invalid_review", "invalid_draft", "edit_during_review", "edit_during_solve", "clear_failed", "stop"],
)
def test_failed_or_interrupted_rewrite_preserves_existing_answer(mode, monkeypatch):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        body = page.frame_locator("#ueditor_1").locator("body")
        body.fill("原答案片段")
        stopped = []
        if mode == "clear_failed":
            original_press = _Element.press

            def press(element, key):
                if key != "Backspace":
                    original_press(element, key)

            monkeypatch.setattr(_Element, "press", press)

        class Model(DraftModel):
            def call_model(self, model, messages, tools):
                reviewing = messages[-1].content.startswith('{"existing_answer":')
                if mode == "invalid_review" and reviewing:
                    return LLMResponse('{"rewrite":"true"}')
                if mode == "invalid_draft" and not reviewing:
                    return LLMResponse('{"blocks":[]}')
                if (mode == "edit_during_review" and reviewing) or (
                    mode == "edit_during_solve" and not reviewing
                ):
                    body.fill("用户新输入")
                if mode == "stop":
                    stopped.append(True)
                return super().call_model(model, messages, tools)

        handler = _handler(browser, Model(rewrite=True))
        if mode == "stop":
            handler.run_interruptibly(should_stop=lambda: bool(stopped))
        else:
            with pytest.raises(TaskReviewRequiredError) as caught:
                handler.run()
            assert not caught.value.saved
        assert not requests
        assert body.inner_text() == ("用户新输入" if mode.startswith("edit_during") else "原答案片段")


def test_stop_while_formula_dialog_loads_leaves_partial_text_without_confirmation_or_save():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        stopped = []
        page = browser._require_page()

        def route(request):
            stopped.append(True)
            request.fulfill(content_type="text/html", body=_tex())

        page.route("**/latex/html/*", route)
        _handler(browser, DraftModel()).run_interruptibly(should_stop=lambda: bool(stopped))
        assert not requests
        assert page.frame_locator("#ueditor_1").locator("img").count() == 0
        assert "第一步" in page.frame_locator("#ueditor_1").locator("body").inner_text()


def test_delayed_preview_clears_old_formula_before_confirmation():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        tex = (
            _tex()
            .replace(
                "document.querySelector('textarea').oninput = () => {",
                "document.querySelector('textarea').oninput = () => {setTimeout(()=>{",
            )
            .replace(" : '';\n      };", " : '';},50);\n      };")
        )
        tex = tex.replace(
            '<div id="wrap_output"></div>', '<div id="wrap_output"><svg><path d="M0 0L2 2"/></svg></div>'
        )
        browser._require_page().route(
            "**/latex/html/*",
            lambda route: route.fulfill(
                content_type="text/html",
                body=tex,
            ),
        )
        handler = _handler(browser, DraftModel())
        url, _ = handler._target()
        handler._draft_assignment(url)
        assert len(requests) == 3


def test_saved_textarea_with_empty_editor_is_not_overwritten_or_sent_to_model():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        browser._require_page().evaluate("() => document.querySelector('#answer1').value='<p>已有解答</p>'")
        model = DraftModel()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert not caught.value.saved
        assert not model.calls
        assert not requests


def test_uncertain_keyboard_write_is_recovered_by_readback_without_replay(monkeypatch):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        original = _Element.type_text
        writes = []

        def interrupted(element, text):
            original(element, text)
            writes.append(text)
            raise BrowserElementError("local injected failure after input")

        monkeypatch.setattr(_Element, "type_text", interrupted)
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, DraftModel()).run()
        assert caught.value.saved
        assert len(writes) == 2
        assert len(requests) == 3
        text = browser._require_page().frame_locator("#ueditor_1").locator("body").inner_text()
        assert text.count("第一步") == 1
        assert text.count("最终结果") == 1


@pytest.mark.parametrize("mode", ["before", "partial", "always", "stop"])
def test_interrupted_text_retries_only_when_unchanged_and_not_stopped(mode, monkeypatch):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        original = _Element.type_text
        writes = []
        stopped = []

        def interrupted(element, text):
            writes.append(text)
            if len(writes) == 1 or mode == "always":
                if mode == "partial":
                    original(element, "只写入一部分")
                if mode == "stop":
                    stopped.append(True)
                raise BrowserElementError("injected input failure")
            original(element, text)

        monkeypatch.setattr(_Element, "type_text", interrupted)
        handler = _handler(browser, DraftModel())
        if mode == "stop":
            handler.run_interruptibly(should_stop=lambda: bool(stopped))
        else:
            with pytest.raises(TaskReviewRequiredError) as caught:
                handler.run()
            assert caught.value.saved == (mode == "before")
        assert len(writes) == {"before": 3, "partial": 1, "always": 2, "stop": 1}[mode]
        assert len(requests) == (3 if mode == "before" else 0)
        text = browser._require_page().frame_locator("#ueditor_1").locator("body").inner_text()
        if mode == "partial":
            assert text == "只写入一部分"
        if mode == "before":
            assert text.count("第一步") == text.count("最终结果") == 1


@pytest.mark.parametrize("already_open", [False, True])
def test_interrupted_tex_click_reconciles_dialog_before_retry(already_open, monkeypatch, caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        original = _Element.click
        clicks = []

        def interrupted(element):
            if element.evaluate("e => e.title === 'TEX'") is not True:
                original(element)
                return
            clicks.append(True)
            if len(clicks) == 1:
                if already_open:
                    original(element)
                try:
                    raise RuntimeError("PRIVATE_COURSE_URL intercepts pointer events")
                except RuntimeError as exc:
                    raise BrowserElementError("injected click failure") from exc
            original(element)

        monkeypatch.setattr(_Element, "click", interrupted)
        model = DraftModel()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert len(clicks) == (1 if already_open else 2)
        assert len(model.calls) == 2
        assert len(requests) == 3
        assert browser._require_page().frame_locator("#ueditor_1").locator("img").count() == 1
        assert "打开 TEX 窗口失败（点击被页面顶栏或浮层遮挡）" in caplog.text
        assert "PRIVATE_COURSE_URL" not in caplog.text


def test_real_pointer_overlay_timeout_is_recovered_without_forced_click(monkeypatch, caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        original = _Element.click
        clicks = []

        def blocked_once(element):
            if element.evaluate("e => e.title === 'TEX'") is not True:
                original(element)
                return
            clicks.append(True)
            if len(clicks) != 1:
                original(element)
                return
            page.evaluate("""() => {
                const cover = document.createElement('div'); cover.id='transientOverlay';
                cover.style.cssText='position:fixed;inset:0;z-index:9999;background:white';
                document.body.append(cover);
            }""")
            page.set_default_timeout(150)
            try:
                original(element)
            finally:
                page.set_default_timeout(1500)
                page.locator("#transientOverlay").evaluate("e => e.remove()")

        monkeypatch.setattr(_Element, "click", blocked_once)
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, DraftModel()).run()
        assert caught.value.saved
        assert len(clicks) == 2
        assert len(requests) == 3
        assert page.frame_locator("#ueditor_1").locator("img").count() == 1
        assert "打开 TEX 窗口失败（点击被页面顶栏或浮层遮挡）" in caplog.text


def test_long_answer_with_39_blocks_and_fixed_header_saves_every_formula_once():
    class LongModel(DraftModel):
        def call_model(self, model, messages, tools):
            result = super().call_model(model, messages, tools)
            if messages[-1].content == "请按正式考试答卷格式完成这道题的所有小问。":
                return LLMResponse(
                    json.dumps(
                        {
                            "blocks": [
                                {"kind": "latex", "content": f"x={i}"}
                                if i % 2
                                else {"kind": "text", "content": f"计算第{i}步。"}
                                for i in range(39)
                            ]
                        }
                    )
                )
            return result

    body = _body().replace(
        "<style>iframe",
        "<style>body {padding-top:1600px} "
        "#header {position:fixed;top:0;left:0;width:100%;height:80px;z-index:20;background:white} iframe",
    )
    body += '<div id="header">固定顶栏</div>'
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser, body)
        model = LongModel()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert len(model.calls) == 2
        assert len(requests) == 3
        editor = browser._require_page().frame_locator("#ueditor_1")
        assert editor.locator("img").count() == 19
        assert editor.locator("img").evaluate_all(
            "images => images.map(i => JSON.parse(unescape(i.getAttribute('data'))))"
        ) == [f"x={i}" for i in range(1, 39, 2)]
        assert "计算第38步。" in editor.locator("body").inner_text()


@pytest.mark.parametrize("long_draft", [False, True])
def test_auto_floating_toolbar_is_revealed_below_assignment_header(long_draft, caplog):
    class LongTextModel(DraftModel):
        def call_model(self, model, messages, tools):
            result = super().call_model(model, messages, tools)
            if messages[-1].content == "请按正式考试答卷格式完成这道题的所有小问。":
                value = json.loads(result.content)
                if long_draft:
                    value["blocks"] = [
                        {"kind": "latex", "content": f"x={i}"}
                        if i % 2
                        else {"kind": "text", "content": f"计算第{i}步。" + "列式计算得到所求结果。" * 20}
                        for i in range(31)
                    ]
                else:
                    value["blocks"][0]["content"] = "列式计算得到所求结果。" * 250
                return LLMResponse(json.dumps(value))
            return result

    body = _body().replace(
        '<iframe id="ueditor_1"',
        '<div class="edui-editor"><div class="edui-editor-toolbarbox">'
        '<button type="button" title="TEX" onclick="openTex(\'ueditor_1\')">TEX</button>'
        '</div><iframe id="ueditor_1"',
    )
    body = body.replace(
        '<button type="button" title="TEX" onclick="openTex(\'ueditor_1\')">TEX</button>\n    </div>',
        "</div>\n    </div>",
    )
    body += """
    <div id="header">固定作业顶栏</div><div style="height:1200px"></div>
    <style>
      body {padding-top:600px}
      #header {position:fixed;top:0;left:0;width:100%;height:80px;z-index:100;background:white}
      .edui-editor {width:520px}
      .edui-editor-toolbarbox {position:relative;height:30px;width:520px;background:white}
    </style>
    <script>
      const editor = document.querySelector('.edui-editor');
      const toolbar = document.querySelector('.edui-editor-toolbarbox');
      const frame = document.querySelector('#ueditor_1');
      window.texClicks=[];
      toolbar.querySelector('button').addEventListener('click', event => {
        const button=event.currentTarget, r=button.getBoundingClientRect();
        window.texClicks.push({
          unblocked:button.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2)),
          trusted:event.isTrusted, position:getComputedStyle(toolbar).position
        });
      });
      function floatToolbar() {
        const rect = editor.getBoundingClientRect();
        const floating = rect.top < 0 && rect.bottom > 80;
        toolbar.style.position = floating ? 'fixed' : 'relative';
        toolbar.style.top = '0px'; toolbar.style.zIndex='10';
      }
      window.addEventListener('scroll', floatToolbar);
      frame.addEventListener('load', () => {
        const body = frame.contentDocument.body;
        new MutationObserver(() => {
          frame.style.height = Math.max(140, body.scrollHeight) + 'px';
          floatToolbar();
        }).observe(body, {subtree:true,childList:true,characterData:true});
      });
    </script>
    """
    with PlaywrightBrowser(headless=True, timeout_ms=300) as browser:
        requests = _setup(browser, body)
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, LongTextModel()).run()
        assert caught.value.saved
        count = 15 if long_draft else 1
        assert (
            browser._require_page().evaluate("window.texClicks")
            == [{"unblocked": True, "trusted": True, "position": "relative"}] * count
        )
        assert len(requests) == 3
        assert browser._require_page().frame_locator("#ueditor_1").locator("img").count() == count
        assert "打开 TEX 窗口失败" not in caplog.text
