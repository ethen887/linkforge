"""
PlaywrightBrowser 集成测试。

本模块验证 LinkForge PlaywrightBrowser 与真实 Chromium Runtime 之间的
基本集成行为。

测试目标：
1. 验证 BrowserConfig 能够作为 Browser 创建所需的运行配置。
2. 验证浏览器生命周期能够正常启动和关闭。
3. 验证页面导航和基础页面信息读取。
4. 验证 click、fill、press、scroll 等基础交互能力。
5. 验证 Browser 未启动时能够抛出 LinkForge 自身异常。
6. 验证 Browser 可以通过上下文管理器安全管理资源。

测试页面使用 data URL 在本地构造，不依赖外部公网网站，从而避免：
- 网络波动；
- 第三方网站 DOM 变化；
- CI 环境无法访问公网；
- 外部网站行为导致测试不稳定。
"""

from collections.abc import Generator
from pathlib import Path
from urllib.parse import quote

import pytest

from linkforge.action.browser import BrowserActionExecutor
from linkforge.action.exceptions import ActionExecutionError
from linkforge.action.models import ClickAction, FillAction, PressAction
from linkforge.browser.exceptions import BrowserClosedError, BrowserElementError
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.config.settings import BrowserConfig
from linkforge.observation.browser import BrowserObserver


def _make_data_url(html: str) -> str:
    """
    将 HTML 文本转换为可供浏览器直接访问的 data URL。

    Args:
        html: HTML 页面源码。

    Returns:
        编码后的 data:text/html URL。
    """
    return f"data:text/html;charset=utf-8,{quote(html)}"


def _create_browser(config: BrowserConfig) -> PlaywrightBrowser:
    """
    根据 BrowserConfig 创建 PlaywrightBrowser。

    当前 Browser Infrastructure 保持配置模型与具体 Browser 实现解耦，
    因此由调用方负责将 BrowserConfig 中的参数传递给 PlaywrightBrowser。

    后续 Application 层建立后，这一对象组装职责将由 Application 层承担。

    Args:
        config: Browser 运行配置。

    Returns:
        根据配置创建的 PlaywrightBrowser 实例。
    """
    return PlaywrightBrowser(
        headless=config.headless,
        timeout_ms=config.timeout_ms,
    )


@pytest.fixture
def browser_config() -> BrowserConfig:
    """
    创建 Browser 集成测试专用配置。

    测试使用无头 Chromium，避免运行测试时弹出浏览器窗口。
    同时将 timeout 设置为较小值，使错误能够更快暴露。

    Returns:
        Browser 集成测试配置。
    """
    return BrowserConfig(
        headless=True,
        timeout_ms=3_000,
    )


@pytest.fixture
def browser(
    browser_config: BrowserConfig,
) -> Generator[PlaywrightBrowser, None, None]:
    """
    创建供集成测试使用的 PlaywrightBrowser。

    每个测试都会获得独立 Browser 实例，并在测试结束后自动释放资源。
    即使测试过程中发生异常，也会通过 finally 尝试关闭 Chromium。

    Args:
        browser_config: Browser 集成测试配置。

    Yields:
        已启动的 PlaywrightBrowser 实例。
    """
    instance = _create_browser(browser_config)

    instance.start()

    try:
        yield instance
    finally:
        instance.close()


def test_browser_can_start_open_and_read_page(
    browser: PlaywrightBrowser,
) -> None:
    """
    验证 Browser 能够打开页面并读取基础页面信息。
    """
    html = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>LinkForge Test</title>
        </head>
        <body>
            <h1>Hello LinkForge</h1>
            <p>Browser integration test.</p>
        </body>
    </html>
    """

    browser.open(_make_data_url(html))

    assert browser.title() == "LinkForge Test"
    assert "Hello LinkForge" in browser.text()
    assert "Browser integration test." in browser.text()
    assert browser.current_url().startswith("data:text/html")


def test_browser_can_fill_input(
    browser: PlaywrightBrowser,
) -> None:
    """
    验证 Browser 能够向输入框填写文本。
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <input
                id="name"
                type="text"
                oninput="
                    document.getElementById('result').innerText = this.value;
                "
            >

            <p id="result"></p>
        </body>
    </html>
    """

    browser.open(_make_data_url(html))

    browser.fill("#name", "LinkForge")

    assert "LinkForge" in browser.text()


def test_browser_can_click_element(
    browser: PlaywrightBrowser,
) -> None:
    """
    验证 Browser 能够点击页面元素。
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <button
                id="submit"
                onclick="
                    document.getElementById('result').innerText =
                    'Button clicked';
                "
            >
                Submit
            </button>

            <p id="result"></p>
        </body>
    </html>
    """

    browser.open(_make_data_url(html))

    browser.click("#submit")

    assert "Button clicked" in browser.text()


def test_browser_can_press_key(
    browser: PlaywrightBrowser,
) -> None:
    """
    验证 Browser 能够向指定元素发送键盘按键。
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <input
                id="input"
                type="text"
                onkeydown="
                    if (event.key === 'Enter') {
                        document.getElementById('result').innerText =
                        'Enter pressed';
                    }
                "
            >

            <p id="result"></p>
        </body>
    </html>
    """

    browser.open(_make_data_url(html))

    browser.fill("#input", "test")
    browser.press("#input", "Enter")

    assert "Enter pressed" in browser.text()


def test_browser_can_scroll_page(
    browser: PlaywrightBrowser,
) -> None:
    """
    验证 Browser 能够执行页面滚动操作。

    当前 Browser 公共接口暂未暴露 scroll position，因此本测试主要验证
    scroll() 能够通过真实 Playwright + Chromium 执行且不会产生异常。

    后续如果 Observation 层需要暴露 viewport 或 scroll position，
    可以进一步增加状态断言。
    """
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <div style="height: 3000px;">
                <p>Long page for scroll test.</p>
            </div>
        </body>
    </html>
    """

    browser.open(_make_data_url(html))

    browser.scroll(500)
    browser.scroll(-200)


def test_browser_close_is_idempotent(
    browser_config: BrowserConfig,
) -> None:
    """
    验证 Browser.close() 可以被重复调用。

    资源清理操作应具有幂等性，避免 finally、上下文管理器或其他清理逻辑
    重复调用 close() 时产生新的异常。
    """
    browser = _create_browser(browser_config)

    browser.start()

    browser.close()
    browser.close()


def test_persistent_profile_context_can_start_and_close_idempotently(tmp_path: Path) -> None:
    browser = PlaywrightBrowser(
        headless=True,
        timeout_ms=3_000,
        profile_dir=str(tmp_path / "profile"),
    )

    browser.start()
    browser.close()
    browser.close()


def test_persistent_profile_reuses_local_storage(tmp_path: Path) -> None:
    page_path = tmp_path / "persistent-state.html"
    page_path.write_text("<p>Persistent profile state</p>", encoding="utf-8")
    page_url = page_path.as_uri()
    profile_dir = str(tmp_path / "profile")

    with PlaywrightBrowser(
        headless=True,
        timeout_ms=3_000,
        profile_dir=profile_dir,
    ) as first_browser:
        first_browser.open(page_url)
        first_browser.evaluate_in_frames(
            "() => localStorage.setItem('linkforge-profile-test', 'persisted')"
        )

    with PlaywrightBrowser(
        headless=True,
        timeout_ms=3_000,
        profile_dir=profile_dir,
    ) as second_browser:
        second_browser.open(page_url)
        stored_values = second_browser.evaluate_in_frames(
            "() => localStorage.getItem('linkforge-profile-test')"
        )

    assert "persisted" in stored_values


def test_browser_operation_before_start_raises_closed_error(
    browser_config: BrowserConfig,
) -> None:
    """
    验证 Browser 未启动时操作页面会抛出 LinkForge 自身异常。

    该测试用于确认上层代码不需要直接处理 Playwright 的底层异常类型。
    """
    browser = _create_browser(browser_config)

    with pytest.raises(BrowserClosedError):
        browser.title()


def test_browser_context_manager_closes_resources(
    browser_config: BrowserConfig,
) -> None:
    """
    验证 Browser 支持通过 with 上下文管理器管理生命周期。
    """
    html = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Context Manager Test</title>
        </head>
        <body>
            <p>Context manager works.</p>
        </body>
    </html>
    """

    browser = _create_browser(browser_config)

    with browser:
        browser.open(_make_data_url(html))

        assert browser.title() == "Context Manager Test"
        assert "Context manager works." in browser.text()

    with pytest.raises(BrowserClosedError):
        browser.title()


def test_interactive_elements_support_target_based_actions(
    browser: PlaywrightBrowser,
) -> None:
    """Verify the complete observation-to-target-action path on a local page."""
    html = """
    <!DOCTYPE html>
    <html>
        <head>
            <title>Interactive Elements Test</title>
        </head>
        <body>
            <label for="query">Search query</label>
            <input
                id="query"
                type="search"
                oninput="document.getElementById('result').innerText = 'Filled: ' + this.value;"
                onkeydown="
                    if (event.key === 'Enter') {
                        document.getElementById('result').innerText = 'Enter pressed';
                    }
                "
            >
            <button
                id="search"
                onclick="document.getElementById('result').innerText = 'Button clicked';"
            >
                Search
            </button>
            <a
                href="#details"
                onclick="document.getElementById('result').innerText = 'Link clicked';"
            >
                Open details
            </a>
            <p id="result"></p>
        </body>
    </html>
    """
    browser.open(_make_data_url(html))
    observation = BrowserObserver(browser).observe()
    executor = BrowserActionExecutor(browser)

    elements = {(element.role, element.name): element for element in observation.interactive_elements}
    textbox = elements[("textbox", "Search query")]
    button = elements[("button", "Search")]
    link = elements[("link", "Open details")]

    assert len({textbox.target_id, button.target_id, link.target_id}) == 3

    executor.execute(FillAction(target_id=textbox.target_id, text="LinkForge"))
    assert "Filled: LinkForge" in browser.text()

    executor.execute(PressAction(target_id=textbox.target_id, key="Enter"))
    assert "Enter pressed" in browser.text()

    executor.execute(ClickAction(target_id=button.target_id))
    assert "Button clicked" in browser.text()

    executor.execute(ClickAction(target_id=link.target_id))
    assert "Link clicked" in browser.text()


def test_new_observation_invalidates_previous_target_ids(
    browser: PlaywrightBrowser,
) -> None:
    """Verify target IDs cannot resolve to elements from a newer observation."""
    html = """
    <!DOCTYPE html>
    <html>
        <body>
            <button>Submit</button>
        </body>
    </html>
    """
    browser.open(_make_data_url(html))
    observer = BrowserObserver(browser)
    executor = BrowserActionExecutor(browser)

    first_observation = observer.observe()
    second_observation = observer.observe()
    stale_target_id = first_observation.interactive_elements[0].target_id
    current_target_id = second_observation.interactive_elements[0].target_id

    assert stale_target_id != current_target_id

    with pytest.raises(ActionExecutionError) as exc_info:
        executor.execute(ClickAction(target_id=stale_target_id))

    assert isinstance(exc_info.value.__cause__, BrowserElementError)
