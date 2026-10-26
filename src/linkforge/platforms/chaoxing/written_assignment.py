"""独立作业草稿：所有题型逐题填写、暂存，整份处理后交还用户检查。"""

import logging
from collections.abc import Callable

from linkforge.application.task_runner import TaskReviewRequiredError
from linkforge.browser.element import BrowserElement
from linkforge.browser.exceptions import BrowserError
from linkforge.llm.base import LLMImage
from linkforge.llm.errors import ModelRequestError
from linkforge.platforms.chaoxing.assignment_handler import StandaloneAssignmentHandler
from linkforge.platforms.chaoxing.assignment_page import ASSIGNMENT_SUBMIT_PATH
from linkforge.platforms.chaoxing.exceptions import ChaoxingQuizError, ChaoxingWrittenStateError
from linkforge.platforms.chaoxing.quiz_dom import QuizDOMQuestion
from linkforge.platforms.chaoxing.quiz_draft import click_draft_save
from linkforge.platforms.chaoxing.quiz_handler import _QuizDraftClickedError
from linkforge.platforms.chaoxing.quiz_models import (
    QuizAnswer,
    QuizQuestion,
    QuizQuestionType,
    validate_answer,
)
from linkforge.platforms.chaoxing.written_answer import LLMWrittenSolver, WrittenDraft
from linkforge.platforms.chaoxing.written_editor import (
    EditorSnapshot,
    WrittenEditor,
    is_written,
    normalize_editor_text,
)
from linkforge.platforms.chaoxing.written_formula import FORMULA_FRAME, VISIBLE, FormulaDialog
from linkforge.platforms.chaoxing.written_review import ISSUE_LABELS, LLMWrittenReviewer, WrittenAuditRecord

logger = logging.getLogger(__name__)


def _input_failure_reason(exc: BrowserError) -> str:
    """仅输出固定分类；底层错误可能包含 URL、页面正文及认证参数。"""
    cause: BaseException | None = exc
    while cause is not None:
        value = str(cause).lower()
        if "intercepts pointer events" in value:
            return "点击被页面顶栏或浮层遮挡"
        if "detached" in value or "not attached" in value:
            return "元素已重绘或失效"
        if "closed" in value:
            return "元素作用域或页面已关闭"
        if "timeout" in type(cause).__name__.lower() or "timeout" in value:
            reason = "浏览器交互等待超时"
        else:
            reason = "浏览器交互失败"
        if cause.__cause__ is None:
            return reason
        cause = cause.__cause__
    return "浏览器交互失败"


class _WriteInterruptedError(Exception):
    def __init__(self, error: BrowserError) -> None:
        self.error = error


class DraftingAssignmentHandler(StandaloneAssignmentHandler):
    written_solver: LLMWrittenSolver
    written_reviewer: LLMWrittenReviewer
    audit_history: list[WrittenAuditRecord]

    def _run(self) -> None:
        url, _ = self._target()
        try:
            self._draft_assignment(url)
        except (ChaoxingQuizError, BrowserError, ModelRequestError) as exc:
            self._check_stop()
            if isinstance(exc, ChaoxingWrittenStateError):
                logger.warning("作业草稿暂停原因：%s", str(exc))
            logger.warning("作业草稿未全部确认暂存，已暂停等待人工检查（%s）", type(exc).__name__)
            raise TaskReviewRequiredError(saved=False) from None
        self._check_stop()
        raise TaskReviewRequiredError

    def _draft_assignment(self, url: str) -> None:
        self.audit_history = []
        expected: dict[int, EditorSnapshot | QuizAnswer] = {}
        question_images: dict[int, LLMImage] = {}
        with self._browser.page_element_scope(FORMULA_FRAME) as frames:
            if any(frame.evaluate(VISIBLE) is True for frame in frames):
                raise ChaoxingWrittenStateError("请先关闭已打开的 TEX 窗口，再开始生成草稿。")

        def preflight(nodes: tuple[BrowserElement, ...]) -> tuple[bool, ...]:
            kinds = tuple(is_written(e) for e in nodes)
            for index, (element, written) in enumerate(zip(nodes, kinds, strict=True)):
                if written:
                    WrittenEditor(element).snapshot()
                else:
                    dom = QuizDOMQuestion(element, index)
                    dom.selected(dom.hint or QuizQuestionType.SINGLE_CHOICE)
            return kinds

        kinds = self._with_questions(url, preflight)
        logger.info("整份作业共 %d 题：逐题作答并暂存，全部处理后等待检查", len(kinds))

        def signatures(nodes: tuple[BrowserElement, ...]) -> tuple[object, ...]:
            return tuple(
                node.evaluate("""e => {
                const copy = e.cloneNode(true);
                copy.querySelectorAll('.edui-editor,iframe,textarea,script,style').forEach(e => e.remove());
                return (copy.textContent || '').replace(/\\s+/g, ' ').trim();
            }""")
                for node in nodes
            )

        original_signatures = self._with_questions(url, signatures)

        def verify(nodes: tuple[BrowserElement, ...]) -> None:
            self._check_identity(url)
            if (
                len(nodes) != len(kinds)
                or tuple(is_written(e) for e in nodes) != kinds
                or signatures(nodes) != original_signatures
            ):
                logger.warning("作业核验失败：题目数量、题型或题干发生变化")
                raise ChaoxingWrittenStateError("草稿作答期间题目结构发生变化。")
            for index, state in expected.items():
                if isinstance(state, EditorSnapshot):
                    editor = WrittenEditor(nodes[index])
                    if editor.snapshot() != state:
                        logger.warning("第 %d 题：暂存后正文或公式与录入结果不一致", index + 1)
                        raise ChaoxingWrittenStateError("暂存后大题草稿发生变化，已停止继续填写。")
                    if not editor.saved_copy_matches():
                        logger.warning("第 %d 题：编辑器内容未同步到暂存表单", index + 1)
                        raise ChaoxingWrittenStateError("大题正文未同步到暂存表单，请手动检查保存。")
                else:
                    dom = QuizDOMQuestion(nodes[index], index)
                    if dom.selected(state.question_type) != frozenset(state.choices):
                        raise ChaoxingWrittenStateError("暂存后已有选项发生变化，已停止继续填写。")

        for index, written in enumerate(kinds):
            self._with_questions(url, verify)
            if written:
                state = self._with_questions(url, lambda nodes: WrittenEditor(nodes[index]).snapshot())
                image = self._with_questions(url, lambda nodes: LLMImage(nodes[index].screenshot()))
                question_images[index] = image
                if state.has_content:
                    logger.info("第 %d 题：正在判断已有答案是否需要重做", index + 1)
                    rewrite = self.written_solver.needs_rewrite(
                        image, text=state.text, formulas=state.formulas
                    )
                    self._check_identity(url)
                    self._with_questions(url, verify)
                    current = self._with_questions(
                        url, lambda nodes: WrittenEditor(nodes[index]).snapshot()
                    )
                    if current != state:
                        raise ChaoxingWrittenStateError("模型判断期间大题内容已改变，请检查页面。")
                    if not rewrite:
                        expected[index] = state
                        self._save_written(url)
                        self._with_questions(url, verify)
                        logger.info("第 %d 题：AI 判断可保留已有答案，已跳过重做", index + 1)
                        continue
                    logger.info("第 %d 题：AI 判断需要重做，生成完整答案后覆盖", index + 1)
                logger.info("第 %d 题：正在生成大题草稿", index + 1)
                self._check_identity(url)
                draft = self.written_solver.solve(image, question_text=str(original_signatures[index]))
                self._check_identity(url)
                self._with_questions(url, verify)
                # 清空前再次确认用户没有在模型等待期间修改答案。
                current = self._with_questions(url, lambda nodes: WrittenEditor(nodes[index]).snapshot())
                if current != state:
                    raise ChaoxingWrittenStateError("模型等待期间大题内容已改变，请检查页面。")
                expected[index] = self._write_draft(
                    url, index, draft, replace=state if state.has_content else None
                )
                self._save_written(url)
                self._with_questions(url, verify)
                logger.info("第 %d 题：大题草稿已填写并确认暂存", index + 1)
            else:

                def capture(nodes: tuple[BrowserElement, ...]):
                    dom = QuizDOMQuestion(nodes[index], index)
                    return dom.resumable_answer() or dom.capture()

                question = self._with_questions(url, capture)
                if isinstance(question, QuizAnswer):
                    expected[index] = question
                    continue
                answer = validate_answer(question, self._solver.solve(question))
                self._check_identity(url)
                for _ in range(len(question.option_letters) + 1):

                    def reconcile(nodes: tuple[BrowserElement, ...]) -> None:
                        verify(nodes)
                        self._reconcile_one(nodes[index], question, answer, url)

                    try:
                        self._with_questions(url, reconcile)
                        break
                    except _QuizDraftClickedError as saved:
                        actual = self._with_questions(
                            url,
                            lambda nodes: QuizDOMQuestion(nodes[index], index).selected(
                                answer.question_type
                            ),
                        )
                        if actual != saved.selected:
                            raise ChaoxingWrittenStateError("暂存后选项变化。") from None
                else:
                    raise ChaoxingWrittenStateError("暂存后选项未稳定。")
                expected[index] = answer
        self._with_questions(url, verify)
        # 最后再确认整份表单已保存，包括期间保留的手动客观题答案。
        self._save_written(url)
        self._with_questions(url, verify)
        self._audit_written(
            url, kinds, expected, question_images, tuple(str(s) for s in original_signatures), verify
        )
        self._with_questions(url, verify)
        logger.info("整份作业 %d 题已处理并确认暂存，等待人工检查和提交", len(kinds))

    def _audit_written(
        self,
        url: str,
        kinds: tuple[bool, ...],
        expected: dict[int, EditorSnapshot | QuizAnswer],
        question_images: dict[int, LLMImage],
        question_texts: tuple[str, ...],
        verify: Callable[[tuple[BrowserElement, ...]], None],
    ) -> None:
        pending = [index for index, written in enumerate(kinds) if written]
        # 首次审核后最多自动重做两轮；只重做未通过的题目。
        for attempt in range(3):
            failed = []
            for index in pending:
                self._with_questions(url, verify)
                state = expected[index]
                if not isinstance(state, EditorSnapshot):
                    raise ChaoxingWrittenStateError("审核题型状态不一致。")
                logger.info("第 %d 题：正在进行第 %d 轮作答审核", index + 1, attempt + 1)
                screenshots = self._with_questions(
                    url, lambda nodes: WrittenEditor(nodes[index]).audit_screenshots()
                )
                self._with_questions(url, verify)
                result = self.written_reviewer.audit(
                    (question_images[index], *(LLMImage(data) for data in screenshots)),
                    question_text=question_texts[index],
                    text=state.text,
                    formulas=state.formulas,
                )
                self._check_identity(url)
                self._with_questions(url, verify)
                self.audit_history.append(WrittenAuditRecord(index, attempt + 1, result.issues))
                if result.passed:
                    logger.info("第 %d 题：第 %d 轮作答审核通过", index + 1, attempt + 1)
                else:
                    failed.append(index)
                    for issue in result.issues:
                        # 自由文本反馈仅用于本次重做上下文，日志只记录固定问题分类。
                        logger.warning(
                            "第 %d 题：第 %d 轮审核问题：%s",
                            index + 1,
                            attempt + 1,
                            ISSUE_LABELS[issue.code],
                        )
            if not failed:
                if pending:
                    logger.info("作业大题自动审核全部通过，草稿等待人工检查")
                return
            if attempt == 2:
                logger.warning("作答审核仍未通过，已达到两轮自动重做上限，保留草稿等待人工检查")
                raise ChaoxingWrittenStateError("自动审核未通过，已达到重做上限。")
            for index in failed:
                self._with_questions(url, verify)
                old = expected[index]
                if not isinstance(old, EditorSnapshot):
                    raise ChaoxingWrittenStateError("重做题型状态不一致。")
                feedback = tuple(
                    f"{ISSUE_LABELS[issue.code]}：{issue.detail}"
                    for record in self.audit_history
                    if record.question_index == index
                    for issue in record.issues
                )
                logger.info("第 %d 题：正在根据审核记录进行第 %d 次重做", index + 1, attempt + 1)
                draft = self.written_solver.solve(
                    question_images[index], question_text=question_texts[index], feedback=feedback
                )
                self._check_identity(url)
                self._with_questions(url, verify)
                expected[index] = self._write_draft(url, index, draft, replace=old)
                self._save_written(url)
                self._with_questions(url, verify)
            pending = failed

    def _check_identity(self, url: str) -> None:
        self._check_stop()
        if self._target() != (url, url):
            raise ChaoxingWrittenStateError("大题作答页面已改变。")

    def _reconcile_one(
        self, element: BrowserElement, question: QuizQuestion, answer: QuizAnswer, url: str
    ) -> None:
        QuizDOMQuestion(element, question.index).reconcile(
            question,
            answer,
            timeout_seconds=self._config.selection_timeout_seconds,
            poll_interval_seconds=self._config.poll_interval_seconds,
            sleep=self._sleep,
            monotonic=self._monotonic,
            before_click=lambda: self._check_identity(url),
            on_selection_changed=lambda selected: self._save_after_click(
                url, url, question.index, selected
            ),
        )

    def _wait(self, url: str, predicate: Callable[[], bool], *, timeout: float, stage: str) -> None:
        deadline = self._monotonic() + timeout
        while True:
            self._check_identity(url)
            if predicate():
                return
            if self._monotonic() >= deadline:
                raise ChaoxingWrittenStateError(
                    f"{stage}超时；已保留草稿，不会重复确认公式，请检查网络和页面。"
                )
            self._sleep(self._config.poll_interval_seconds)

    def _write_draft(
        self, url: str, index: int, draft: WrittenDraft, *, replace: EditorSnapshot | None = None
    ) -> EditorSnapshot:
        text: list[str] = []
        formulas: list[str] = []

        def write_once(
            operation: Callable[[WrittenEditor], None],
            *,
            stage: str,
            before: EditorSnapshot | None = None,
            wanted: EditorSnapshot | None = None,
            opens_formula: bool = False,
        ) -> None:
            def apply(nodes: tuple[BrowserElement, ...]) -> None:
                try:
                    operation(WrittenEditor(nodes[index]))
                except BrowserError as exc:
                    # 先退出普通的 DOM 重试路径，交由下面回读确认是否已经生效。
                    raise _WriteInterruptedError(exc) from None

            for attempt in range(2):
                self._check_identity(url)
                try:
                    self._with_questions(url, apply)
                    return
                except _WriteInterruptedError as interrupted:
                    self._check_identity(url)
                    logger.warning(
                        "第 %d 题：%s失败（%s）", index + 1, stage, _input_failure_reason(interrupted.error)
                    )
                    if before is None:
                        raise ChaoxingWrittenStateError(
                            "清空旧答案的结果不确定，已停止重复操作，请检查页面。"
                        ) from None
                    try:
                        current = self._with_questions(
                            url,
                            lambda nodes: WrittenEditor(nodes[index]).snapshot(
                                require_images=False, allow_cleared=replace is not None
                            ),
                        )
                        with self._browser.page_element_scope(FORMULA_FRAME) as frames:
                            visible_dialogs = sum(frame.evaluate(VISIBLE) is True for frame in frames)
                    except BrowserError:
                        raise ChaoxingWrittenStateError(
                            "录入中断且无法可靠回读当前内容，已停止重复写入。"
                        ) from None
                    self._check_identity(url)
                    applied = (
                        current == wanted and visible_dialogs == 0
                        if not opens_formula
                        else current == before and visible_dialogs == 1
                    )
                    if applied:
                        logger.info("第 %d 题：已回读确认交互生效，继续后续核验", index + 1)
                        return
                    if current == before and visible_dialogs == 0 and attempt == 0:
                        logger.info("第 %d 题：已确认交互未生效，重新定位后重试一次", index + 1)
                        continue
                    raise ChaoxingWrittenStateError(
                        "录入状态不一致、出现部分内容或重试仍失败，已保留当前草稿。"
                    ) from None

        if replace is not None:

            def clear(editor: WrittenEditor) -> None:
                if editor.snapshot() != replace:
                    raise ChaoxingWrittenStateError("覆盖前大题内容已改变，已保留当前内容。")
                editor.clear()

            write_once(clear, stage="清空旧答案")

        for block_index, block in enumerate(draft.blocks):
            self._check_identity(url)
            logger.info("第 %d 题：正在录入第 %d/%d 段", index + 1, block_index + 1, len(draft.blocks))
            before = EditorSnapshot(normalize_editor_text(" ".join(text)), tuple(formulas))
            if block.kind == "text":
                wanted = EditorSnapshot(
                    normalize_editor_text(" ".join((*text, block.content))), tuple(formulas)
                )
                write_once(
                    lambda editor: editor.append_text(block.content, first=not text and not formulas),
                    stage="正文输入",
                    before=before,
                    wanted=wanted,
                )
                text.append(block.content)
            else:
                write_once(
                    lambda editor: editor.open_formula(),
                    stage="打开 TEX 窗口",
                    before=before,
                    opens_formula=True,
                )

                def before_confirm() -> None:
                    state = self._with_questions(
                        url,
                        lambda nodes: WrittenEditor(nodes[index]).snapshot(
                            require_images=False, allow_cleared=replace is not None
                        ),
                    )
                    if state != before:
                        raise ChaoxingWrittenStateError("公式预览期间正文或已有公式发生变化，已停止确认。")

                self._insert_formula(url, block.content, before_confirm=before_confirm)
                formulas.append(block.content)
            wanted = EditorSnapshot(normalize_editor_text(" ".join(text)), tuple(formulas))

            def inserted() -> bool:
                state = self._with_questions(
                    url,
                    lambda nodes: WrittenEditor(nodes[index]).snapshot(
                        require_images=False, allow_cleared=replace is not None
                    ),
                )
                if state != wanted:
                    if block.kind == "latex" and state == before:
                        return False  # 点击确认后，平台先上传 PNG，随后异步插入。
                    raise ChaoxingWrittenStateError("录入后正文或公式与预期不一致，已停止重复写入。")
                with self._browser.page_element_scope(FORMULA_FRAME) as frames:
                    if any(frame.evaluate(VISIBLE) is True for frame in frames):
                        return False
                image_state = self._with_questions(
                    url,
                    lambda nodes: nodes[index].evaluate(
                        "e => {const images = [...e.querySelector('iframe[id^=ueditor_]')"
                        ".contentDocument.images];"
                        "if (images.some(i => i.complete && i.naturalWidth === 0)) return 'broken';"
                        "return images.every(i => i.complete && i.naturalWidth > 0)"
                        " ? 'ready' : 'loading';}"
                    ),
                )
                if image_state == "broken":
                    raise ChaoxingWrittenStateError(
                        "公式已插入，但图片加载失败；请检查网络并手动保存，程序不会重复插入。"
                    )
                return image_state == "ready"

            self._wait(
                url,
                inserted,
                timeout=self._config.formula_insert_timeout_seconds,
                stage="等待公式上传、插入和图片加载" if block.kind == "latex" else "等待正文回读",
            )
            logger.info("第 %d 题：第 %d/%d 段已核验", index + 1, block_index + 1, len(draft.blocks))
        return wanted

    def _insert_formula(self, url: str, latex: str, *, before_confirm: Callable[[], None]) -> None:
        FormulaDialog(
            self._browser,
            check=lambda: self._check_identity(url),
            sleep=self._sleep,
            monotonic=self._monotonic,
            timeout=self._config.formula_preview_timeout_seconds,
            poll_interval=self._config.poll_interval_seconds,
        ).insert(latex, before_confirm=before_confirm)

    def _save_written(self, url: str) -> None:
        self._check_identity(url)
        if self._form_fields is None:
            raise ChaoxingWrittenStateError("暂存前未能核验作业身份。")
        with self._browser.capture_json_responses(
            ASSIGNMENT_SUBMIT_PATH, form_fields={"pyFlag": "1", **self._form_fields}
        ) as responses:
            with self._draft_scope(url) as controls:
                if not click_draft_save(controls, check_stop=lambda: self._check_identity(url)):
                    raise ChaoxingWrittenStateError("大题已填写，但未找到唯一可用的暂存按钮，请手动保存。")
            self._wait_for_draft_receipt(url, responses)
            if not self._submission_confirmed(responses):
                raise ChaoxingWrittenStateError("大题已填写，但未收到暂存成功确认，请检查页面。")
