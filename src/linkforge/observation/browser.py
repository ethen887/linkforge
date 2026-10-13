"""基于浏览器的观察源。"""

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.observation.base import Observer
from linkforge.observation.exceptions import ObservationCaptureError
from linkforge.observation.models import Observation


class BrowserObserver(Observer):
    """通过 Browser 抽象层捕获规范化观察结果。"""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    def observe(self) -> Observation:
        """捕获浏览器当前的 URL、标题与可见文本。"""
        try:
            return Observation(
                url=self._browser.current_url(),
                title=self._browser.title(),
                text=self._browser.text(),
                interactive_elements=self._browser.interactive_elements(),
            )
        except BrowserError as exc:
            raise ObservationCaptureError("Failed to capture browser observation.") from exc
