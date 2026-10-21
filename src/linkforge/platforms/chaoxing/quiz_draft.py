"""只点击明确标注为暂存的普通 UI 控件，不复用最终提交及确认流程。"""

import logging
from collections.abc import Callable

from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizStateError

DRAFT_CONTROL_SELECTOR = 'button, input[type="button"], input[type="submit"], [role="button"], a'
logger = logging.getLogger(__name__)
_DRAFT_CONTROL_SCRIPT = r"""element => {
    const labels = [element.innerText || element.textContent, element.value,
        element.getAttribute('aria-label'), element.getAttribute('title')]
        .filter(value => typeof value === 'string')
        .map(value => value.replace(/\s+/g, ' ').trim().toLowerCase()).filter(Boolean);
    const saveLabels = ['暂时保存', '临时保存', '暂存', '保存', '保存答案', 'save', 'save draft'];
    const forbidden = /提交|交卷|完成答题|完成测试|submit|finish|hand\s*in|取消|cancel/;
    const isSave = labels.some(label => saveLabels.includes(label))
        && !labels.some(label => forbidden.test(label))
        && !element.classList.contains('completeBtn')
        && !element.closest('#workpop, [role="dialog"], .popDiv');
    const style = window.getComputedStyle(element);
    return {
        draft: isSave,
        visible: style.display !== 'none' && style.visibility !== 'hidden'
            && element.getClientRects().length > 0,
        enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
    };
}"""


def click_draft_save(elements: tuple[BrowserElement, ...], *, check_stop: Callable[[], None]) -> bool:
    """不存在或无法唯一识别时跳过；实际点击只尝试一次，不确认任何提交弹窗。"""
    try:
        candidates = []
        for element in elements:
            state = element.evaluate(_DRAFT_CONTROL_SCRIPT)
            if (
                not isinstance(state, dict)
                or state.get("draft") is not True
                or state.get("visible") is not True
            ):
                continue
            candidates.append((element, state.get("enabled") is True))
        if not candidates:
            return False
        if len(candidates) != 1 or not candidates[0][1]:
            logger.warning("暂存按钮不唯一或暂不可用，已跳过本次暂存点击")
            return False
        check_stop()
        candidates[0][0].click()
        return True
    except BrowserError as exc:
        # 点击可能已生效，禁止以浏览器错误触发同一保存的自动重试。
        raise ChaoxingQuizStateError("暂存控件操作失败，保存结果未确认，请检查页面。") from exc
