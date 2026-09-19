"""Browser infrastructure construction."""

from linkforge.browser.base import Browser
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.config.settings import BrowserConfig


def create_browser(config: BrowserConfig) -> Browser:
    """Create the production Browser implementation from runtime configuration."""
    return PlaywrightBrowser(
        headless=config.headless,
        timeout_ms=config.timeout_ms,
        profile_dir=config.profile_dir,
    )
