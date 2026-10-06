"""Unit tests for the Chaoxing platform composition root."""

import inspect
from collections.abc import Sequence
from dataclasses import dataclass

import linkforge.platforms.chaoxing.runtime as runtime_module
from linkforge.application.task_runner import TaskRunner, TaskType
from linkforge.browser.base import Browser
from linkforge.llm.base import LLM, LLMMessage, LLMResponse
from linkforge.platforms.chaoxing.comment_state import CommentSession
from linkforge.platforms.chaoxing.innerbook import InnerbookSession
from linkforge.platforms.chaoxing.runtime import ChaoxingPlatformRuntime
from linkforge.platforms.chaoxing.video_state import VideoSession
from tests.fakes import FakeBrowser


class RecordingBrowser(FakeBrowser):
    def __init__(self) -> None:
        super().__init__()
        self.lifecycle_calls: list[str] = []

    def start(self) -> None:
        self.lifecycle_calls.append("start")

    def open(self, url: str) -> None:
        self.lifecycle_calls.append(f"open:{url}")
        super().open(url)

    def close(self) -> None:
        self.lifecycle_calls.append("close")
        super().close()


class FakeLLM(LLM):
    def __init__(self) -> None:
        self.calls = 0

    def call_model(
        self,
        model: str,
        messages: list[LLMMessage],
        tools: list[dict],
    ) -> LLMResponse:
        self.calls += 1
        raise AssertionError("Composition must not call the LLM.")


class FakeQuizSubmitter:
    def submit(self, browser: Browser, *, module_url: str) -> None:
        raise AssertionError("Composition must not submit a quiz.")


class ScriptedDetector:
    def __init__(self, tasks: Sequence[TaskType]) -> None:
        self._tasks = iter(tasks)

    def detect(self) -> TaskType:
        return next(self._tasks)


class RecordingHandler:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events

    def run(self) -> None:
        self._events.append(self._name)


@dataclass
class BuildRecord:
    browser: Browser
    session: CommentSession
    detector: ScriptedDetector
    video_session: VideoSession
    innerbook_session: InnerbookSession
    quiz_solver: object | None = None
    comment_generator: object | None = None


def test_build_runner_composes_shared_run_scoped_dependencies(monkeypatch) -> None:
    browser = RecordingBrowser()
    llm = FakeLLM()
    submitter = FakeQuizSubmitter()
    handler_events: list[str] = []
    records: list[BuildRecord] = []
    handler_dependencies: list[tuple[str, Browser, object | None, object | None]] = []
    solver_calls: list[tuple[LLM, str]] = []
    generator_calls: list[tuple[LLM, str]] = []

    def create_detector(
        received_browser: Browser,
        *,
        comment_session: CommentSession,
        video_session: VideoSession,
        innerbook_session: InnerbookSession,
    ) -> ScriptedDetector:
        detector = ScriptedDetector(
            [
                TaskType.VIDEO,
                TaskType.DOCUMENT,
                TaskType.CONTENT,
                TaskType.QUIZ,
                TaskType.COMMENT,
                TaskType.COMPLETE,
            ]
        )
        records.append(
            BuildRecord(received_browser, comment_session, detector, video_session, innerbook_session)
        )
        return detector

    def create_quiz_solver(*, llm: LLM, model: str) -> object:
        solver_calls.append((llm, model))
        solver = object()
        records[-1].quiz_solver = solver
        return solver

    def create_comment_generator(*, llm: LLM, model: str) -> object:
        generator_calls.append((llm, model))
        generator = object()
        records[-1].comment_generator = generator
        return generator

    def create_handler(name: str):
        def factory(
            received_browser: Browser,
            *,
            detector: object | None = None,
            solver: object | None = None,
            submitter: object | None = None,
            comment_session: object | None = None,
            body_generator: object | None = None,
            video_session: VideoSession | None = None,
            innerbook_session: InnerbookSession | None = None,
        ) -> RecordingHandler:
            if name == "video":
                dependency = video_session
            elif name == "document":
                dependency = (innerbook_session, video_session)
            elif name == "content":
                dependency = detector
            elif name == "quiz":
                dependency = (detector, solver, submitter)
            else:
                dependency = (detector, comment_session, body_generator)
            handler_dependencies.append((name, received_browser, dependency, records[-1].detector))
            return RecordingHandler(name, handler_events)

        return factory

    monkeypatch.setattr(runtime_module, "ChaoxingTaskDetector", create_detector)
    monkeypatch.setattr(runtime_module, "LLMQuizSolver", create_quiz_solver)
    monkeypatch.setattr(runtime_module, "LLMCommentBodyGenerator", create_comment_generator)
    monkeypatch.setattr(runtime_module, "ChaoxingVideoTaskHandler", create_handler("video"))
    monkeypatch.setattr(runtime_module, "ChaoxingDocumentTaskHandler", create_handler("document"))
    monkeypatch.setattr(runtime_module, "ChaoxingContentTaskHandler", create_handler("content"))
    monkeypatch.setattr(runtime_module, "ChaoxingQuizTaskHandler", create_handler("quiz"))
    monkeypatch.setattr(runtime_module, "ChaoxingCommentTaskHandler", create_handler("comment"))

    runtime = ChaoxingPlatformRuntime(quiz_submitter=submitter)
    first_runner = runtime.build_runner(browser=browser, llm=llm, model="vision-model")
    second_runner = runtime.build_runner(browser=browser, llm=llm, model="vision-model")

    assert isinstance(first_runner, TaskRunner)
    assert isinstance(second_runner, TaskRunner)
    assert len(records) == 2
    assert records[0].session is not records[1].session
    assert records[0].video_session is not records[1].video_session
    assert records[0].innerbook_session is not records[1].innerbook_session
    assert all(record.browser is browser for record in records)
    assert solver_calls == [(llm, "vision-model"), (llm, "vision-model")]
    assert generator_calls == [(llm, "vision-model"), (llm, "vision-model")]

    first_dependencies = handler_dependencies[:5]
    assert [name for name, _, _, _ in first_dependencies] == [
        "video",
        "document",
        "content",
        "quiz",
        "comment",
    ]
    assert all(received_browser is browser for _, received_browser, _, _ in first_dependencies)
    assert first_dependencies[0][2] is records[0].video_session
    assert first_dependencies[1][2] == (records[0].innerbook_session, records[0].video_session)
    assert handler_dependencies[6][2] == (records[1].innerbook_session, records[1].video_session)
    assert handler_dependencies[5][2] is records[1].video_session
    assert first_dependencies[2][2] is records[0].detector
    assert first_dependencies[3][2] == (
        records[0].detector,
        records[0].quiz_solver,
        submitter,
    )
    assert first_dependencies[4][2] == (
        records[0].detector,
        records[0].session,
        records[0].comment_generator,
    )

    first_runner.run()

    assert handler_events == ["video", "document", "content", "quiz", "comment"]
    assert browser.lifecycle_calls == []
    assert llm.calls == 0


def test_runtime_source_does_not_depend_on_smoke() -> None:
    source = inspect.getsource(runtime_module)

    assert "smoke_quiz" not in source
    assert "SmokeQuizSubmitter" not in source
