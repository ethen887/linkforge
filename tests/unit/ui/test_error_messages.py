"""Chinese, user-oriented runtime error presentation."""

from linkforge.application.task_runner import UnknownTaskError
from linkforge.llm.errors import ModelRequestError
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingQuizSolverError,
    ContentNavigationError,
)
from linkforge.ui.error_messages import user_error_message


def test_unknown_task_explains_unsupported_module() -> None:
    message = user_error_message(UnknownTaskError("internal English message"))

    assert message.category == "暂不支持的课程模块"
    assert "暂不支持" in message.summary
    assert "手动完成或跳过" in message.summary
    assert "internal English" not in message.summary


def test_model_failure_uses_reason_from_cause_chain() -> None:
    try:
        raise ModelRequestError("模型或接口地址不存在，请检查模型名称和服务商配置。")
    except ModelRequestError as cause:
        error = ChaoxingQuizSolverError("internal wrapper")
        error.__cause__ = cause

    message = user_error_message(error)

    assert message.category == "模型调用失败"
    assert "模型或接口地址不存在" in message.summary
    assert "internal wrapper" not in message.summary


def test_content_navigation_error_has_actionable_chinese_message() -> None:
    message = user_error_message(ContentNavigationError("knowledgeId did not change"))

    assert message.category == "课程页面切换失败"
    assert "弹窗、遮挡或尚未完成的任务" in message.summary
    assert "knowledgeId" not in message.summary


def test_unclassified_error_does_not_show_raw_exception_text() -> None:
    message = user_error_message(RuntimeError("Authorization: secret-value"))

    assert message.category == "运行异常"
    assert "secret-value" not in message.summary
    assert "最新日志" in message.summary
