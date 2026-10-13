"""浏览器基础设施的构造。"""

from linkforge.browser.base import Browser
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.config.settings import BrowserConfig


def create_browser(config: BrowserConfig) -> Browser:
    """根据运行时配置创建生产环境的 Browser 实现。"""
    return PlaywrightBrowser(
        headless=config.headless,
        timeout_ms=config.timeout_ms,
        profile_dir=config.profile_dir,
    )
