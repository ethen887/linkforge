import logging
import traceback
from types import SimpleNamespace

import pytest

from linkforge.llm.base import LLMImage, LLMResponse, ToolCall
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizSolverError
from linkforge.platforms.chaoxing.quiz_models import QuizQuestion
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver, QuizResponseError, parse_answer

VALID = '{"question_type":"SINGLE_CHOICE","choices":["A"]}'
QUESTION = QuizQuestion(2, None, ("A", "B"), LLMImage(b"private-image"))


@pytest.mark.parametrize(
    "wrapper", ["{}", "  {}\n", "```json\n{}\n```", "```\n{}\n```", "```JSON\r\n{}\r\n```"]
)
def test_complete_json_and_fences(wrapper):
    assert parse_answer(wrapper.format(VALID), QUESTION).choices == ("A",)


@pytest.mark.parametrize(
    "content,reason",
    [
        (None, "empty_response"),
        ("  \n", "empty_response"),
        ("explanation " + VALID, "invalid_json"),
        (VALID + VALID, "invalid_json"),
        ("```json\n" + VALID + "\n```\nexplanation", "invalid_json"),
        ("```json\n" + VALID + "\n```\n```json\n{}\n```", "invalid_json"),
        ("```python\n" + VALID + "\n```", "invalid_json"),
        ('{"question_type":"SINGLE_CHOICE","choices":[NaN]}', "invalid_json"),
        ('{"question_type":"SINGLE_CHOICE","choices":["A"],"choices":["B"]}', "duplicate_keys"),
        ('{"question_type":"SINGLE_CHOICE","choices":"A"}', "invalid_structure"),
        ("[]", "invalid_structure"),
        ('{"question_type":"PRIVATE-TYPE","choices":[]}', "unsupported_type"),
        ('{"question_type":"SINGLE_CHOICE","choices":["PRIVATE-CHOICE"]}', "invalid_answer"),
    ],
)
def test_categorized_failures_do_not_expose_content(content, reason):
    with pytest.raises(QuizResponseError) as caught:
        parse_answer(content, QUESTION)
    assert caught.value.reason == reason
    assert "第 3 题" in str(caught.value)
    rendered = "".join(traceback.format_exception(caught.value))
    assert "PRIVATE-" not in rendered


@pytest.mark.parametrize(
    "finish,reason",
    [
        ("length", "truncated"),
        ("max_tokens", "truncated"),
        ("content_filter", "refused"),
        ("refusal", "refused"),
    ],
)
def test_incomplete_or_refused_response_rejected_even_if_json_valid(finish, reason):
    solver = LLMQuizSolver(
        llm=SimpleNamespace(call_json_model=lambda *args: LLMResponse(VALID, finish_reason=finish)),
        model="test",
    )
    with pytest.raises(QuizResponseError) as caught:
        solver.solve(QUESTION)
    assert caught.value.reason == reason


def test_diagnostics_only_record_safe_metadata_and_retry_once(caplog):
    calls = []

    def call(*args):
        calls.append(args)
        return LLMResponse("PRIVATE-CONTENT", finish_reason="PRIVATE-FINISH\ninjected")

    solver = LLMQuizSolver(llm=SimpleNamespace(call_json_model=call), model="PRIVATE-MODEL")
    with caplog.at_level(logging.INFO), pytest.raises(QuizResponseError):
        solver.solve(QUESTION)
    assert len(calls) == 2
    assert "question=3 attempt=1" in caplog.text
    assert "question=3 attempt=2" in caplog.text
    assert "elapsed_seconds=" in caplog.text
    assert "content_length=15 empty=False fenced=False finish_reason=unknown" in caplog.text
    assert "reason=invalid_json" in caplog.text
    assert "PRIVATE-" not in caplog.text
    assert "private-image" not in caplog.text
    assert len(calls[1][1]) == 3
    assert calls[1][1][0:2] == calls[0][1]
    assert "previous response was rejected" in calls[1][1][2].content


def test_retry_can_recover_with_valid_json():
    responses = iter([LLMResponse("not-json"), LLMResponse(VALID, finish_reason="stop")])
    solver = LLMQuizSolver(
        llm=SimpleNamespace(call_json_model=lambda *args: next(responses)),
        model="test",
    )
    assert solver.solve(QUESTION).choices == ("A",)


def test_sdk_exception_body_is_not_in_traceback_or_logs(caplog):
    def call(*args):
        raise RuntimeError("PRIVATE-API-KEY PRIVATE-REQUEST")

    solver = LLMQuizSolver(llm=SimpleNamespace(call_json_model=call), model="test")
    with pytest.raises(ChaoxingQuizSolverError) as caught:
        solver.solve(QUESTION)
    assert "模型调用失败" in str(caught.value)
    assert "检查网络、API Key、接口地址和模型名称" in str(caught.value)
    assert "PRIVATE-" not in "".join(traceback.format_exception(caught.value))
    assert "PRIVATE-" not in caplog.text


def test_tool_calls_rejected():
    solver = LLMQuizSolver(
        llm=SimpleNamespace(call_json_model=lambda *args: LLMResponse(VALID, [ToolCall("1", "click", {})])),
        model="test",
    )
    with pytest.raises(QuizResponseError, match="tool_calls"):
        solver.solve(QUESTION)
