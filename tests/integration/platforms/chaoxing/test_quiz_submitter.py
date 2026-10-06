"""Real browser coverage for delayed top-page Chaoxing confirmations."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizSubmissionError
from linkforge.platforms.chaoxing.quiz_submitter import ChaoxingQuizSubmitter


@contextmanager
def _quiz(*, warning=False, malformed=False):
    message = "You still have unfinished Single Choice, are you sure to submit?" if warning else "Submit?"
    top = """
    <iframe src="/ananas/modules/work/index.html" style="height:300px;width:600px"></iframe>
    <div id="workpop" style="display:none"><div class="popDiv">
      <p id="popcontent">MESSAGE</p><div class="popBottom">
        <a role="button" id="popok" onclick="window.confirmClicks++">Submit</a>
        <a role="button" id="popno">Cancel</a>
      </div></div></div>
    <script>
      window.submitClicks=0; window.confirmClicks=0;
      window.openConfirmation=()=>{
        window.submitClicks++;
        setTimeout(()=>document.querySelector('#workpop').style.display='block',150);
      };
    </script>
    """.replace("MESSAGE", message)
    if malformed:
        top = top.replace('id="popno"', 'id="unrelated"')
    documents = {
        "/study": top,
        "/ananas/modules/work/index.html": (
            '<iframe src="/mooc-ans/work/doHomeWorkNew" style="height:200px;width:500px"></iframe>'
        ),
        "/mooc-ans/work/doHomeWorkNew": (
            '<a role="button" class="btnSubmit workBtnIndex" onclick="top.openConfirmation()">Submit</a>'
        ),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = documents.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((body or "").encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("scenario", ["success", "unfinished", "malformed"])
def test_top_confirmation_is_bounded_scoped_and_never_submits_unfinished_quiz(scenario):
    with _quiz(warning=scenario == "unfinished", malformed=scenario == "malformed") as base:
        with PlaywrightBrowser(headless=True) as browser:
            browser.open(base + "/study")
            submitter = ChaoxingQuizSubmitter(confirmation_timeout_seconds=0.5)
            if scenario == "success":
                submitter.submit(browser, module_url=base + "/ananas/modules/work/index.html")
            else:
                with pytest.raises(
                    ChaoxingQuizSubmissionError,
                    match=("unfinished" if scenario == "unfinished" else "bounded wait"),
                ):
                    submitter.submit(browser, module_url=base + "/ananas/modules/work/index.html")
            assert {
                "submit": 1,
                "confirm": 1 if scenario == "success" else 0,
            } in browser.evaluate_in_frames(
                "() => ({submit:window.submitClicks, confirm:window.confirmClicks})"
            )
