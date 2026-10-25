"""审核契约、真实输入范围与拒绝误通过；不访问课程或模型服务。"""

import json

import pytest

from linkforge.llm.base import LLM, LLMImage, LLMResponse
from linkforge.llm.errors import ModelRequestCancelledError
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizAnswerError
from linkforge.platforms.chaoxing.written_review import LLMWrittenReviewer, parse_written_audit


@pytest.mark.parametrize(
    "content",
    [
        None,
        "PRIVATE-FEEDBACK",
        '{"passed":"true","issues":[]}',
        '{"passed":false,"issues":[]}',
        '{"passed":true,"issues":[],"extra":1}',
        '{"passed":true,"passed":false,"issues":[]}',
        '{"passed":false,"issues":[{"code":"unknown","detail":"PRIVATE-FEEDBACK"}]}',
        '{"passed":false,"issues":[{"code":"rendering","detail":""}]}',
        json.dumps({"passed": False, "issues": [{"code": "rendering", "detail": "x" * 501}]}),
    ],
)
def test_invalid_audit_never_counts_as_passed_or_echoes_feedback(content):
    with pytest.raises(ChaoxingQuizAnswerError) as caught:
        parse_written_audit(content)
    assert "PRIVATE-FEEDBACK" not in str(caught.value)


@pytest.mark.parametrize(
    "text,code",
    [
        (r"结果为 $x=\frac{1}{2}$。", "raw_latex"),
        ("题目中该数值被遮挡，按常见取值计算。", "unsupported_assumption"),
    ],
)
def test_structured_answer_and_images_are_reviewed_and_obvious_defects_cannot_pass(text, code):
    class Model(LLM):
        def call_model(self, model, messages, tools):
            assert len(messages[-1].images) == 2
            data = json.loads(messages[-1].content)["audit_answer"]
            assert data["question_text"] == "已知 L=2.0 m"
            assert data["text"] == text
            assert data["formulas"] == [r"\lambda=1"]
            return LLMResponse('{"passed":true,"issues":[]}')

    result = LLMWrittenReviewer(llm=Model(), model="test").audit(
        (LLMImage(b"question"), LLMImage(b"answer")),
        question_text="已知 L=2.0 m",
        text=text,
        formulas=(r"\lambda=1",),
    )
    assert not result.passed
    assert result.issues[0].code == code


def test_audit_stop_propagates_without_overwrite_authorization():
    class Model(LLM):
        def call_model(self, model, messages, tools):
            raise ModelRequestCancelledError

    with pytest.raises(ModelRequestCancelledError):
        LLMWrittenReviewer(llm=Model(), model="test").audit(
            (LLMImage(b"question"), LLMImage(b"answer")),
            question_text="question",
            text="answer",
            formulas=(),
        )
