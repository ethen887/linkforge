"""通过本机 HTTP 连接验证 SSE 完成后的真实连接池与异步生成器清理。"""

import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from linkforge.llm.base import LLMMessage
from linkforge.llm.errors import ModelRequestCancelledError
from linkforge.llm.openai import OpenAIInterface
from tests.unit.test_model_request_runtime import openai_events


@pytest.mark.parametrize("cancel", [False, True])
def test_sse_requests_close_real_http_generators_without_asyncio_errors(caplog, cancel):
    payload = b"".join(openai_events())
    received = threading.Event()
    release = threading.Event()
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(openai_events()[0] if cancel else payload)
            self.wfile.flush()
            received.set()
            if cancel:
                release.wait(3)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever)
    serving.start()
    adapter = OpenAIInterface(api_key="local-test", base_url=f"http://127.0.0.1:{server.server_port}/v1")
    adapter.configure_runtime(should_stop=stop.is_set)

    def cancel_when_received():
        if received.wait(3):
            stop.set()

    stopper = threading.Thread(target=cancel_when_received) if cancel else None
    if stopper:
        stopper.start()
    try:
        with caplog.at_level(logging.ERROR, logger="asyncio"):
            if cancel:
                with pytest.raises(ModelRequestCancelledError):
                    adapter.call_json_model("local-test", [LLMMessage("user", "local question")])
            else:
                for _ in range(3):
                    result = adapter.call_json_model("local-test", [LLMMessage("user", "local question")])
                    assert result.content == '{"answer":"A"}'
    finally:
        release.set()
        if stopper:
            stopper.join()
        adapter.close()
        server.shutdown()
        serving.join()
        server.server_close()
    assert not [
        record for record in caplog.records if record.name == "asyncio" and record.levelno >= logging.ERROR
    ]
