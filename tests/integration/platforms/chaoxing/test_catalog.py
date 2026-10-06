"""Verify completed-node navigation through real nested browser DOM."""

import json
from html import escape
from urllib.parse import quote

import pytest

from linkforge.application.task_runner import TaskHandler, TaskRunner, TaskType
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.content_handler import ChaoxingContentTaskHandler
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ContentNavigationError
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector


def _page(marker: str = '<span class="icon_Completed prevTips"></span>') -> str:
    urls = []
    for node_id, kind in ((100, "unsupported"), (200, "unsupported"), (300, "work")):
        html = f'<iframe src="/ananas/modules/{kind}/"></iframe>'
        urls.append(
            f"data:text/html,{quote(html, safe='')}#/mooc-ans/knowledge/cards?knowledgeid={node_id}"
        )
    html = f"""
        <ul id="prev_tab"><li class="active">Current card</li><li>Remaining card</li></ul>
        <section>
            <div id="cur100" class="posCatalog_select posCatalog_active">
                <span class="posCatalog_name" onclick="navigate(0)">Completed</span>{marker}
            </div>
        </section>
        <section>
            <div id="cur200" class="posCatalog_select">
                <span class="posCatalog_name" onclick="navigate(1)">Completed in next chapter</span>
                <span class="icon_Completed prevTips"></span>
            </div>
            <div id="cur300" class="posCatalog_select">
                <span class="posCatalog_name" onclick="navigate(2)">Pending quiz</span>
                <span class="catalog_points_yi prevTips"><span class="orangeNew">0</span></span>
            </div>
        </section>
        <iframe id="card" src="{escape(urls[0], quote=True)}"></iframe>
        <script>
            const urls = {json.dumps(urls)};
            function navigate(index) {{
                document.querySelectorAll('.posCatalog_select').forEach(node =>
                    node.classList.remove('posCatalog_active'));
                document.getElementById('cur' + [100,200,300][index]).classList.add('posCatalog_active');
                document.getElementById('card').src = urls[index];
            }}
        </script>
    """
    return f"data:text/html,{quote(html, safe='')}#/mycourse/studentstudy"


def test_consecutive_completed_nodes_across_chapters_resume_at_pending_quiz() -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=3000) as browser:
        browser.open(_page())
        detector = ChaoxingTaskDetector(browser)
        handler = ChaoxingContentTaskHandler(browser, detector=detector)
        assert detector.detect() is TaskType.CONTENT
        handler.run()
        assert inspect_chaoxing_page(browser).knowledge_id == "200"
        assert detector.detect() is TaskType.CONTENT
        handler.run()
        assert inspect_chaoxing_page(browser).knowledge_id == "300"
        assert detector.detect() is TaskType.QUIZ
        with pytest.raises(ContentNavigationError, match="pending"):
            handler.run()
        assert inspect_chaoxing_page(browser).knowledge_id == "300"


@pytest.mark.parametrize(
    "marker",
    [
        "",
        '<span class="icon_Completed" style="display:none"></span>',
        '<span class="catalog_points_yi"><span class="orangeNew">0</span></span>',
        '<span class="icon_Completed"></span><span class="catalog_points_yi"></span>',
    ],
)
def test_missing_or_conflicting_check_does_not_skip_unknown_module(marker: str) -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=3000) as browser:
        browser.open(_page(marker))
        assert ChaoxingTaskDetector(browser).detect() is TaskType.UNKNOWN


def test_completion_removed_at_click_prevents_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    with PlaywrightBrowser(headless=True, timeout_ms=3000) as browser:
        browser.open(_page())
        handler = ChaoxingContentTaskHandler(browser)
        original = handler._click_next_knowledge

        def remove_marker_then_click(*args: object) -> None:
            browser.evaluate_in_frames(
                "() => { document.querySelector('#cur100 > .icon_Completed')?.remove(); return null; }"
            )
            original(*args)

        monkeypatch.setattr(handler, "_click_next_knowledge", remove_marker_then_click)
        with pytest.raises(ContentNavigationError, match="knowledge-tree-changed"):
            handler.run()
        assert inspect_chaoxing_page(browser).knowledge_id == "100"


def test_runner_dispatches_only_first_pending_quiz_after_completed_nodes() -> None:
    class ProbeHandler(TaskHandler):
        def __init__(self) -> None:
            self.calls = 0

        def run(self) -> None:
            self.calls += 1

    with PlaywrightBrowser(headless=True, timeout_ms=3000) as browser:
        browser.open(_page())
        detector = ChaoxingTaskDetector(browser)
        quiz = ProbeHandler()
        unused = ProbeHandler()
        runner = TaskRunner(
            detector=detector,
            video_handler=unused,
            document_handler=unused,
            comment_handler=unused,
            quiz_handler=quiz,
            content_handler=ChaoxingContentTaskHandler(browser, detector=detector),
        )
        runner.run(should_stop=lambda: quiz.calls == 1 or unused.calls > 0)
        assert quiz.calls == 1
        assert unused.calls == 0
        assert inspect_chaoxing_page(browser).knowledge_id == "300"
