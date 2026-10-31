"""编辑器异步初始化、已有坏图及脱敏诊断的回归验证。"""

import base64
import logging
from dataclasses import replace

import pytest

from linkforge.application.task_runner import TaskReviewRequiredError
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.llm.base import LLMResponse
from tests.integration.platforms.chaoxing.test_written_assignment import PNG, DraftModel, _handler, _setup


@pytest.mark.parametrize("mode", ["initializing", "missing_frame", "restoring"])
def test_transient_editor_readiness_is_waited_for_before_drafting(mode, caplog):
    caplog.set_level(logging.DEBUG, logger="linkforge")
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.evaluate(
            """mode => {
                const frame = document.querySelector('#ueditor_1');
                const body = frame.contentDocument.body;
                if (mode === 'initializing') {
                    body.contentEditable = 'false';
                    window.restoreEditor = () => body.contentEditable = 'true';
                } else if (mode === 'missing_frame') {
                    frame.id = 'loading_editor';
                    window.restoreEditor = () => frame.id = 'ueditor_1';
                } else {
                    document.querySelector('#answer1').value = '<p>已保存答案</p>';
                    window.restoreEditor = () => body.innerHTML = '<p>已保存答案</p>';
                }
            }""",
            mode,
        )
        model = DraftModel()
        handler = _handler(browser, model)
        original_sleep = handler._sleep

        def restore(_seconds):
            # 首次只读检查已观察到未就绪，再模拟平台完成初始化。
            assert not model.calls
            assert not requests
            page.evaluate("() => window.restoreEditor()")
            handler._sleep = original_sleep

        handler._sleep = restore
        with pytest.raises(TaskReviewRequiredError) as caught:
            handler.run()
        assert caught.value.saved
        assert len(model.calls) == (1 if mode == "restoring" else 2)
        assert requests
        assert all(request["pyFlag"] == ["1"] for request in requests)
        assert "等待编辑器初始化" in caplog.text
        assert "编辑器已就绪" in caplog.text


@pytest.mark.parametrize("stop", [False, True])
def test_unready_editor_times_out_or_stops_without_writing(stop, caplog):
    caplog.set_level(logging.DEBUG, logger="linkforge")
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.frame_locator("#ueditor_1").locator("body").evaluate("e => e.contentEditable = 'false'")
        model = DraftModel()
        handler = _handler(browser, model)
        handler._config = replace(
            handler._config, readiness_timeout_seconds=0.05, poll_interval_seconds=0.01
        )
        if stop:
            handler.run_interruptibly(should_stop=lambda: "等待编辑器初始化" in caplog.text)
        else:
            with pytest.raises(TaskReviewRequiredError) as caught:
                handler.run()
            assert not caught.value.saved
            assert "第 1 题编辑器在等待后仍未就绪" in caplog.text
            assert "reason=initializing" in caplog.text
        assert not model.calls
        assert not requests
        assert not page.locator("#workpop").is_visible()


def _broken_formula(page):
    page.evaluate("""() => {
        const body = document.querySelector('#ueditor_1').contentDocument.body;
        body.innerHTML = '<p>PRIVATE-EXISTING-ANSWER</p>';
        const image = body.ownerDocument.createElement('img');
        image.className = 'ans-latex-moudle';
        image.setAttribute('data', escape(JSON.stringify('PRIVATE-FORMULA')));
        image.src = '/PRIVATE-IMAGE-URL.png?token=PRIVATE-TOKEN';
        body.append(image);
        document.querySelector('#answer1').value = body.innerHTML;
    }""")
    page.frame_locator("#ueditor_1").locator("img").evaluate(
        "async i => { try { await i.decode(); } catch {} }"
    )


def test_loading_formula_is_waited_for_and_kept_without_unnecessary_rewrite(caplog):
    caplog.set_level(logging.DEBUG, logger="linkforge")
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        pending = []
        page.route("**/pending-formula.png", lambda route: pending.append(route))
        page.evaluate("""() => {
            const body = document.querySelector('#ueditor_1').contentDocument.body;
            const image = body.ownerDocument.createElement('img');
            image.className = 'ans-latex-moudle';
            image.setAttribute('data', escape(JSON.stringify('x=1')));
            image.src = '/pending-formula.png';
            body.append(image);
            document.querySelector('#answer1').value = body.innerHTML;
        }""")
        model = DraftModel()
        handler = _handler(browser, model)
        original_sleep = handler._sleep

        def finish_loading(_seconds):
            assert not model.calls
            assert not requests
            assert len(pending) == 1
            pending[0].fulfill(content_type="image/png", body=base64.b64decode(PNG.split(",")[1]))
            handler._sleep = original_sleep

        handler._sleep = finish_loading
        with pytest.raises(TaskReviewRequiredError) as caught:
            handler.run()
        assert caught.value.saved
        assert len(model.calls) == 1
        assert model.review_calls[0]["existing_answer"]["formulas"] == ["x=1"]
        assert page.frame_locator("#ueditor_1").locator("img").count() == 1
        assert "pending_images=1" in caplog.text
        assert "将生成完整草稿后重做" not in caplog.text


def test_existing_broken_formula_with_valid_metadata_can_be_replaced_and_saved(caplog):
    caplog.set_level(logging.DEBUG, logger="linkforge")
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        _broken_formula(page)

        def assert_preserved_before_generation():
            if len(model.calls) == 1:
                assert (
                    "PRIVATE-EXISTING-ANSWER"
                    in page.frame_locator("#ueditor_1").locator("body").inner_text()
                )

        model = DraftModel(callback=assert_preserved_before_generation)
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert caught.value.saved
        assert not model.review_calls  # 坏图不能被模型的“保留”判断挡住。
        assert len(model.calls) == 2
        assert "PRIVATE-EXISTING-ANSWER" not in requests[-1]["answer1"][0]
        assert "最终结果" in requests[-1]["answer1"][0]
        assert page.frame_locator("#ueditor_1").locator("img").evaluate("i => i.naturalWidth > 0")
        assert all(request["pyFlag"] == ["1"] for request in requests)
        assert "question=1 reason=images_not_ready" in caplog.text
        assert "broken_images=1" in caplog.text
        assert "将生成完整草稿后重做" in caplog.text
        assert "PRIVATE-" not in caplog.text


@pytest.mark.parametrize("failure", ["invalid_draft", "user_edit", "stop"])
def test_broken_formula_rewrite_preserves_original_until_draft_is_valid(failure):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        _broken_formula(page)
        stopped = []

        class Model(DraftModel):
            def call_model(self, model, messages, tools):
                if failure == "user_edit":
                    page.frame_locator("#ueditor_1").locator("body").fill("用户新输入")
                if failure == "stop":
                    stopped.append(True)
                if failure == "invalid_draft":
                    return LLMResponse('{"blocks":[]}')
                return super().call_model(model, messages, tools)

        handler = _handler(browser, Model())
        if failure == "stop":
            handler.run_interruptibly(should_stop=lambda: bool(stopped))
        else:
            with pytest.raises(TaskReviewRequiredError) as caught:
                handler.run()
            assert not caught.value.saved
        assert not requests
        content = page.frame_locator("#ueditor_1").locator("body").inner_text()
        assert ("用户新输入" if failure == "user_edit" else "PRIVATE-EXISTING-ANSWER") in content


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("ordinary_image", "unrecognized_image"),
        ("invalid_formula", "unrecognized_image"),
        ("table", "unsupported_content"),
        ("duplicate_editor", "structure"),
    ],
)
def test_unsupported_editor_content_is_preserved_with_specific_private_safe_diagnostics(
    mode, reason, caplog
):
    caplog.set_level(logging.DEBUG, logger="linkforge")
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        page.evaluate(
            """mode => {
            const question = document.querySelector('#question1');
            const frame = document.querySelector('#ueditor_1');
            const body = frame.contentDocument.body;
            body.innerHTML = '<p>PRIVATE-ANSWER</p>';
            if (mode === 'duplicate_editor') {
                question.append(frame.cloneNode(true));
            } else if (mode === 'table') {
                body.innerHTML += '<table><tr><td>PRIVATE-TABLE</td></tr></table>';
            } else {
                const image = body.ownerDocument.createElement('img');
                image.src = '/PRIVATE-IMAGE.png?token=PRIVATE-TOKEN';
                if (mode === 'invalid_formula') {
                    image.className = 'ans-latex-moudle';
                    image.setAttribute('data', 'PRIVATE-INVALID-FORMULA');
                }
                body.append(image);
            }
        }""",
            mode,
        )
        original = page.frame_locator("#ueditor_1").first.locator("body").inner_html()
        model = DraftModel()
        with pytest.raises(TaskReviewRequiredError) as caught:
            _handler(browser, model).run()
        assert not caught.value.saved
        assert not model.calls
        assert not requests
        assert page.frame_locator("#ueditor_1").first.locator("body").inner_html() == original
        assert f"question=1 reason={reason}" in caplog.text
        assert "PRIVATE-" not in caplog.text
