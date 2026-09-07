"""Validated V1 question and answer contracts; DOM text is never solver input."""

import re
from dataclasses import dataclass
from enum import Enum
from string import ascii_uppercase

from linkforge.llm.base import LLMImage
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizAnswerError, ChaoxingQuizStateError


class QuizQuestionType(Enum):
    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"


def option_letters(count: int) -> tuple[str, ...]:
    if not 1 <= count <= 26:
        raise ChaoxingQuizStateError(f"Question must have 1 to 26 options; received {count}.")
    return tuple(ascii_uppercase[:count])


def parse_question_type(title: str, roles: tuple[str, ...]) -> QuizQuestionType | None:
    """Read only the heading's type prefix, never classify from question semantics.

    Radio semantics cannot distinguish single-choice from true/false, so without
    a legible heading they remain unknown for Vision to disambiguate.
    """
    match = re.match(
        r"^\s*(?:\d+\s*[.．、]\s*)?[（(【\[]?\s*"
        r"(单选题|多选题|判断题|填空题|简答题|论述题|计算题|匹配题|排序题|名词解释)"
        r"(?=$|[\s,，:：)）】\]])",
        title,
    )
    labels = {
        "单选题": QuizQuestionType.SINGLE_CHOICE,
        "多选题": QuizQuestionType.MULTIPLE_CHOICE,
        "判断题": QuizQuestionType.TRUE_FALSE,
    }
    hint = None
    if match:
        label = match[1]
        if label not in labels:
            raise ChaoxingQuizAnswerError(f"Unsupported question type: {label}.")
        hint = labels[label]
    kinds = set(roles)
    if not kinds <= {"radio", "checkbox"} or len(kinds) > 1:
        raise ChaoxingQuizStateError("Question options have unsupported or mixed control semantics.")
    if kinds == {"checkbox"}:
        if hint is not None and hint is not QuizQuestionType.MULTIPLE_CHOICE:
            raise ChaoxingQuizAnswerError("DOM heading conflicts with checkbox semantics.")
        return QuizQuestionType.MULTIPLE_CHOICE
    if kinds == {"radio"} and hint is QuizQuestionType.MULTIPLE_CHOICE:
        raise ChaoxingQuizAnswerError("DOM heading conflicts with radio semantics.")
    return hint


@dataclass(frozen=True, slots=True)
class QuizQuestion:
    index: int
    question_type: QuizQuestionType | None
    option_letters: tuple[str, ...]
    image: LLMImage


@dataclass(frozen=True, slots=True)
class QuizAnswer:
    question_type: QuizQuestionType
    choices: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.question_type, QuizQuestionType):
            raise ChaoxingQuizAnswerError("Unsupported answer question_type.")
        if not isinstance(self.choices, tuple) or not self.choices:
            raise ChaoxingQuizAnswerError("Answer choices must be a non-empty tuple.")
        if any(not isinstance(c, str) or len(c) != 1 or c not in ascii_uppercase for c in self.choices):
            raise ChaoxingQuizAnswerError("Choices must be uppercase option letters.")
        if len(set(self.choices)) != len(self.choices):
            raise ChaoxingQuizAnswerError("Answer contains duplicate options.")
        if self.question_type is not QuizQuestionType.MULTIPLE_CHOICE and len(self.choices) != 1:
            raise ChaoxingQuizAnswerError("Single-choice and true/false require exactly one choice.")


def validate_answer(question: QuizQuestion, answer: QuizAnswer) -> QuizAnswer:
    if not isinstance(answer, QuizAnswer):
        raise ChaoxingQuizAnswerError("Solver did not return a QuizAnswer.")
    if question.question_type is not None and question.question_type is not answer.question_type:
        raise ChaoxingQuizAnswerError("DOM and AI question types conflict.")
    if not set(answer.choices) <= set(question.option_letters):
        raise ChaoxingQuizAnswerError("Answer contains an unknown option letter.")
    if answer.question_type is QuizQuestionType.TRUE_FALSE and question.option_letters != ("A", "B"):
        raise ChaoxingQuizAnswerError("True/false requires exactly the page options A and B.")
    return answer
