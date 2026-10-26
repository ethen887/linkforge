"""TEX 的预览与上传是两个异步阶段；确认上传后绝不重放点击。"""

import logging
from collections.abc import Callable

from linkforge.browser.base import Browser
from linkforge.browser.element import BrowserElement
from linkforge.platforms.chaoxing.exceptions import ChaoxingWrittenStateError

logger = logging.getLogger(__name__)
FORMULA_FRAME = 'iframe[src*="/ananas/common-modules/latex/"]'
VISIBLE = "e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden'"


class FormulaTimeoutError(ChaoxingWrittenStateError):
    """只在确认前允许重新触发一次预览；上传结果未知时不得重试。"""


class FormulaDialog:
    def __init__(
        self,
        browser: Browser,
        *,
        check: Callable[[], None],
        sleep: Callable[[float], None],
        monotonic: Callable[[], float],
        timeout: float,
        poll_interval: float,
    ) -> None:
        self.browser = browser
        self.check = check
        self.sleep = sleep
        self.monotonic = monotonic
        self.timeout = timeout
        self.poll_interval = poll_interval

    def with_dialog(self, operation: Callable[[BrowserElement], bool]) -> bool:
        self.check()
        with self.browser.page_element_scope(FORMULA_FRAME) as frames:
            visible = [frame for frame in frames if frame.evaluate(VISIBLE) is True]
            if len(visible) > 1:
                raise ChaoxingWrittenStateError("TEX 窗口不唯一，已停止确认。")
            return operation(visible[0]) if visible else False

    def wait(self, predicate: Callable[[], bool], stage: str) -> None:
        logger.info("TEX 公式：%s", stage)
        deadline = self.monotonic() + self.timeout
        while True:
            self.check()
            if predicate():
                return
            if self.monotonic() >= deadline:
                raise FormulaTimeoutError(f"TEX {stage}超时；已保留草稿，请检查公式窗口和网络。")
            self.sleep(self.poll_interval)

    @staticmethod
    def fill(frame: BrowserElement, value: str) -> bool:
        inputs = frame.frame_query_all("#txta_input")
        if len(inputs) != 1:
            raise ChaoxingWrittenStateError("TEX 输入框不唯一。")
        # 相同值的 fill 不保证触发 input。先实际改变输入，再恢复目标值。
        inputs[0].fill(value + " ")
        inputs[0].fill(value)
        inputs[0].press("End")
        if inputs[0].evaluate("e => e.value") != value:
            raise ChaoxingWrittenStateError("TEX 输入框中的公式发生变化，已停止确认。")
        return True

    def insert(self, latex: str, *, before_confirm: Callable[[], None]) -> None:
        self.wait(
            lambda: self.with_dialog(lambda frame: len(frame.frame_query_all("#txta_input")) == 1),
            "等待输入窗口就绪",
        )
        for attempt in range(2):
            try:
                preview_svg = self._preview(latex)
                break
            except FormulaTimeoutError:
                # 只有确认前、正文未改变时，才能重新输入；绝不重传结果未知的公式。
                before_confirm()
                if attempt:
                    raise
                logger.warning("TEX 公式：预览未就绪，确认前重新输入一次")
        before_confirm()

        def confirm(frame: BrowserElement) -> bool:
            inputs = frame.frame_query_all("#txta_input")
            if len(inputs) != 1 or inputs[0].evaluate("e => e.value") != latex:
                raise ChaoxingWrittenStateError("确认前 TEX 输入内容已改变，已保留草稿。")
            if self.output(frame) != {"svg": preview_svg, "invalid": False}:
                raise ChaoxingWrittenStateError("确认前 TEX 预览发生变化，已停止上传。")
            controls = frame.frame_query_all(".confirmBtn")
            if len(controls) != 1:
                raise ChaoxingWrittenStateError("TEX 确认按钮不唯一。")
            self.check()
            logger.info("TEX 公式：已确认预览，开始上传并等待插入（不重复确认）")
            controls[0].click()
            return True

        if not self.with_dialog(confirm):
            raise ChaoxingWrittenStateError("TEX 窗口已改变，已停止确认。")

    @staticmethod
    def output(frame: BrowserElement) -> object:
        outputs = frame.frame_query_all("#wrap_output")
        if len(outputs) != 1:
            return None
        return outputs[0].evaluate("""e => {
            const svg = e.querySelector('svg');
            if (!svg) return {svg:'', invalid:false};
            const drawn = [...svg.querySelectorAll('use,path,text,line,rect,polygon,polyline')]
                .some(node => !node.closest('defs'));
            return {svg:drawn ? svg.outerHTML : '',
                invalid:!!e.querySelector('[data-mml-node=merror],mjx-merror,.mjx-merror,[data-mjx-error]')};
        }""")

    def _preview(self, latex: str) -> str:
        if not self.with_dialog(lambda frame: self.fill(frame, "")):
            raise ChaoxingWrittenStateError("TEX 窗口已关闭，已保留草稿。")

        # MathJax 异步替换 SVG；必须观察旧预览消失，不能复用上条公式。
        self.wait(
            lambda: self.with_dialog(lambda frame: self.output(frame) == {"svg": "", "invalid": False}),
            "等待旧预览清空",
        )
        if not self.with_dialog(lambda frame: self.fill(frame, latex)):
            raise ChaoxingWrittenStateError("TEX 窗口已改变。")
        last_svg: object = None
        stable_since = self.monotonic()
        stable_svg = ""

        def ready(frame: BrowserElement) -> bool:
            nonlocal last_svg, stable_since, stable_svg
            inputs = frame.frame_query_all("#txta_input")
            if len(inputs) != 1 or inputs[0].evaluate("e => e.value") != latex:
                raise ChaoxingWrittenStateError("等待预览期间 TEX 输入已改变，已停止确认。")
            state = self.output(frame)
            if not isinstance(state, dict) or not state.get("svg"):
                last_svg = None
                stable_since = self.monotonic()
                return False
            if state != last_svg:
                last_svg, stable_since = state, self.monotonic()
                return False
            if self.monotonic() - stable_since < 0.3:
                return False
            if state["invalid"]:
                raise ChaoxingWrittenStateError("TEX 预览包含公式语法错误，未确认上传；请检查公式。")
            stable_svg = str(state["svg"])
            return True

        self.wait(lambda: self.with_dialog(ready), "等待新公式预览稳定")
        return stable_svg
