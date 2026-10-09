"""Provider-neutral, user-safe model request failures."""

from __future__ import annotations


class ModelRequestError(RuntimeError):
    """A model provider request failed with a safe Chinese explanation."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"模型调用失败：{reason}")

    @classmethod
    def from_exception(cls, exc: Exception) -> ModelRequestError:
        return cls(model_failure_reason(exc))


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if not isinstance(value, int):
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def model_failure_reason(exc: Exception) -> str:
    """Classify SDK failures without exposing response bodies or credentials."""
    if isinstance(exc, ModelRequestError):
        return exc.reason

    status = _status_code(exc)
    name = type(exc).__name__.lower()

    if status in {401, 403} or "authentication" in name or "permission" in name:
        return "API Key 无效、权限不足，或当前账号无权使用所选模型。"
    if status == 429 or "ratelimit" in name or "rate_limit" in name:
        return "模型服务触发限流或额度不足，请稍后重试并检查账户额度。"
    if status == 404 or "notfound" in name or "not_found" in name:
        return "模型或接口地址不存在，请检查模型名称和服务商配置。"
    if status in {400, 405, 409, 413, 415, 422}:
        return "模型服务不接受当前请求，请检查模型名称、接口地址及图片理解能力。"
    if status is not None and status >= 500:
        return f"模型服务暂时异常（HTTP {status}），请稍后重试。"
    if "timeout" in name:
        return "模型服务响应超时，请检查网络后重试。"
    if any(term in name for term in ("connection", "connect", "network")):
        return "无法连接模型服务，请检查网络和接口地址。"
    if status is not None:
        return f"模型服务返回 HTTP {status}，请检查模型配置或稍后重试。"
    return "模型服务请求异常，请检查网络、API Key、接口地址和模型名称。"
