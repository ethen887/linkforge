"""Offline cancellation, deadline, streaming and privacy tests using the real SDK parsers."""

import asyncio
import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest
from openai import APIStatusError

try:
    import httpx2 as httpx
except ImportError:
    import httpx

import linkforge.llm.anthropic as anthropic_module
import linkforge.llm.openai as openai_module
import linkforge.llm.request_runtime as runtime
from linkforge.llm.base import LLMImage, LLMMessage
from linkforge.llm.errors import ModelRequestCancelledError, ModelRequestError


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    monkeypatch.setattr(runtime, "POLL_INTERVAL_SECONDS", 0.005)
    monkeypatch.setattr(runtime, "PROGRESS_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(logging.getLogger("linkforge"), "propagate", True)


@pytest.mark.parametrize("streaming", [False, True])
def test_stop_cancels_pending_operation_and_joins_network_thread(streaming, caplog):
    stop = threading.Event()
    closed = threading.Event()

    async def operation(progress):
        try:
            if streaming:
                progress.chunk(content="PRIVATE-ANSWER", reasoning="PRIVATE-THINKING")
            await asyncio.sleep(30)
        finally:
            closed.set()

    timer = threading.Timer(0.05, stop.set)
    timer.start()
    started = time.monotonic()
    try:
        with caplog.at_level(logging.INFO), pytest.raises(ModelRequestCancelledError):
            runtime.run_request(
                operation,
                should_stop=stop.is_set,
                provider="test",
                model="PRIVATE-MODEL-KEY",
                messages=[LLMMessage("user", "PRIVATE-TEXT", images=(LLMImage(b"PRIVATE-IMAGE"),))],
            )
    finally:
        timer.join()
    assert closed.is_set()
    assert time.monotonic() - started < 1
    assert not any(t.name == "linkforge-model-request" for t in threading.enumerate())
    assert "已取消，连接已关闭" in caplog.text
    assert "PRIVATE-" not in caplog.text


def test_total_deadline_cancels_continuously_streaming_request(monkeypatch, caplog):
    monkeypatch.setattr(runtime, "REQUEST_TIMEOUT_SECONDS", 0.04)
    closed = threading.Event()

    async def operation(progress):
        try:
            while True:
                progress.chunk(content="PRIVATE")
                await asyncio.sleep(0.002)
        finally:
            closed.set()

    with caplog.at_level(logging.INFO), pytest.raises(ModelRequestError, match="响应超时"):
        runtime.run_request(
            operation, should_stop=lambda: False, provider="test", model="test", messages=[]
        )
    assert closed.is_set()
    assert "正在接收" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_stop_before_request_does_not_start_operation():
    async def operation(_progress):
        raise AssertionError("Must not send request after stop")

    with pytest.raises(ModelRequestCancelledError):
        runtime.run_request(operation, should_stop=lambda: True, provider="test", model="test", messages=[])


def test_stop_wins_when_response_arrives_at_the_same_time():
    stop = threading.Event()

    async def operation(_progress):
        stop.set()
        return "answer must not be used"

    with pytest.raises(ModelRequestCancelledError):
        runtime.run_request(operation, should_stop=stop.is_set, provider="test", model="test", messages=[])


@pytest.mark.parametrize("status,reason", [(402, "余额不足"), (429, "限流或额度不足"), (503, "HTTP 503")])
def test_errors_log_status_and_safe_reason_without_provider_body(status, reason, caplog):
    async def operation(_progress):
        request = httpx.Request("POST", "https://private.example/?key=PRIVATE-KEY")
        raise APIStatusError(
            "PRIVATE-ERROR", response=httpx.Response(status, request=request), body="PRIVATE-BODY"
        )

    with caplog.at_level(logging.INFO), pytest.raises(ModelRequestError, match=reason):
        runtime.run_request(
            operation, should_stop=lambda: False, provider="test", model="PRIVATE-MODEL", messages=[]
        )
    assert f"HTTP={status}" in caplog.text
    assert "PRIVATE" not in caplog.text


class EventBody(httpx.AsyncByteStream):
    def __init__(self, events, *, hang=False):
        self.events = events
        self.hang = hang
        self.closed = threading.Event()
        self.received = threading.Event()

    async def __aiter__(self):
        for event in self.events:
            yield event
        self.received.set()
        if self.hang:
            await asyncio.sleep(30)

    async def aclose(self):
        self.closed.set()


def openai_events():
    common = dict(id="PRIVATE-REQUEST-ID", created=1, model="private-model", object="chat.completion.chunk")
    chunks = [
        dict(choices=[dict(index=0, delta=dict(role="assistant", content=""), finish_reason=None)]),
        dict(choices=[dict(index=0, delta=dict(content='{"answer":"A"}'), finish_reason=None)]),
        dict(choices=[dict(index=0, delta={}, finish_reason="stop")]),
        dict(choices=[], usage=dict(prompt_tokens=15, completion_tokens=5, total_tokens=20)),
    ]
    return [f"data: {json.dumps(common | chunk)}\n\n".encode() for chunk in chunks] + [b"data: [DONE]\n\n"]


def anthropic_events():
    events = [
        (
            "message_start",
            dict(
                message=dict(
                    id="PRIVATE-REQUEST-ID",
                    type="message",
                    role="assistant",
                    model="private-model",
                    content=[],
                    stop_reason=None,
                    stop_sequence=None,
                    usage=dict(input_tokens=15, output_tokens=0),
                )
            ),
        ),
        ("content_block_start", dict(index=0, content_block=dict(type="text", text=""))),
        ("content_block_delta", dict(index=0, delta=dict(type="text_delta", text='{"answer":"A"}'))),
        ("content_block_stop", dict(index=0)),
        (
            "message_delta",
            dict(delta=dict(stop_reason="end_turn", stop_sequence=None), usage=dict(output_tokens=5)),
        ),
        ("message_stop", {}),
    ]
    return [
        f"event: {kind}\ndata: {json.dumps(dict(type=kind, **body))}\n\n".encode() for kind, body in events
    ]


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("hang", [False, True])
def test_real_sdk_streaming_and_cancellation_close_http_transport(provider, hang, monkeypatch, caplog):
    stop = threading.Event()
    events = openai_events() if provider == "openai" else anthropic_events()
    body = EventBody(events[:1] if hang else events, hang=hang)
    requests = []

    async def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=body)

    module = openai_module if provider == "openai" else anthropic_module
    sdk_name = "AsyncOpenAI" if provider == "openai" else "AsyncAnthropic"
    sdk_class = getattr(module, sdk_name)

    def make_client(**kwargs):
        return sdk_class(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))

    monkeypatch.setattr(module, sdk_name, make_client)
    adapter_class = module.OpenAIInterface if provider == "openai" else module.AnthropicInterface
    adapter = adapter_class(api_key="PRIVATE-KEY", base_url="https://models.example.test/v1")
    adapter.configure_runtime(should_stop=stop.is_set)

    def cancel_when_stream_received():
        if body.received.wait(2):
            stop.set()

    stopper = threading.Thread(target=cancel_when_stream_received) if hang else None
    if stopper:
        stopper.start()
    try:
        with caplog.at_level(logging.INFO):
            if hang:
                with pytest.raises(ModelRequestCancelledError):
                    adapter.call_json_model("test-model", [LLMMessage("user", "PRIVATE-QUESTION")])
            else:
                response = adapter.call_json_model("test-model", [LLMMessage("user", "PRIVATE-QUESTION")])
                assert response.content == '{"answer":"A"}'
                assert response.finish_reason in {"stop", "end_turn"}
    finally:
        adapter.close()
        if stopper:
            stopper.join()
    assert body.closed.is_set()
    assert len(requests) == 1
    assert requests[0]["stream"] is True
    assert "PRIVATE" not in caplog.text
    assert "收到首个数据块" in caplog.text
    if not hang:
        assert "15/5/0" in caplog.text


def test_progress_usage_handles_invalid_provider_values():
    progress = runtime.RequestProgress()
    progress.usage(SimpleNamespace(prompt_tokens="PRIVATE", completion_tokens=-1))
    assert progress.input_tokens == progress.output_tokens == 0
