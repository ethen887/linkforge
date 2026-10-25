"""大题数据格式、长度、模型输出及隐私边界。"""

import json

import pytest

from linkforge.llm.base import LLM, LLMImage, LLMResponse
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizAnswerError
from linkforge.platforms.chaoxing.written_answer import (
    LLMWrittenSolver,
    WrittenBlock,
    normalize_latex,
    parse_written_draft,
)


def test_parse_text_and_latex_preserves_order_and_literal_text():
    draft = parse_written_draft(
        json.dumps(
            {
                "blocks": [
                    {"kind": "text", "content": "<script>这是纯文本</script>"},
                    {"kind": "latex", "content": r"\frac{x_1^2}{2}=\int_0^1 x\,dx"},
                    {"kind": "text", "content": "所以结果为 0.5，单位为 m。"},
                ]
            }
        )
    )
    assert [block.kind for block in draft.blocks] == ["text", "latex", "text"]
    assert draft.blocks[0].content.startswith("<script>")


def test_overescaped_math_commands_are_decoded_without_destroying_aligned_rows():
    canonical = r"\lambda=632.8\,\text{nm}=632.8\times10^{-9}\,\text{m}"
    overescaped = canonical.replace("\\", "\\\\")
    draft = parse_written_draft(json.dumps({"blocks": [{"kind": "latex", "content": overescaped}]}))
    assert draft.blocks[0].content == canonical
    aligned = r"\begin{aligned}x&=1\\\lambda&=2\\[2pt] y&=\frac{1}{2}\end{aligned}"
    assert normalize_latex(aligned) == aligned
    assert normalize_latex(r"a\\ b\\ c") == r"a\\ b\\ c"
    assert normalize_latex(r"\\\\frac{1}{2}") == r"\frac{1}{2}"


@pytest.mark.parametrize("formula", ["lambda=2", "Deltax=1", "textnm", "times10^{-9}", "\text{nm}"])
def test_bare_commands_and_json_tab_escapes_are_not_accepted_as_renderable_math(formula):
    with pytest.raises(ChaoxingQuizAnswerError):
        parse_written_draft(json.dumps({"blocks": [{"kind": "latex", "content": formula}]}))


def test_command_names_are_allowed_inside_prose_arguments():
    formula = r"\text{lambda is a symbol}\quad x=\mathrm{lambda}"
    draft = parse_written_draft(json.dumps({"blocks": [{"kind": "latex", "content": formula}]}))
    assert draft.blocks[0].content == formula


@pytest.mark.parametrize("text", [r"结果 $x=1$", r"结果 $$x=1$$", r"由 \frac{L}{d} 得", r"数值 \(x=1\)"])
def test_text_blocks_cannot_hide_unrendered_formula_source(text):
    with pytest.raises(ChaoxingQuizAnswerError):
        WrittenBlock("text", text)


@pytest.mark.parametrize(
    "wrapped",
    [
        "$x=2$",
        "$$x=2$$",
        r"\(x=2\)",
        r"\[x=2\]",
        "```latex\nx=2\n```",
        "```tex\n$$x=2$$\n```",
        "```\nx=2\n```",
    ],
)
def test_latex_outer_delimiters_are_removed_locally(wrapped):
    draft = parse_written_draft(json.dumps({"blocks": [{"kind": "latex", "content": wrapped}]}))
    assert draft.blocks[0].content == "x=2"


def test_inline_math_is_split_without_model_repair_or_changes_to_the_answer():
    class Model(LLM):
        calls = 0

        def call_model(self, model, messages, tools):
            self.calls += 1
            assert self.calls == 1
            return LLMResponse(
                json.dumps(
                    {
                        "blocks": [
                            {
                                "kind": "text",
                                "content": r"解：由 $x=2$ 得，$$y=\frac{x}{2}=1$$，故结果为 1。",
                            }
                        ]
                    }
                )
            )

    model = Model()
    draft = LLMWrittenSolver(llm=model, model="test").solve(LLMImage(b"image"))
    assert [b.kind for b in draft.blocks] == ["text", "latex", "text", "latex", "text"]
    assert [b.content for b in draft.blocks if b.kind == "latex"] == ["x=2", r"y=\frac{x}{2}=1"]
    assert model.calls == 1


@pytest.mark.parametrize("text", ["未配对 $x=1", "$$", r"未配对 \(x=1", "先 $x$ 后 $"])
def test_unpaired_math_is_rejected_without_guessing_boundaries(text):
    with pytest.raises(ChaoxingQuizAnswerError):
        parse_written_draft(json.dumps({"blocks": [{"kind": "text", "content": text}]}))


def test_fenced_math_in_text_is_rendered_as_a_formula_without_evaluating_code():
    draft = parse_written_draft(
        json.dumps(
            {
                "blocks": [
                    {
                        "kind": "text",
                        "content": "由\n```latex\nx=2\n```\n得结果。",
                    }
                ]
            }
        )
    )
    assert [block.kind for block in draft.blocks] == ["text", "latex", "text"]
    assert draft.blocks[1].content == "x=2"
    with pytest.raises(ChaoxingQuizAnswerError):
        parse_written_draft(json.dumps({"blocks": [{"kind": "latex", "content": "$ $"}]}))


def test_existing_overescaped_formula_is_redone_even_if_ai_mistakenly_accepts_it():
    class Model(LLM):
        def call_model(self, model, messages, tools):
            return LLMResponse('{"rewrite":false}')

    assert LLMWrittenSolver(llm=Model(), model="test").needs_rewrite(
        LLMImage(b"image"), text="已有答案", formulas=(r"\\lambda=2",)
    )


@pytest.mark.parametrize(
    "content",
    [
        None,
        "PRIVATE-OUTPUT",
        '{"blocks":[],"extra":1}',
        '{"blocks":[],"blocks":[]}',
        '{"blocks":[{"kind":"html","content":"PRIVATE-OUTPUT"}]}',
        '{"blocks":[{"kind":"text","content":3}]}',
        '{"blocks":[{"kind":[],"content":"PRIVATE-OUTPUT"}]}',
        json.dumps({"blocks": [{"kind": "text", "content": "x" * 8001}]}),
        json.dumps({"blocks": [{"kind": "text", "content": "x"}] * 41}),
        json.dumps({"blocks": [{"kind": "latex", "content": r"\href{https://example.test}{x}"}]}),
    ],
)
def test_invalid_draft_does_not_echo_model_output(content):
    with pytest.raises(ChaoxingQuizAnswerError) as caught:
        parse_written_draft(content)
    assert "PRIVATE-OUTPUT" not in str(caught.value)


@pytest.mark.parametrize("reason", ["length", "max_tokens", "refusal", "tool_calls"])
def test_solver_rejects_incomplete_response(reason):
    class Model(LLM):
        def call_model(self, model, messages, tools):
            assert len(messages[-1].images) == 1
            return LLMResponse('{"blocks":[{"kind":"text","content":"result"}]}', finish_reason=reason)

    with pytest.raises(ChaoxingQuizAnswerError):
        LLMWrittenSolver(llm=Model(), model="test").solve(LLMImage(b"image"))


def test_solver_requests_complete_exam_answer_with_working_and_all_subquestions():
    class Model(LLM):
        def call_model(self, model, messages, tools):
            prompt = messages[0].content
            assert "正式考试答卷" in prompt
            assert "Complete ALL subquestions" in prompt
            assert "calculation steps, units" in prompt
            assert "Do not stop after setting up an equation" in prompt
            assert "Do not write a tutorial" in prompt
            assert "Split long derivations" in prompt
            assert messages[-1].content == "请按正式考试答卷格式完成这道题的所有小问。"
            return LLMResponse('{"blocks":[{"kind":"text","content":"解：（1）结果为 2 m。"}]}')

    draft = LLMWrittenSolver(llm=Model(), model="test").solve(LLMImage(b"image"))
    assert draft.blocks[0].content == "解：（1）结果为 2 m。"


@pytest.mark.parametrize("rewrite", [False, True])
def test_review_supplies_existing_text_and_formulas_and_requires_boolean(rewrite):
    class Model(LLM):
        def call_model(self, model, messages, tools):
            assert len(messages[-1].images) == 1
            assert json.loads(messages[-1].content) == {
                "existing_answer": {"text": "das", "formulas": ["x=0"]}
            }
            assert "do not solve the whole question" in messages[0].content
            return LLMResponse(json.dumps({"rewrite": rewrite}))

    assert (
        LLMWrittenSolver(llm=Model(), model="test").needs_rewrite(
            LLMImage(b"image"), text="das", formulas=("x=0",)
        )
        is rewrite
    )


@pytest.mark.parametrize(
    "content,reason",
    [
        ('{"rewrite":true}', "length"),
        ('{"rewrite":"true"}', "stop"),
        ('{"rewrite":1}', "stop"),
        ('{"rewrite":null}', "stop"),
        ('{"rewrite":true,"extra":1}', "stop"),
        ('{"rewrite":false,"rewrite":true}', "stop"),
        ('{"rewrite":NaN}', "stop"),
        ("PRIVATE-ANSWER", "stop"),
    ],
)
def test_invalid_review_does_not_authorize_deletion_or_echo_content(content, reason):
    class Model(LLM):
        def call_model(self, model, messages, tools):
            return LLMResponse(content, finish_reason=reason)

    with pytest.raises(ChaoxingQuizAnswerError) as caught:
        LLMWrittenSolver(llm=Model(), model="test").needs_rewrite(
            LLMImage(b"image"), text="PRIVATE-ANSWER", formulas=()
        )
    assert "PRIVATE-ANSWER" not in str(caught.value)


@pytest.mark.parametrize(
    "invalid",
    [
        '```json\n{"blocks":[{"kind":"text","content":"PRIVATE-ANSWER"}]}\n```',
        '{"blocks":[{"type":"text","content":"PRIVATE-ANSWER"}]}',
        json.dumps({"blocks": [{"kind": "text", "content": r"由 \frac{x}{2} 得 PRIVATE-ANSWER"}]}),
        '{"blocks":[{"kind":"latex","content":"\\frac{1}{2}"}]}',
    ],
)
def test_format_failure_gets_one_repair_without_resolving_or_logging_answer(invalid, caplog):
    class Model(LLM):
        calls = 0

        def call_model(self, model, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(invalid)
            assert self.calls == 2
            assert not messages[-1].images
            assert json.loads(messages[-1].content)["answer"] == invalid
            assert "do not solve the question again" in messages[0].content
            return LLMResponse('{"blocks":[{"kind":"text","content":"结果为 2 m。"}]}')

    model = Model()
    with caplog.at_level("INFO", logger="linkforge.platforms.chaoxing.written_answer"):
        draft = LLMWrittenSolver(llm=model, model="test").solve(LLMImage(b"image"))
    assert draft.blocks[0].content == "结果为 2 m。"
    assert model.calls == 2
    assert "格式修复成功" in caplog.text
    assert "PRIVATE-ANSWER" not in caplog.text


def test_failed_format_repair_is_not_retried_and_unsafe_formula_is_never_repaired():
    class Model(LLM):
        calls = 0

        def call_model(self, model, messages, tools):
            self.calls += 1
            return LLMResponse("PRIVATE-INVALID")

    model = Model()
    with pytest.raises(ChaoxingQuizAnswerError):
        LLMWrittenSolver(llm=model, model="test").solve(LLMImage(b"image"))
    assert model.calls == 2

    class Unsafe(Model):
        def call_model(self, model, messages, tools):
            self.calls += 1
            return LLMResponse(json.dumps({"blocks": [{"kind": "latex", "content": r"\input{x}"}]}))

    unsafe = Unsafe()
    with pytest.raises(ChaoxingQuizAnswerError):
        LLMWrittenSolver(llm=unsafe, model="test").solve(LLMImage(b"image"))
    assert unsafe.calls == 1
