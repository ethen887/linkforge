"""Quiz workflow behavior, using external-boundary fakes only."""

from types import SimpleNamespace

import pytest

from linkforge.application.task_runner import TaskRunner, TaskType
from linkforge.browser.exceptions import BrowserError
from linkforge.llm.base import LLMResponse, ToolCall
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingQuizAnswerError,
    ChaoxingQuizCaptureError,
    ChaoxingQuizCompletionError,
    ChaoxingQuizSolverError,
    ChaoxingQuizStateError,
    ChaoxingQuizSubmissionError,
)
from linkforge.platforms.chaoxing.quiz_dom import QuizDOMQuestion
from linkforge.platforms.chaoxing.quiz_handler import ChaoxingQuizHandlerConfig, ChaoxingQuizTaskHandler
from linkforge.platforms.chaoxing.quiz_models import QuizAnswer, QuizQuestionType
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver
from tests.fakes import FakeBrowser, FakeDOMElement

Q = QuizQuestionType
MODULE = "https://example.test/ananas/modules/work/index.html?id=1"


class Clock:
    now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_question(kind=Q.SINGLE_CHOICE, selected=(), *, count=4, initial_aria=True, name="q1", events=None):
    selected = set(selected)
    role = "checkbox" if kind is Q.MULTIPLE_CHOICE else "radio"
    state = {"selected": selected, "clicked": False, "inert": False, "images_ready": True}
    children = []

    def click(letter):
        if state["inert"]:
            return
        state["clicked"] = True
        if role == "checkbox":
            selected.symmetric_difference_update({letter})
        else:
            selected.clear()
            selected.add(letter)

    for index in range(count):
        letter = chr(65 + index)
        children.append(
            FakeDOMElement(
                inspect=lambda i=index, c=letter: {
                    "kind": role,
                    "index": i,
                    "count": count,
                    "aria": str(c in selected).lower() if initial_aria or state["clicked"] else None,
                    "checked": None,
                },
                on_click=lambda c=letter: click(c),
                name=f"{name}:{letter}",
                events=events,
            )
        )
    title = {Q.SINGLE_CHOICE: "单选题", Q.MULTIPLE_CHOICE: "多选题", Q.TRUE_FALSE: "判断题"}[kind]
    element = FakeDOMElement(
        inspect=lambda: {
            "title": title,
            "hidden_answers": ["".join(sorted(selected))] if role == "radio" else ["unknown-encoding"],
            "images_ready": state["images_ready"],
        },
        children=tuple(children),
        events=events,
        name=name,
    )
    return element, state


def make_handler(elements, answers, *, events=None, submitter=None):
    module = {"module_url": MODULE, "has_job_icon": True, "finished": False}
    frame = {
        "frame_url": "https://example.test/mooc-ans/knowledge/cards?knowledgeid=1",
        "active_tab_count": 1,
        "active_tab_index": 0,
        "has_next_tab": False,
        "modules": [module],
        "video_count": 0,
        "video": None,
    }
    browser = FakeBrowser(frame_evaluation_results=(frame,))
    browser.scoped_elements = tuple(elements)
    questions = []

    def solve(question):
        questions.append(question)
        if events is not None:
            events.append(f"solve:q{question.index + 1}")
        return answers[question.index]

    timer = Clock()
    handler = ChaoxingQuizTaskHandler(
        browser,
        solver=SimpleNamespace(solve=solve),
        submitter=submitter,
        config=ChaoxingQuizHandlerConfig(
            readiness_timeout_seconds=0.2,
            selection_timeout_seconds=0.2,
            completion_timeout_seconds=0.2,
            poll_interval_seconds=0.1,
        ),
        sleep=timer.sleep,
        monotonic=timer.monotonic,
    )
    return handler, browser, module, questions


@pytest.mark.parametrize("kind,count", [(Q.SINGLE_CHOICE, 4), (Q.TRUE_FALSE, 2)])
def test_initial_null_aria_uses_empty_hidden_and_switches_radio(kind, count):
    events = []
    element, state = make_question(kind, count=count, initial_aria=False, events=events)
    handler, browser, _, questions = make_handler([element], [QuizAnswer(kind, ("B",))])
    assert handler.answer_all() == (QuizAnswer(kind, ("B",)),)
    assert state["selected"] == {"B"}
    assert events == ["capture:q1", "click:q1:B"]
    assert questions[0].option_letters == tuple("ABCD"[:count])
    assert browser.scope_closed
    handler.answer_all()
    assert events.count("click:q1:B") == 1


def test_checkbox_reconciles_existing_answers_idempotently():
    events = []
    element, state = make_question(Q.MULTIPLE_CHOICE, ("A", "B"), events=events)
    handler, _, _, _ = make_handler([element], [QuizAnswer(Q.MULTIPLE_CHOICE, ("A", "C"))])
    handler.answer_all()
    handler.answer_all()
    assert state["selected"] == {"A", "C"}
    assert [e for e in events if e.startswith("click")] == ["click:q1:B", "click:q1:C"]


def test_questions_capture_solve_select_sequentially_and_mapping_is_local():
    events = []
    first, one = make_question(events=events)
    second, two = make_question(Q.TRUE_FALSE, count=2, name="q2", events=events)
    handler, _, _, _ = make_handler(
        [first, second],
        [QuizAnswer(Q.SINGLE_CHOICE, ("C",)), QuizAnswer(Q.TRUE_FALSE, ("A",))],
        events=events,
    )
    handler.answer_all()
    assert events == ["capture:q1", "solve:q1", "click:q1:C", "capture:q2", "solve:q2", "click:q2:A"]
    assert one["selected"] == {"C"}
    assert two["selected"] == {"A"}


def test_run_without_submitter_explicitly_stops_before_submission():
    element, _ = make_question()
    handler, browser, module, _ = make_handler([element], [QuizAnswer(Q.SINGLE_CHOICE, ("A",))])
    with pytest.raises(ChaoxingQuizSubmissionError, match="stopped before submission"):
        handler.run()
    assert handler.last_answers
    assert browser.scope_closed
    assert not module["finished"]


@pytest.mark.parametrize("failure", ["screenshot", "solver", "click", "inert", "images"])
def test_failure_propagation_and_scope_cleanup(failure):
    element, state = make_question()
    handler, browser, module, _ = make_handler([element], [QuizAnswer(Q.SINGLE_CHOICE, ("A",))])
    expected = ChaoxingQuizStateError
    if failure == "screenshot":
        element.screenshot_error = BrowserError("capture error")
        expected = ChaoxingQuizCaptureError
    elif failure == "solver":

        def fail(_question):
            raise RuntimeError("provider failed")

        handler._solver = SimpleNamespace(solve=fail)
        expected = ChaoxingQuizSolverError
    elif failure == "click":
        element.children[0].click_error = BrowserError("click error")
    elif failure == "images":
        state["images_ready"] = False
        expected = ChaoxingQuizCaptureError
    else:
        state["inert"] = True
    with pytest.raises(expected):
        handler.run()
    assert browser.scope_closed
    assert not module["finished"]


@pytest.mark.parametrize("failure", ["no_questions", "frame_missing", "wrong_task", "no_options"])
def test_preflight_failures_do_not_call_solver(failure):
    element, _ = make_question(count=0 if failure == "no_options" else 4)
    handler, browser, module, questions = make_handler([element], [])
    if failure == "no_questions":
        browser.scoped_elements = ()
    elif failure == "frame_missing":
        browser.scope_error = BrowserError("missing frame")
    elif failure == "wrong_task":
        module["module_url"] = "/ananas/modules/video/"
    with pytest.raises(ChaoxingQuizStateError):
        handler.answer_all()
    assert not questions
    assert browser.scope_closed


def test_invalid_custom_solver_answer_is_validated_before_click():
    events = []
    element, _ = make_question(events=events)
    handler, _, _, _ = make_handler([element], [QuizAnswer(Q.SINGLE_CHOICE, ("Z",))])
    with pytest.raises(ChaoxingQuizAnswerError, match="unknown option"):
        handler.answer_all()
    assert events == ["capture:q1"]


def test_multiple_existing_radio_answers_fail_before_click():
    element, _ = make_question(selected=("A", "B"))
    handler, _, _, _ = make_handler([element], [QuizAnswer(Q.SINGLE_CHOICE, ("A",))])
    with pytest.raises(ChaoxingQuizStateError, match="multiple selected"):
        handler.answer_all()


@pytest.mark.parametrize(
    "failure", ["aria_conflict", "hidden_conflict", "duplicate", "encoding", "mapping"]
)
def test_marker_contract_rejects_conflicting_or_malformed_selection(failure, caplog):
    element, _ = make_question(Q.MULTIPLE_CHOICE, count=2, initial_aria=False)
    states = [
        {
            "kind": "checkbox",
            "index": i,
            "count": 2,
            "aria": None,
            "checked": None,
            "marker_count": 1,
            "marker_checked": False,
            "marker_value": letter,
        }
        for i, letter in enumerate("AB")
    ]
    for node, state in zip(element.children, states):
        node.inspect = lambda state=state: state
    hidden = {"value": ""}
    element.inspect = lambda: {"title": "多选题", "hidden_answers": [hidden["value"]], "images_ready": True}
    dom = QuizDOMQuestion(element, 21)
    assert dom.selected(Q.MULTIPLE_CHOICE) == set()
    if failure == "aria_conflict":
        states[0]["aria"] = "true"
    elif failure == "hidden_conflict":
        hidden["value"] = "A"
    elif failure == "duplicate":
        states[0]["marker_count"] = 2
    elif failure == "encoding":
        hidden["value"] = "A,A"
    else:
        states[0]["marker_value"] = "B"
    with caplog.at_level("DEBUG"), pytest.raises(ChaoxingQuizStateError):
        dom.selected(Q.MULTIPLE_CHOICE)
    if failure in ("aria_conflict", "hidden_conflict"):
        assert "question_index=21" in caplog.text and "reason=conflicting" in caplog.text


def test_missing_checkbox_state_without_verified_markers_still_fails():
    element, _ = make_question(Q.MULTIPLE_CHOICE, initial_aria=False)
    dom = QuizDOMQuestion(element, 0)
    with pytest.raises(ChaoxingQuizStateError, match="missing or conflicting"):
        dom.selected(Q.MULTIPLE_CHOICE)


def test_later_question_missing_state_stops_before_any_model_call_or_click():
    events = []
    first, _ = make_question(events=events)
    second, _ = make_question(Q.MULTIPLE_CHOICE, initial_aria=False, name="q2", events=events)
    handler, _, _, questions = make_handler([first, second], [])
    with pytest.raises(ChaoxingQuizStateError, match="missing or conflicting"):
        handler.answer_all()
    assert not questions
    assert not events


@pytest.mark.parametrize("submit_behavior", ["complete", "timeout", "error"])
def test_handler_submission_and_completion_boundary(submit_behavior):
    element, _ = make_question()
    handler, browser, module, _ = make_handler([element], [QuizAnswer(Q.SINGLE_CHOICE, ("A",))])
    calls = []

    def submit(received, *, module_url):
        assert received is browser and module_url == MODULE
        calls.append("submit")
        if submit_behavior == "error":
            raise BrowserError("failed")
        if submit_behavior == "complete":
            module["finished"] = True  # Test-only platform response double.

    handler._submitter = SimpleNamespace(submit=submit)
    if submit_behavior == "complete":
        handler.run()
    else:
        expected = (
            ChaoxingQuizSubmissionError if submit_behavior == "error" else ChaoxingQuizCompletionError
        )
        with pytest.raises(expected):
            handler.run()
    assert calls == ["submit"]


def test_runner_dispatches_production_handler_and_does_not_loop_when_unsubmitted():
    element, _ = make_question()
    handler, _, _, _ = make_handler([element], [QuizAnswer(Q.SINGLE_CHOICE, ("A",))])
    runner = TaskRunner(
        detector=SimpleNamespace(detect=lambda: TaskType.QUIZ),
        quiz_handler=handler,
        video_handler=None,
        document_handler=None,
        content_handler=None,
        comment_handler=None,
    )
    with pytest.raises(ChaoxingQuizSubmissionError):
        runner.run()


@pytest.mark.parametrize(
    "response",
    [
        LLMResponse('{"question_type":"SINGLE_CHOICE","choices":["B"]}'),
        LLMResponse("invalid"),
        LLMResponse(tool_calls=[ToolCall("1", "click", {})]),
    ],
)
def test_vision_solver_uses_image_and_metadata_without_dom_text(response):
    calls = []

    def call_model(model, messages, tools):
        calls.append((model, messages, tools))
        return response

    element, _ = make_question()
    handler, _, _, _ = make_handler([element], [])
    handler._solver = LLMQuizSolver(llm=SimpleNamespace(call_model=call_model), model="vision-test")
    if response.content and response.content.startswith("{"):
        handler.answer_all()
    else:
        with pytest.raises(ChaoxingQuizAnswerError):
            handler.answer_all()
    assert len(calls) == 1
    model, messages, tools = calls[0]
    assert model == "vision-test" and tools == []
    assert messages[1].images[0].data == b"test-png"
    assert set(__import__("json").loads(messages[1].content)) == {"option_letters", "question_type_hint"}
