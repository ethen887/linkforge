"""Playwright coverage for the real Chaoxing continuous-scroll PDF contract."""

import json
from html import escape
from urllib.parse import quote

from linkforge.application.task_runner import TaskType
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.document_handler import ChaoxingDocumentTaskHandler
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector

_PDF_A_ID = "141755adf0d07a601e4027b3878aca2b"
_PDF_B_ID = "5ac3b700a9b8a474bcbafbde00c0a55b"


def _viewer_url(object_id: str, page_count: int) -> str:
    pages = "".join(
        f"""
            <div class="page" style="height: 700px">
                <img src="/thumb/{page}.png" alt="page {page}" style="height: 680px">
            </div>
        """
        for page in range(1, page_count + 1)
    )
    viewer_html = f"""
        <style>html, body {{ margin: 0; padding: 0; }}</style>
        {pages}
    """
    return f"data:text/html;charset=utf-8,{quote(viewer_html, safe='')}#/screen/v2/file_{object_id}"


def _module_url(object_id: str, page_count: int) -> str:
    viewer_url = _viewer_url(object_id, page_count)
    module_html = f"""
        <iframe
            id="panView"
            src="{escape(viewer_url, quote=True)}"
            style="width: 800px; height: 300px"
        ></iframe>
    """
    return (
        f"data:text/html;charset=utf-8,{quote(module_html, safe='')}"
        f"#/ananas/modules/pdf/index.html?objectid={object_id}"
    )


def _course_page(*documents: tuple[str, int, bool, bool]) -> str:
    module_html_parts: list[str] = []
    for object_id, page_count, has_job_icon, finished in documents:
        classes = "ans-attach-ct ans-job-finished" if finished else "ans-attach-ct"
        icon = '<span class="ans-job-icon"></span>' if has_job_icon else ""
        module_data = escape(
            json.dumps({"objectid": object_id, "pagenum": page_count}),
            quote=True,
        )
        module_url = escape(_module_url(object_id, page_count), quote=True)
        module_html_parts.append(
            f"""
                <div class="{classes}">
                    {icon}
                    <iframe data="{module_data}" src="{module_url}"></iframe>
                </div>
            """
        )

    content_html = "".join(module_html_parts)
    content_url = (
        f"data:text/html;charset=utf-8,{quote(content_html, safe='')}#/mooc-ans/knowledge/cards?num=1"
    )
    page_html = f"""
        <ul id="prev_tab"><li class="active">PPT</li></ul>
        <iframe src="{escape(content_url, quote=True)}"></iframe>
    """
    return f"data:text/html;charset=utf-8,{quote(page_html, safe='')}"


def _handler(browser: PlaywrightBrowser) -> ChaoxingDocumentTaskHandler:
    return ChaoxingDocumentTaskHandler(
        browser,
        viewer_ready_timeout_seconds=2.0,
        timeout_seconds=5.0,
        progress_timeout_seconds=1.0,
        poll_interval_seconds=0.02,
    )


def test_document_handler_scrolls_nested_viewer_then_detector_returns_content() -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_course_page((_PDF_A_ID, 2, False, False)))
        detector = ChaoxingTaskDetector(browser)

        assert detector.detect() is TaskType.DOCUMENT
        _handler(browser).run()
        assert detector.detect() is TaskType.CONTENT


def test_two_documents_are_processed_one_per_handler_invocation() -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(
            _course_page(
                (_PDF_A_ID, 2, False, False),
                (_PDF_B_ID, 1, False, False),
            )
        )
        detector = ChaoxingTaskDetector(browser)

        assert detector.detect() is TaskType.DOCUMENT
        _handler(browser).run()
        assert detector.detect() is TaskType.DOCUMENT
        _handler(browser).run()
        assert detector.detect() is TaskType.CONTENT


def test_platform_finished_job_document_is_skipped_without_scrolling() -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_course_page((_PDF_A_ID, 2, True, True)))

        assert ChaoxingTaskDetector(browser).detect() is TaskType.CONTENT
