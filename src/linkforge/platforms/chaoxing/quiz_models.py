"""校验过的 V1 题目与答案契约；DOM 文本永不作为解题器输入。"""

import re
from dataclasses import dataclass
from enum import Enum
from string import ascii_uppercase

from linkforge.llm.base import LLMImage
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizAnswerError, ChaoxingQuizStateError


class QuizQuestionType(Enum):
    """支持的题型：单选、多选、判断题。"""

    SINGLE_CHOICE = "SINGLE_CHOICE"
    MULTIPLE_CHOICE = "MULTIPLE_CHOICE"
    TRUE_FALSE = "TRUE_FALSE"


def option_letters(count: int) -> tuple[str, ...]:
    """为 count 个选项返回按序的 A-Z 大写字母元组；count 须在 1 到 26 之间。"""
    if not 1 <= count <= 26:
        raise ChaoxingQuizStateError(f"Question must have 1 to 26 options; received {count}.")
    return tuple(ascii_uppercase[:count])


def parse_question_type(title: str, roles: tuple[str, ...]) -> QuizQuestionType | None:
    """只读取标题的题型前缀，绝不由题目语义推断题型。

    单选（radio）语义无法区分单选题与判断题，因此若没有可读的标题，
    就保持未知，交由 Vision 来区分。
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
    """一道已捕获的题目：索引、题型提示、选项字母与题目截图。"""

    index: int
    question_type: QuizQuestionType | None
    option_letters: tuple[str, ...]
    image: LLMImage


@dataclass(frozen=True, slots=True)
class QuizAnswer:
    """一道题的答案：题型与选中选项的大写字母元组。"""

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
    """校验答案与题目的题型、选项一致性，通过则返回该答案。"""
    if not isinstance(answer, QuizAnswer):
        raise ChaoxingQuizAnswerError("Solver did not return a QuizAnswer.")
    if question.question_type is not None and question.question_type is not answer.question_type:
        raise ChaoxingQuizAnswerError("DOM and AI question types conflict.")
    if not set(answer.choices) <= set(question.option_letters):
        raise ChaoxingQuizAnswerError("Answer contains an unknown option letter.")
    if answer.question_type is QuizQuestionType.TRUE_FALSE and question.option_letters != ("A", "B"):
        raise ChaoxingQuizAnswerError("True/false requires exactly the page options A and B.")
    return answer
