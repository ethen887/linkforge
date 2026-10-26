"""离线重现 TEX 的慢上传、预览故障和确认边界；不访问真实作业。"""

from dataclasses import replace

import pytest

from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.exceptions import ChaoxingWrittenStateError
from linkforge.platforms.chaoxing.quiz_handler import QuizStoppedError
from linkforge.platforms.chaoxing.written_answer import WrittenBlock, WrittenDraft
from tests.integration.platforms.chaoxing.test_written_assignment import (
    PNG,
    DraftModel,
    _handler,
    _setup,
    _tex,
)


def _route_tex(page, tex):
    tex = tex.replace(
        "const latex = document.querySelector('textarea').value;",
        "const latex = document.querySelector('textarea').value;"
        "parent.confirmClicks=(parent.confirmClicks||0)+1;",
    )
    page.route(
        "**/latex/html/*",
        lambda route: route.fulfill(content_type="text/html; charset=utf-8", body=tex),
    )


def _write(handler):
    url, _ = handler._target()
    return handler._write_draft(
        url, 0, WrittenDraft((WrittenBlock("text", "已录入正文"), WrittenBlock("latex", "x=2")))
    )


def test_upload_slower_than_dom_readiness_is_waited_without_second_confirmation():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        _route_tex(page, _tex().replace("}, 30);", "}, 450);"))
        handler = _handler(browser, DraftModel())
        handler._config = replace(handler._config, readiness_timeout_seconds=0.1)
        state = _write(handler)
        assert state.formulas == ("x=2",)
        assert page.evaluate("window.confirmClicks") == 1
        assert page.frame_locator("#ueditor_1").locator("img").count() == 1
        assert not requests


def test_transient_preview_is_retriggered_once_before_upload(caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        _setup(browser)
        page = browser._require_page()
        tex = _tex().replace(
            "document.querySelector('textarea').oninput = () => {",
            "document.querySelector('textarea').oninput = () => {"
            "if(document.querySelector('textarea').value.trim()) {"
            "window.renders=(window.renders||0)+1;if(window.renders<=2)return;}",
        )
        _route_tex(page, tex)
        with caplog.at_level("INFO"):
            assert _write(_handler(browser, DraftModel())).formulas == ("x=2",)
        assert page.evaluate("window.confirmClicks") == 1
        assert caplog.text.count("确认前重新输入一次") == 1


@pytest.mark.parametrize("mode", ["syntax", "unresponsive", "empty_svg", "changed_input", "user_edit"])
def test_invalid_or_changed_preview_is_not_confirmed_or_saved(mode, caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        tex = _tex()
        if mode == "syntax":
            tex = tex.replace(
                '<svg><path d="M0 0L1 1"/></svg>',
                '<svg><g data-mml-node="merror"><text>PRIVATE-RENDER-ERROR</text></g></svg>',
            )
        elif mode == "unresponsive":
            tex = tex.replace('<svg><path d="M0 0L1 1"/></svg>', "")
        elif mode == "empty_svg":
            tex = tex.replace('<svg><path d="M0 0L1 1"/></svg>', "<svg></svg>")
        else:
            effect = (
                "document.querySelector('textarea').value='PRIVATE-EDIT';"
                if mode == "changed_input"
                else "parent.document.querySelector('#ueditor_1').contentDocument.body.append('用户补充');"
            )
            tex = tex.replace(
                "document.querySelector('textarea').oninput = () => {",
                "document.querySelector('textarea').oninput = () => {"
                "if(document.querySelector('textarea').value.trim()){setTimeout(()=>{" + effect + "},50);}",
            )
        _route_tex(page, tex)
        reasons = {
            "syntax": "语法错误",
            "unresponsive": "新公式预览稳定超时",
            "empty_svg": "新公式预览稳定超时",
            "changed_input": "输入已改变",
            "user_edit": "正文或已有公式发生变化",
        }
        with caplog.at_level("INFO"), pytest.raises(ChaoxingWrittenStateError, match=reasons[mode]):
            _write(_handler(browser, DraftModel()))
        assert page.evaluate("window.confirmClicks||0") == 0
        assert not requests
        assert "PRIVATE-" not in caplog.text
        assert "已录入正文" in page.frame_locator("#ueditor_1").locator("body").inner_text()


@pytest.mark.parametrize("mode", ["missing_insert", "broken_image", "unexpected_content"])
def test_failure_after_confirmation_preserves_draft_without_reupload(mode, caplog):
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        tex = _tex()
        if mode == "missing_insert":
            tex = tex.replace("body.append(image);", "")
        elif mode == "broken_image":
            tex = tex.replace(PNG, "data:image/png;base64,AA==")
        else:
            tex = tex.replace("body.append(image);", "body.append(image);body.append('用户补充');")
        _route_tex(page, tex)
        reasons = {
            "missing_insert": "等待公式上传、插入和图片加载超时",
            "broken_image": "图片加载失败",
            "unexpected_content": "正文或公式与预期不一致",
        }
        with caplog.at_level("INFO"), pytest.raises(ChaoxingWrittenStateError, match=reasons[mode]):
            _write(_handler(browser, DraftModel()))
        assert page.evaluate("window.confirmClicks") == 1
        assert not requests
        assert "已录入正文" in page.frame_locator("#ueditor_1").locator("body").inner_text()
        assert "确认前重新输入一次" not in caplog.text


def test_stop_after_confirmation_interrupts_upload_wait_without_replay():
    with PlaywrightBrowser(headless=True, timeout_ms=1500) as browser:
        requests = _setup(browser)
        page = browser._require_page()
        _route_tex(page, _tex().replace("}, 30);", "}, 5000);"))
        handler = _handler(browser, DraftModel())
        handler._should_stop = lambda: bool(page.evaluate("window.confirmClicks||0"))
        with pytest.raises(QuizStoppedError):
            _write(handler)
        assert page.evaluate("window.confirmClicks") == 1
        assert not requests
