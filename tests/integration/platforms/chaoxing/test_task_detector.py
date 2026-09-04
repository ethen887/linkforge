"""Local DOM smoke test for Chaoxing task detection through Playwright."""

from html import escape
from urllib.parse import quote

from linkforge.application.task_runner import TaskType
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector


def test_detector_reads_pending_activity_from_card_frame() -> None:
    content_html = """
        <div class="ans-attach-ct ans-job-finished">
            <span class="ans-job-icon"></span>
            <iframe src="/ananas/modules/video/"></iframe>
        </div>
        <div class="ans-attach-ct">
            <iframe src="/ananas/modules/pdf/"></iframe>
        </div>
        <div class="ans-attach-ct">
            <iframe src="/ananas/modules/work/"></iframe>
        </div>
    """
    content_url = f"data:text/html;charset=utf-8,{quote(content_html)}#/mooc-ans/knowledge/cards?num=1"
    page_html = f"""
        <ul id="prev_tab">
            <li>概述</li>
            <li class="active">小结</li>
        </ul>
        <iframe src="{escape(content_url, quote=True)}"></iframe>
    """
    data_url = f"data:text/html;charset=utf-8,{quote(page_html, safe='')}"

    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(data_url)

        assert ChaoxingTaskDetector(browser).detect() is TaskType.DOCUMENT
