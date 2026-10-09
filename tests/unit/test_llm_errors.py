"""User-safe classification of model provider failures."""

import pytest

from linkforge.llm.errors import ModelRequestError, model_failure_reason


class _ProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__("sensitive provider response")


class _TimeoutError(Exception):
    pass


class _ConnectionError(Exception):
    pass


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_ProviderError(401), "API Key 无效"),
        (_ProviderError(429), "限流或额度不足"),
        (_ProviderError(404), "模型或接口地址不存在"),
        (_ProviderError(400), "不接受当前请求"),
        (_ProviderError(503), "HTTP 503"),
        (_TimeoutError(), "响应超时"),
        (_ConnectionError(), "无法连接模型服务"),
    ],
)
def test_model_failure_reason_is_actionable_and_does_not_expose_response(error, expected):
    reason = model_failure_reason(error)

    assert expected in reason
    assert "sensitive provider response" not in reason


def test_model_request_error_keeps_safe_reason() -> None:
    error = ModelRequestError.from_exception(_ProviderError(403))

    assert error.reason.startswith("API Key 无效")
    assert str(error).startswith("模型调用失败：")
