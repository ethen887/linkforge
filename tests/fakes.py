"""Test doubles for external LinkForge interfaces."""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager

from linkforge.action.base import ActionExecutor
from linkforge.action.models import Action
from linkforge.agent.browser import BrowserAgent
from linkforge.agent.models import BrowserDecision
from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserElementError, BrowserError
from linkforge.browser.models import BrowserPage, InteractiveElement
from linkforge.observation.base import Observer
from linkforge.observation.models import Observation


class ManualClock:
    """Advance a deterministic monotonic clock when a test requests sleep."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeCredentialStore:
    """Keep explicitly fake credentials in memory, never in the OS store."""

    def __init__(self) -> None:
        self._passwords: dict[tuple[str, str], str] = {}
        self.get_calls: list[tuple[str, str]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.read_error: Exception | None = None
        self.write_error: Exception | None = None

    def get_password(self, service: str, username: str) -> str | None:
        self.get_calls.append((service, username))
        if self.read_error is not None:
            raise self.read_error
        return self._passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.set_calls.append((service, username))
        if self.write_error is not None:
            raise self.write_error
        self._passwords[(service, username)] = password


class FakeObserver(Observer):
    """Return scripted observations while recording loop events."""

    def __init__(
        self,
        observations: list[Observation],
        *,
        events: list[str] | None = None,
    ) -> None:
        self.observations = observations
        self.events = events if events is not None else []
        self.call_count = 0

    def observe(self) -> Observation:
        self.events.append("observe")
        if self.call_count >= len(self.observations):
            raise AssertionError("No scripted observation remains.")

        observation = self.observations[self.call_count]
        self.call_count += 1
        return observation


class FakeBrowserAgent(BrowserAgent):
    """Return scripted browser decisions while recording received observations."""

    def __init__(
        self,
        decisions: list[BrowserDecision],
        *,
        events: list[str] | None = None,
    ) -> None:
        self.decisions = decisions
        self.events = events if events is not None else []
        self.observations: list[Observation] = []
        self.call_count = 0

    def decide(self, observation: Observation) -> BrowserDecision:
        self.events.append("decide")
        self.observations.append(observation)
        if self.call_count >= len(self.decisions):
            raise AssertionError("No scripted browser decision remains.")

        decision = self.decisions[self.call_count]
        self.call_count += 1
        return decision


class FakeActionExecutor(ActionExecutor):
    """Record actions without interacting with a real execution target."""

    def __init__(self, *, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.actions: list[Action] = []

    def execute(self, action: Action) -> None:
        self.events.append("execute")
        self.actions.append(action)


class FakeBrowser(Browser):
    """A deterministic Browser implementation that does not launch a real browser."""

    def __init__(
        self,
        *,
        url: str = "about:blank",
        title: str = "",
        text: str = "",
        interactive_elements: tuple[InteractiveElement, ...] = (),
        frame_evaluation_results: tuple[object, ...] = (),
        observation_error: BrowserError | None = None,
        action_error: BrowserError | None = None,
    ) -> None:
        self.url = url
        self.page_title = title
        self.page_text = text
        self.page_interactive_elements = interactive_elements
        self.frame_evaluation_results = frame_evaluation_results
        self.observation_error = observation_error
        self.action_error = action_error
        self.action_calls: list[tuple[object, ...]] = []
        self.frame_evaluation_calls: list[str] = []
        self._active_target_ids: set[int] = set()
        self.page = BrowserPage(page_id=1, url=url)
        self.scoped_elements: tuple[BrowserElement, ...] = ()
        self.scope_error: BrowserError | None = None
        self.scope_closed = True

    @contextmanager
    def element_scope(
        self, frame_url_contains: str, selector: str, *, ancestor_url: str
    ) -> Iterator[tuple[BrowserElement, ...]]:
        self.action_calls.append(("element_scope", frame_url_contains, selector, ancestor_url))
        if self.scope_error:
            raise self.scope_error
        self.scope_closed = False
        try:
            yield self.scoped_elements
        finally:
            self.scope_closed = True

    def start(self) -> None:
        pass

    def open(self, url: str) -> None:
        self._raise_action_error()
        self.url = url
        self._active_target_ids.clear()
        self.action_calls.append(("open", url))

    def current_url(self) -> str:
        self._raise_observation_error()
        return self.url

    def title(self) -> str:
        self._raise_observation_error()
        return self.page_title

    def text(self) -> str:
        self._raise_observation_error()
        return self.page_text

    def interactive_elements(self) -> tuple[InteractiveElement, ...]:
        self._raise_observation_error()
        self._active_target_ids = {element.target_id for element in self.page_interactive_elements}
        return self.page_interactive_elements

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self._raise_observation_error()
        self.frame_evaluation_calls.append(expression)
        return self.frame_evaluation_results

    @contextmanager
    def page_element_scope(self, selector: str) -> Iterator[tuple[BrowserElement, ...]]:
        self.action_calls.append(("page_element_scope", selector))
        yield ()

    def current_page(self) -> BrowserPage:
        self._raise_observation_error()
        return BrowserPage(page_id=self.page.page_id, url=self.url)

    def open_new_page_from_frame(
        self, frame_url_contains: str, selector: str, *, timeout_ms: int
    ) -> BrowserPage:
        self._raise_action_error()
        self.action_calls.append(("open_new_page_from_frame", frame_url_contains, selector, timeout_ms))
        self.page = BrowserPage(page_id=self.page.page_id + 1, url="about:blank")
        self.url = self.page.url
        return self.page

    def switch_page(self, page: BrowserPage) -> None:
        self._raise_action_error()
        self.page = page
        self.url = page.url
        self._active_target_ids.clear()
        self.action_calls.append(("switch_page", page.page_id))

    def close_page(self, page: BrowserPage) -> None:
        self._raise_action_error()
        self._active_target_ids.clear()
        self.action_calls.append(("close_page", page.page_id))

    def click_target(self, target_id: int) -> None:
        self._require_target(target_id)
        self._raise_action_error()
        self.action_calls.append(("click_target", target_id))

    def fill_target(self, target_id: int, text: str) -> None:
        self._require_target(target_id)
        self._raise_action_error()
        self.action_calls.append(("fill_target", target_id, text))

    def press_target(self, target_id: int, key: str) -> None:
        self._require_target(target_id)
        self._raise_action_error()
        self.action_calls.append(("press_target", target_id, key))

    def click(self, selector: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("click", selector))

    def fill(self, selector: str, text: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("fill", selector, text))

    def press(self, selector: str, key: str) -> None:
        self._raise_action_error()
        self.action_calls.append(("press", selector, key))

    def scroll(self, delta_y: int) -> None:
        self._raise_action_error()
        self.action_calls.append(("scroll", delta_y))

    def close(self) -> None:
        self._active_target_ids.clear()

    def _raise_observation_error(self) -> None:
        if self.observation_error is not None:
            raise self.observation_error

    def _raise_action_error(self) -> None:
        if self.action_error is not None:
            raise self.action_error

    def _require_target(self, target_id: int) -> None:
        if target_id not in self._active_target_ids:
            raise BrowserElementError(f"Unknown or stale target_id: {target_id}")


class ScriptedInnerbookBrowser(FakeBrowser):
    """Pair card/reader snapshots while recording reader actions separately."""

    def __init__(self, snapshots: Sequence[tuple[tuple[object, ...], tuple[object, ...]]]) -> None:
        super().__init__()
        self.snapshots = list(snapshots)
        self.index = -1
        self.actions: list[str] = []

    def evaluate_in_frames(self, expression: str) -> tuple[object, ...]:
        self.frame_evaluation_calls.append(expression)
        if "const modulePath" in expression:
            self.actions.append(expression)
            return ({"matched": True},)
        if "__linkforgeInnerbookImages" in expression:
            return self.snapshots[max(0, self.index)][1]
        self.index = min(self.index + 1, len(self.snapshots) - 1)
        return self.snapshots[self.index][0]


class FakeDOMElement:
    """Scriptable element with observable capture/click events."""

    def __init__(
        self,
        *,
        inspect: Callable[[], object],
        children: tuple[BrowserElement, ...] = (),
        on_click: Callable[[], None] = lambda: None,
        events: list[str] | None = None,
        name: str = "question",
    ) -> None:
        self.inspect = inspect
        self.children = children
        self.on_click = on_click
        self.events = events if events is not None else []
        self.name = name
        self.screenshot_error: BrowserError | None = None
        self.click_error: BrowserError | None = None

    def query_all(self, selector: str) -> tuple[BrowserElement, ...]:
        return self.children

    def evaluate(self, expression: str) -> object:
        return self.inspect()

    def screenshot(self) -> bytes:
        self.events.append(f"capture:{self.name}")
        if self.screenshot_error:
            raise self.screenshot_error
        return b"test-png"

    def click(self) -> None:
        self.events.append(f"click:{self.name}")
        if self.click_error:
            raise self.click_error
        self.on_click()
