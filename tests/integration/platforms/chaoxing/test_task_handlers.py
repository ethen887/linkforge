"""Local Playwright integration tests for Chaoxing VIDEO and CONTENT handlers."""

import time
from html import escape
from urllib.parse import quote

import pytest

from linkforge.application.task_runner import TaskRunner, TaskType
from linkforge.browser.base import Browser
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.navigation import ChaoxingNavigationMonitor
from linkforge.platforms.chaoxing.recovery import ChaoxingTaskRecovery
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from linkforge.platforms.chaoxing.video_handler import (
    ChaoxingVideoHandlerConfig,
    ChaoxingVideoTaskHandler,
)
from linkforge.platforms.chaoxing.video_state import VideoSession


def test_manual_navigation_follows_new_video_without_deferring_old_video() -> None:
    def content_url(chapter: str) -> str:
        play = "state.paused = false;"
        if chapter == "200":
            play += "state.ended = true; state.currentTime = 1; parent.postMessage('ended', '*');"
        video_html = f"""
            <video id="video"></video>
            <script>
                const state = {{paused: true, ended: false, currentTime: 0}};
                const video = document.getElementById('video');
                Object.defineProperties(video, {{
                    paused: {{get: () => state.paused}}, ended: {{get: () => state.ended}},
                    currentTime: {{get: () => state.currentTime}},
                    duration: {{get: () => 10}}, readyState: {{get: () => 4}},
                }});
                video.play = () => {{{play}}};
            </script>
        """
        video = _data_url(video_html, f"/ananas/modules/video/index.html?chapter={chapter}")
        content = f"""
            <div id="task" class="ans-attach-ct"><span class="ans-job-icon"></span>
                <iframe src="{escape(video, quote=True)}"></iframe>
            </div>
            <script>addEventListener('message', event => {{
                if (event.data === 'ended') {{
                    document.getElementById('task').classList.add('ans-job-finished');
                }}
            }});</script>
        """
        return _data_url(content, f"/mooc-ans/knowledge/cards?knowledgeid={chapter}&num=0")

    first, selected = content_url("100"), content_url("200")
    page = f"""
        <ul id="prev_tab"><li class="active">Video</li></ul>
        <button id="choose-b" onclick="document.getElementById('card').src = this.dataset.target;"
            data-target="{escape(selected, quote=True)}">Select B</button>
        <iframe id="card" src="{escape(first, quote=True)}"></iframe>
    """
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        original = inspect_chaoxing_page(browser)
        session = VideoSession()
        detector = ChaoxingTaskDetector(browser, video_session=session)
        navigator = ChaoxingContentTaskHandler(browser, detector=detector)
        navigation = ChaoxingNavigationMonitor(browser, poll_interval_seconds=0.05)
        recovery = ChaoxingTaskRecovery(browser, navigator, video_session=session, navigation=navigation)
        switched = False

        def sleep(seconds: float) -> None:
            nonlocal switched
            if not switched:
                switched = True
                browser.click("#choose-b")
            time.sleep(seconds)

        handler = ChaoxingVideoTaskHandler(
            browser,
            video_session=session,
            navigation=navigation,
            sleep=sleep,
            config=ChaoxingVideoHandlerConfig(poll_interval_seconds=0.05, overall_timeout_seconds=5),
        )
        runner = TaskRunner(
            detector=detector,
            video_handler=handler,
            document_handler=navigator,
            content_handler=navigator,
            comment_handler=navigator,
            quiz_handler=navigator,
            recovery=recovery,
        )

        def finished() -> bool:
            try:
                state = inspect_chaoxing_page(browser)
            except ChaoxingInspectionError:
                return False
            return state.knowledge_id == "200" and bool(state.modules) and state.modules[0].finished

        runner.run(should_stop=finished)
        assert switched
        assert finished()
        assert runner.issues == []
        assert not session.is_deferred(original, 0)
        assert not session.is_handled(original, 0)


def test_failed_video_is_deferred_and_next_video_completes() -> None:
    def video_url(*, broken: bool) -> str:
        play = (
            "throw new Error('fixture failure');"
            if broken
            else """
            state.paused = false;
            state.ended = true;
            state.currentTime = 1;
            parent.postMessage('ended', '*');
        """
        )
        html = f"""
            <video id="video"></video>
            <script>
                const state = {{paused: true, ended: false, currentTime: 0}};
                const video = document.getElementById('video');
                Object.defineProperties(video, {{
                    paused: {{get: () => state.paused}},
                    ended: {{get: () => state.ended}},
                    currentTime: {{get: () => state.currentTime}},
                    duration: {{get: () => 1}}, readyState: {{get: () => 4}},
                }});
                video.pause = () => {{state.paused = true;}};
                video.play = () => {{{play}}};
            </script>
        """
        return _data_url(html, f"/ananas/modules/video/index.html?broken={broken}")

    modules = "".join(
        f'<div class="ans-attach-ct"><span class="ans-job-icon"></span>'
        f'<iframe src="{escape(video_url(broken=broken), quote=True)}"></iframe></div>'
        for broken in (True, False)
    )
    content = (
        modules
        + """
        <script>
            addEventListener('message', event => {
                if (event.data !== 'ended') return;
                const frame = Array.from(document.querySelectorAll('iframe'))
                    .find(candidate => candidate.contentWindow === event.source);
                frame.closest('.ans-attach-ct').classList.add('ans-job-finished');
            });
        </script>
    """
    )
    content_url = _data_url(content, "/mooc-ans/knowledge/cards?knowledgeid=100&num=0")
    page = (
        '<ul id="prev_tab"><li class="active">Videos</li></ul>'
        f'<iframe src="{escape(content_url)}"></iframe>'
    )
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        session = VideoSession()
        detector = ChaoxingTaskDetector(browser, video_session=session)
        navigator = ChaoxingContentTaskHandler(browser, detector=detector)
        recovery = ChaoxingTaskRecovery(browser, navigator, video_session=session)
        video = ChaoxingVideoTaskHandler(
            browser,
            video_session=session,
            config=ChaoxingVideoHandlerConfig(poll_interval_seconds=0.05, overall_timeout_seconds=5),
        )
        runner = TaskRunner(
            detector=detector,
            video_handler=video,
            document_handler=navigator,
            content_handler=navigator,
            comment_handler=navigator,
            quiz_handler=navigator,
            recovery=recovery,
        )
        runner.run(should_stop=lambda: inspect_chaoxing_page(browser).modules[1].finished)
        state = inspect_chaoxing_page(browser)
        assert session.is_deferred(state, 0)
        assert not state.modules[0].finished
        assert not session.is_handled(state, 0)
        assert state.modules[1].finished
        assert len(runner.issues) == 1
        assert "第 1 个模块" in runner.issues[0].location
        assert detector.detect() is TaskType.CONTENT


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


@pytest.mark.parametrize("marker_mode", ["task_point", "ordinary", "delayed_task_point"])
def test_video_handler_plays_media_and_verifies_completion(marker_mode: str) -> None:
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
    icon = '<span class="ans-job-icon"></span>' if marker_mode == "task_point" else ""
    marker_script = ""
    if marker_mode == "delayed_task_point":
        marker_script = """
            setTimeout(() => document.getElementById("task").insertAdjacentHTML(
                "afterbegin", '<span class="ans-job-icon"></span>'), 200);
        """
    if marker_mode != "ordinary":
        marker_script += """
            setTimeout(() => document.getElementById("task").classList.add("ans-job-finished"), 500);
        """
    content_html = f"""
        <div id="task" class="ans-attach-ct">
            {icon}
            <iframe src="{escape(video_url, quote=True)}"></iframe>
        </div>
        <script>
            {marker_script}
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
        session = VideoSession()
        detector = ChaoxingTaskDetector(browser, video_session=session)
        assert detector.detect() is TaskType.VIDEO
        handler = ChaoxingVideoTaskHandler(
            browser,
            video_session=session,
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
        assert detector.detect() is TaskType.CONTENT
        state = inspect_chaoxing_page(browser)
        assert state.modules[0].has_job_icon is (marker_mode != "ordinary")
        assert state.modules[0].finished is (marker_mode != "ordinary")


def test_stall_recovery_only_restarts_the_pending_video_with_identical_urls() -> None:
    video_html = """
        <video id="video"></video>
        <script>
            const state = {paused: false, ended: false, currentTime: 0};
            const video = document.getElementById('video');
            document.body.dataset.pauseCount = '0';
            Object.defineProperties(video, {
                paused: {get: () => state.paused},
                ended: {get: () => state.ended},
                currentTime: {get: () => state.currentTime},
                duration: {get: () => 1},
                readyState: {get: () => 4},
            });
            video.pause = () => {
                state.paused = true;
                document.body.dataset.pauseCount = String(Number(document.body.dataset.pauseCount) + 1);
            };
            video.play = async () => {
                state.paused = false;
                state.currentTime = 1;
                state.ended = true;
            };
        </script>
    """
    video_url = _data_url(video_html, "/ananas/modules/video/index.html?objectid=local-stalled")
    content_html = f"""
        <div class="ans-attach-ct ans-job-finished">
            <span class="ans-job-icon"></span>
            <iframe src="{escape(video_url, quote=True)}"></iframe>
        </div>
        <div class="ans-attach-ct">
            <iframe src="{escape(video_url, quote=True)}"></iframe>
        </div>
    """
    content_url = _data_url(content_html, "/mooc-ans/knowledge/cards?knowledgeid=100&num=1")
    page_html = f"""
        <ul id="prev_tab"><li class="active">Videos</li></ul>
        <iframe src="{escape(content_url, quote=True)}"></iframe>
    """
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page_html, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        session = VideoSession()
        handler = ChaoxingVideoTaskHandler(
            browser,
            video_session=session,
            config=ChaoxingVideoHandlerConfig(
                poll_interval_seconds=0.05,
                overall_timeout_seconds=3.0,
                video_available_timeout_seconds=0.1,
                progress_timeout_seconds=2.0,
                stall_recovery_interval_seconds=0.1,
            ),
        )
        handler.run()
        counts = browser.evaluate_in_frames("() => document.body.dataset.pauseCount || null")
        assert [count for count in counts if count is not None] == ["0", "1"]
        assert ChaoxingTaskDetector(browser, video_session=session).detect() is TaskType.CONTENT


@pytest.mark.parametrize("has_task_point", [False, True])
def test_identical_video_urls_are_played_and_completed_independently(has_task_point: bool) -> None:
    # Data URLs have opaque origins: this also verifies paths across origin boundaries.
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
                    parent.postMessage("ended", "*");
                }, 100);
            };
        </script>
    """
    video_url = _data_url(video_html, "/ananas/modules/video/index.html")
    icon = '<span class="ans-job-icon"></span>' if has_task_point else ""
    module_html = f'<div class="ans-attach-ct">{icon}<iframe src="{escape(video_url)}"></iframe></div>'
    content_html = (
        module_html * 2
        + """
        <script>
            addEventListener("message", event => {
                if (event.data !== "ended") return;
                const frame = Array.from(document.querySelectorAll("iframe"))
                    .find(candidate => candidate.contentWindow === event.source);
                const container = frame.closest(".ans-attach-ct");
                if (container.querySelector(".ans-job-icon")) {
                    setTimeout(() => container.classList.add("ans-job-finished"), 100);
                }
            });
        </script>
    """
    )
    content_url = _data_url(content_html, "/mooc-ans/knowledge/cards?knowledgeid=100&num=1")
    # Include an unrelated same-URL video outside the current card.
    page_html = f"""
        <ul id="prev_tab"><li class="active">Video</li><li>Next</li></ul>
        <iframe src="{escape(video_url)}"></iframe>
        <iframe src="{escape(content_url)}"></iframe>
    """
    with PlaywrightBrowser(headless=True, timeout_ms=3_000) as browser:
        browser.open(_data_url(page_html, "/mycourse/studentstudy"))
        _wait_until_chaoxing_page_ready(browser)
        session = VideoSession()
        detector = ChaoxingTaskDetector(browser, video_session=session)
        handler = ChaoxingVideoTaskHandler(
            browser,
            video_session=session,
            config=ChaoxingVideoHandlerConfig(
                poll_interval_seconds=0.05,
                video_available_timeout_seconds=0.5,
                overall_timeout_seconds=5.0,
            ),
        )
        state = inspect_chaoxing_page(browser)
        assert [module.frame_path for module in state.modules] == [(1, 0), (1, 1)]
        assert len({video.frame_path for video in state.videos}) == 3
        assert detector.detect() is TaskType.VIDEO

        handler.run()

        state = inspect_chaoxing_page(browser)
        assert [video.ended for video in state.videos] == [False, True, False]
        assert state.modules[1].finished is False
        assert detector.detect() is TaskType.VIDEO

        handler.run()

        state = inspect_chaoxing_page(browser)
        assert [video.ended for video in state.videos] == [False, True, True]
        assert detector.detect() is TaskType.CONTENT


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
        <div class="posCatalog_select posCatalog_active" id="cur100">
            <span class="posCatalog_name">Knowledge 100</span>
        </div>
        <div class="posCatalog_select" id="cur200">
            <span class="posCatalog_name" onclick="
                document.getElementById('cur100').classList.remove('posCatalog_active');
                document.getElementById('cur200').classList.add('posCatalog_active');
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
