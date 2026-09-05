"""Local Playwright integration tests for Chaoxing VIDEO and CONTENT handlers."""

import time
from html import escape
from urllib.parse import quote

from linkforge.browser.base import Browser
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.video_handler import (
    ChaoxingVideoHandlerConfig,
    ChaoxingVideoTaskHandler,
)


def _data_url(html: str, route: str) -> str:
    return f"data:text/html;charset=utf-8,{quote(html, safe='')}#{route}"


def _wait_until_chaoxing_page_ready(
    browser: Browser,
    *,
    timeout_seconds: float = 3.0,
    poll_interval_seconds: float = 0.01,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: ChaoxingInspectionError | None = None

    while time.monotonic() < deadline:
        try:
            inspect_chaoxing_page(browser)
            return
        except ChaoxingInspectionError as exc:
            last_error = exc
            time.sleep(poll_interval_seconds)

    raise AssertionError("Chaoxing integration fixture did not become inspectable.") from last_error


def test_video_handler_plays_media_but_waits_for_task_point_marker() -> None:
    video_html = """
        <video id="video"></video>
        <script>
            const state = {paused: true, ended: false, currentTime: 0};
            const video = document.getElementById("video");
            Object.defineProperties(video, {
                paused: {get: () => state.paused},
                ended: {get: () => state.ended},
                currentTime: {get: () => state.currentTime},
                duration: {get: () => 1},
                readyState: {get: () => 4},
            });
            video.play = async () => {
                document.body.dataset.playCalled = "true";
                state.paused = false;
                setTimeout(() => {
                    state.currentTime = 1;
                    state.ended = true;
                    state.paused = true;
                }, 100);
            };
        </script>
    """
    video_url = _data_url(video_html, "/ananas/modules/video/index.html?objectid=local")
    content_html = f"""
        <div id="task" class="ans-attach-ct">
            <span class="ans-job-icon"></span>
            <iframe src="{escape(video_url, quote=True)}"></iframe>
        </div>
        <script>
            setTimeout(() => document.getElementById("task").classList.add("ans-job-finished"), 500);
        </script>
    """
    content_url = _data_url(
        content_html,
        "/mooc-ans/knowledge/cards?knowledgeid=100&num=1",
    )
    page_html = f"""
        <ul id="prev_tab"><li class="active">Video</li><li>Next</li></ul>
        <iframe src="{escape(content_url, quote=True)}"></iframe>
    """

    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page_html, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        handler = ChaoxingVideoTaskHandler(
            browser,
            config=ChaoxingVideoHandlerConfig(
                poll_interval_seconds=0.05,
                overall_timeout_seconds=5.0,
                video_available_timeout_seconds=1.0,
                playback_start_timeout_seconds=1.0,
                progress_timeout_seconds=2.0,
                platform_finished_timeout_seconds=2.0,
            ),
        )

        handler.run()

        play_markers = browser.evaluate_in_frames(
            "() => window.location.href.includes('/ananas/modules/video/') "
            "? document.body.dataset.playCalled || null : null"
        )
        assert "true" in play_markers


def test_content_handler_waits_for_active_card_and_content_frame_replacement() -> None:
    first_content_url = _data_url(
        "<p>First</p>",
        "/mooc-ans/knowledge/cards?knowledgeid=100&num=1",
    )
    second_content_url = _data_url(
        "<p>Second</p>",
        "/mooc-ans/knowledge/cards?knowledgeid=100&num=2",
    )
    page_html = f"""
        <ul id="prev_tab">
            <li class="active">First</li>
            <li onclick="
                document.querySelector('#prev_tab li.active').classList.remove('active');
                this.classList.add('active');
                document.getElementById('content').src = '{second_content_url}';
            ">Second</li>
        </ul>
        <iframe id="content" src="{escape(first_content_url, quote=True)}"></iframe>
    """

    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page_html, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        handler = ChaoxingContentTaskHandler(
            browser,
            config=ChaoxingContentHandlerConfig(
                poll_interval_seconds=0.05,
                navigation_timeout_seconds=2.0,
            ),
        )

        handler.run()

        active_indexes = browser.evaluate_in_frames(
            "() => Array.from(document.querySelectorAll('#prev_tab li')).findIndex("
            "element => element.classList.contains('active'))"
        )
        assert 1 in active_indexes


def test_content_handler_advances_to_next_knowledge_in_document_order() -> None:
    first_content_url = _data_url(
        "<p>Knowledge 100</p>",
        "/mooc-ans/knowledge/cards?knowledgeid=100&num=0",
    )
    second_content_url = _data_url(
        "<p>Knowledge 200</p>",
        "/mooc-ans/knowledge/cards?knowledgeid=200&num=0",
    )
    page_html = f"""
        <ul id="prev_tab"><li class="active">Only card</li></ul>
        <div class="posCatalog_select" id="cur100">
            <span class="posCatalog_name">Knowledge 100</span>
        </div>
        <div class="posCatalog_select" id="cur200">
            <span class="posCatalog_name" onclick="
                document.getElementById('content').src = '{second_content_url}';
            ">Knowledge 200</span>
        </div>
        <iframe id="content" src="{escape(first_content_url, quote=True)}"></iframe>
    """

    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page_html, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        handler = ChaoxingContentTaskHandler(
            browser,
            config=ChaoxingContentHandlerConfig(
                poll_interval_seconds=0.05,
                navigation_timeout_seconds=2.0,
            ),
        )

        handler.run()

        content_urls = browser.evaluate_in_frames("() => window.location.href")
        assert any("knowledgeid=200" in url for url in content_urls if isinstance(url, str))
