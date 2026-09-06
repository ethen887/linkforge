"""Focused tests for provider-neutral comment generation."""

from typing import Any

import pytest

from linkforge.llm.base import LLM, LLMMessage, LLMResponse
from linkforge.platforms.chaoxing.comment_handler import LLMCommentBodyGenerator
from linkforge.platforms.chaoxing.exceptions import ChaoxingCommentGenerationError


class _LLM(LLM):
    def __init__(self, response: str | None = "正文") -> None:
        self.response = response
        self.calls: list[tuple[str, list[LLMMessage], list[dict[str, Any]]]] = []

    def call_model(
        self, model: str, messages: list[LLMMessage], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        self.calls.append((model, messages, tools))
        return LLMResponse(content=self.response)


def test_llm_generator_sends_only_title_prompt_and_generation_requirements() -> None:
    llm = _LLM()
    generator = LLMCommentBodyGenerator(llm=llm, model="local-model", max_comment_chars=200)

    assert generator.generate(title="主题", prompt="教师问题") == "正文"

    model, messages, tools = llm.calls[0]
    assert model == "local-model"
    assert tools == []
    assert messages[1].content == "讨论标题：主题\n教师问题：教师问题"
    assert "学生回复" not in "".join(message.content or "" for message in messages)


def test_llm_generator_wraps_provider_failure() -> None:
    class FailingLLM(_LLM):
        def call_model(
            self, model: str, messages: list[LLMMessage], tools: list[dict[str, Any]]
        ) -> LLMResponse:
            raise RuntimeError("provider failed")

    with pytest.raises(ChaoxingCommentGenerationError):
        LLMCommentBodyGenerator(llm=FailingLLM(), model="local-model").generate(title="主题", prompt="问题")
