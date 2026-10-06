"""Real nested-frame regression coverage for the innerbook reader contract."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from linkforge.application.task_runner import TaskType
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.document_handler import ChaoxingDocumentTaskHandler
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import ChaoxingDocumentViewerReadyTimeoutError
from linkforge.platforms.chaoxing.innerbook import InnerbookSession
from linkforge.platforms.chaoxing.task_detector import ChaoxingTaskDetector
from linkforge.platforms.chaoxing.video_state import VideoSession


@contextmanager
def _course(*, unloaded: bool = False, preceding_video: bool = False):
    reader = """
        <style>body {margin:0} #Readweb {height:200px;overflow:auto}
        .duxiuimg {height:400px}</style>
        <div id="Readweb">
          <div class="duxiuimg"><div class="J_Msg" style="display:none"></div>
            <input type="image" class="Jimg" src="/dot.gif" style="height:400px;width:100px"></div>
          <div class="duxiuimg"><div class="J_Msg" style="display:none"></div>
            <input type="image" class="Jimg" src="/dot.gif" style="height:400px;width:100px"></div>
        </div>
        <script>
          const c = document.querySelector('#Readweb');
          function loadPages() {
            const cr = c.getBoundingClientRect();
            for (const row of c.children) {
              const r = row.getBoundingClientRect();
              if (r.bottom > cr.top && r.top < cr.bottom) {
                row.querySelector('input').src = '/page.svg';
              }
            }
          }
          c.addEventListener('scroll', loadPages);
          loadPages();
        </script>
    """
    if unloaded:
        reader = reader.replace("loadPages();", "/* leave placeholders unloaded */")
    documents = {
        "/study": (
            '<ul id="prev_tab"><li class="active">Card</li></ul>'
            '<iframe src="/mooc-ans/knowledge/cards" style="width:600px;height:600px"></iframe>'
        ),
        "/mooc-ans/knowledge/cards": "".join(
            '<div class="ans-attach-ct"><iframe src="/ananas/modules/innerbook/index.html" '
            'style="width:500px;height:250px"></iframe></div>'
            for _ in range(2)
        ),
        "/ananas/modules/innerbook/index.html": (
            '<iframe src="/n/readsvr/book/mooc/1/2/3.shtml" style="width:480px;height:230px"></iframe>'
        ),
        "/n/readsvr/book/mooc/1/2/3.shtml": reader,
        "/page.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="400">'
            '<rect width="100" height="400" fill="white"/></svg>'
        ),
        "/dot.gif": '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>',
    }
    if preceding_video:
        documents["/mooc-ans/knowledge/cards"] = (
            '<div class="ans-attach-ct"><iframe src="/ananas/modules/video/index.html"></iframe></div>'
            + documents["/mooc-ans/knowledge/cards"]
        )
        documents["/ananas/modules/video/index.html"] = "<video></video>"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            body = documents.get(path)
            self.send_response(200 if body is not None else 404)
            self.send_header(
                "Content-Type",
                "image/svg+xml" if path in {"/page.svg", "/dot.gif"} else "text/html; charset=utf-8",
            )
            self.end_headers()
            self.wfile.write((body or "").encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/study"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_two_identical_book_urls_scroll_independently_before_content() -> None:
    with _course() as url, PlaywrightBrowser(headless=True) as browser:
        browser.open(url)
        session = InnerbookSession()
        detector = ChaoxingTaskDetector(browser, innerbook_session=session)
        handler = ChaoxingDocumentTaskHandler(browser, innerbook_session=session)

        assert detector.detect() is TaskType.DOCUMENT
        handler.run()
        assert detector.detect() is TaskType.DOCUMENT
        handler.run()
        assert detector.detect() is TaskType.CONTENT


def test_unloaded_book_placeholders_cannot_complete() -> None:
    with _course(unloaded=True) as url, PlaywrightBrowser(headless=True) as browser:
        browser.open(url)
        session = InnerbookSession()
        handler = ChaoxingDocumentTaskHandler(
            browser,
            innerbook_session=session,
            viewer_ready_timeout_seconds=0.3,
        )
        with pytest.raises(ChaoxingDocumentViewerReadyTimeoutError):
            handler.run()
        assert ChaoxingTaskDetector(browser, innerbook_session=session).detect() is TaskType.DOCUMENT


def test_completed_ordinary_video_does_not_block_later_book_handler() -> None:
    with _course(preceding_video=True) as url, PlaywrightBrowser(headless=True) as browser:
        browser.open(url)
        video_session = VideoSession()
        # Seed the run-scoped evidence supplied by the already completed video handler.
        video_session.mark_handled(inspect_chaoxing_page(browser), 0)
        book_session = InnerbookSession()
        detector = ChaoxingTaskDetector(
            browser,
            video_session=video_session,
            innerbook_session=book_session,
        )
        handler = ChaoxingDocumentTaskHandler(
            browser,
            video_session=video_session,
            innerbook_session=book_session,
        )
        assert detector.detect() is TaskType.DOCUMENT
        handler.run()
        assert detector.detect() is TaskType.DOCUMENT
        handler.run()
        assert detector.detect() is TaskType.CONTENT
