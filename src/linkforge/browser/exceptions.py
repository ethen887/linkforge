"""
LinkForge Browser 异常定义。

本模块定义 Browser Infrastructure 对上层暴露的统一异常类型。

底层浏览器实现（例如 Playwright）产生的具体异常，应在实现层被转换为
本模块定义的异常，避免 Playwright 等第三方库异常直接泄漏到 Agent、
Tools 或 Application 层。
"""


class BrowserError(RuntimeError):
    """
    LinkForge Browser 模块所有运行时异常的基类。
    """


class BrowserStartError(BrowserError):
    """
    浏览器运行环境启动失败。
    """


class BrowserClosedError(BrowserError):
    """
    Browser 尚未启动或其底层页面已经关闭。
    """


class BrowserNavigationError(BrowserError):
    """
    页面导航失败。
    """


class BrowserTimeoutError(BrowserError):
    """
    Browser 操作超过允许的等待时间。
    """


class BrowserElementError(BrowserError):
    """
    页面元素定位或交互失败。
    """
