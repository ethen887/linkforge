"""Browser-backed observation source."""

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.observation.base import Observer
from linkforge.observation.exceptions import ObservationCaptureError
from linkforge.observation.models import Observation


class BrowserObserver(Observer):
    """Capture normalized observations through the Browser abstraction."""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    def observe(self) -> Observation:
        """Capture the browser's current URL, title, and visible text."""
        try:
            return Observation(
                url=self._browser.current_url(),
                title=self._browser.title(),
                text=self._browser.text(),
                interactive_elements=self._browser.interactive_elements(),
            )
        except BrowserError as exc:
            raise ObservationCaptureError("Failed to capture browser observation.") from exc
