import json

import pytest

from linkforge.llm.base import LLMImage
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizAnswerError, ChaoxingQuizStateError
from linkforge.platforms.chaoxing.quiz_models import (
    QuizQuestion,
    QuizQuestionType,
    option_letters,
    parse_question_type,
)
from linkforge.platforms.chaoxing.quiz_solver import parse_answer

Q = QuizQuestionType


@pytest.mark.parametrize(
    "title,roles,expected",
    [
        ("1. (单选题, 20分) 题干", ("radio",) * 4, Q.SINGLE_CHOICE),
        ("（多选题）", ("checkbox",) * 4, Q.MULTIPLE_CHOICE),
        ("判断题", ("radio",) * 2, Q.TRUE_FALSE),
        ("乱码", ("checkbox",) * 3, Q.MULTIPLE_CHOICE),
        ("乱码", ("radio",) * 2, None),
        ("题干中提到单选题", ("radio",) * 4, None),
    ],
)
def test_type_parsing(title, roles, expected):
    assert parse_question_type(title, roles) is expected


@pytest.mark.parametrize(
    "title,roles",
    [
        ("填空题", ("radio",)),
        ("简答题", ("radio",)),
        ("单选题", ("checkbox",)),
        ("多选题", ("radio",)),
    ],
)
def test_unsupported_or_conflicting_dom_type(title, roles):
    with pytest.raises(ChaoxingQuizAnswerError):
        parse_question_type(title, roles)


def test_mixed_options_rejected():
    with pytest.raises(ChaoxingQuizStateError):
        parse_question_type("", ("checkbox", "radio"))


@pytest.mark.parametrize(
    "kind,choices",
    [
        (Q.SINGLE_CHOICE, ["B"]),
        (Q.TRUE_FALSE, ["A"]),
        (Q.MULTIPLE_CHOICE, ["A", "C"]),
    ],
)
def test_valid_answers(kind, choices):
    letters = ("A", "B") if kind is Q.TRUE_FALSE else option_letters(4)
    question = QuizQuestion(0, kind, letters, LLMImage(b"png"))
    answer = parse_answer(json.dumps({"question_type": kind.value, "choices": choices}), question)
    assert answer.choices == tuple(choices)
    assert answer.question_type is kind


@pytest.mark.parametrize(
    "kind,choices",
    [
        ("SINGLE_CHOICE", []),
        ("SINGLE_CHOICE", ["A", "B"]),
        ("TRUE_FALSE", ["A", "B"]),
        ("MULTIPLE_CHOICE", []),
        ("MULTIPLE_CHOICE", ["A", "A"]),
        ("MULTIPLE_CHOICE", ["Z"]),
        ("SINGLE_CHOICE", ["a"]),
        ("SINGLE_CHOICE", "A"),
        ("SINGLE_CHOICE", [1]),
        ("SINGLE_CHOICE", [True]),
        ("SINGLE_CHOICE", [["A"]]),
        ("UNSUPPORTED", []),
    ],
)
def test_invalid_model_answers(kind, choices):
    question = QuizQuestion(0, None, option_letters(4), LLMImage(b"png"))
    with pytest.raises(ChaoxingQuizAnswerError):
        parse_answer(json.dumps({"question_type": kind, "choices": choices}), question)


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "```json\n{}\n```",
        "[]",
        "{}",
        '{"question_type":"SINGLE_CHOICE","choices":["A"],"reason":"x"}',
        '{"question_type":"SINGLE_CHOICE","choices":["A"],"choices":["B"]}',
    ],
)
def test_invalid_json_structure(content):
    with pytest.raises(ChaoxingQuizAnswerError):
        parse_answer(content, QuizQuestion(0, None, ("A", "B"), LLMImage(b"png")))


def test_dom_ai_conflict():
    with pytest.raises(ChaoxingQuizAnswerError, match="conflict"):
        parse_answer(
            '{"question_type":"MULTIPLE_CHOICE","choices":["A"]}',
            QuizQuestion(0, Q.SINGLE_CHOICE, ("A", "B"), LLMImage(b"png")),
        )


def test_unknown_dom_allows_vision_type():
    answer = parse_answer(
        '{"question_type":"TRUE_FALSE","choices":["B"]}',
        QuizQuestion(0, None, ("A", "B"), LLMImage(b"png")),
    )
    assert answer.question_type is Q.TRUE_FALSE


def test_letter_mapping():
    assert option_letters(4) == ("A", "B", "C", "D")
    for count in (0, 27):
        with pytest.raises(ChaoxingQuizStateError):
            option_letters(count)
