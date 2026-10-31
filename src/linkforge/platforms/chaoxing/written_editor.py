"""已观察到的 UEditor/TEX 页面适配；仅通过普通输入和按钮写入。"""

import logging
import re
from dataclasses import dataclass

from linkforge.browser.element import BrowserElement
from linkforge.platforms.chaoxing.exceptions import ChaoxingWrittenStateError

_WRITTEN_TITLE = re.compile(r"^\s*(?:\d+\s*[.．、]\s*)?[（(【\[]?\s*(简答题|计算题)(?=$|[\s,，:：)）】\]])")
logger = logging.getLogger(__name__)


class EditorNotReadyError(ChaoxingWrittenStateError):
    """只读预检可等待的编辑器初始化状态，不用于重放写入。"""


class EditorImagesNotReadyError(EditorNotReadyError):
    def __init__(self, *, broken: int, pending: int) -> None:
        self.broken = broken
        self.pending = pending
        super().__init__(f"大题公式图片未就绪：加载失败 {broken} 张，等待加载 {pending} 张。")


def is_written(element: BrowserElement) -> bool:
    title = element.evaluate("e => e.querySelector('.Zy_TItle,.mark_name')?.textContent || ''")
    return isinstance(title, str) and _WRITTEN_TITLE.match(title) is not None


@dataclass(frozen=True)
class EditorSnapshot:
    text: str
    formulas: tuple[str, ...]

    @property
    def has_content(self) -> bool:
        return bool(self.text or self.formulas)


def normalize_editor_text(text: str) -> str:
    """UEditor 的空段落和公式光标占位不属于答卷正文。"""
    return " ".join(text.replace("\u200b", "").replace("\ufeff", "").split())


_SNAPSHOT = r"""e => {
    const frames = e.querySelectorAll('iframe[id^="ueditor_"]');
    const fields = e.querySelectorAll('textarea[id^="answer"]');
    const counts = {frame_count:frames.length, field_count:fields.length};
    if (frames.length !== 1 || fields.length !== 1) return {...counts, status:'structure'};
    let body;
    try { body = frames[0].contentDocument?.body; }
    catch { return {...counts, status:'inaccessible'}; }
    if (!body || !body.isContentEditable) return {...counts, status:'initializing'};
    const stored = new DOMParser().parseFromString(fields[0].value, 'text/html').body;
    const text = node => (node.innerText || node.textContent || '')
        .replace(/[\u200b\ufeff]/g, '').replace(/\s+/g, ' ').trim();
    const images = [...body.querySelectorAll('img')];
    const formulas = images.map(img => {
        if (!img.classList.contains('ans-latex-moudle')) return null;
        try { const value = JSON.parse(unescape(img.getAttribute('data') || ''));
            return typeof value === 'string' ? value : null; } catch { return null; }
    });
    return {
        ...counts,
        status:'ready',
        text: text(body),
        formulas,
        image_count: images.length,
        invalid_formulas: formulas.filter(value => value === null).length,
        broken_images: images.filter(img => img.complete && img.naturalWidth === 0).length,
        pending_images: images.filter(img => !img.complete).length,
        stored_content: !!text(stored) || !!stored.querySelector('img,video,audio,object'),
        unsupported_elements: body.querySelectorAll(
            'video,audio,canvas,svg,object,embed,table,iframe').length
    };
}"""


class WrittenEditor:
    def __init__(self, element: BrowserElement, *, question_number: int | None = None) -> None:
        self.element = element
        self.question_number = question_number

    def snapshot(self, *, require_images: bool = True, allow_cleared: bool = False) -> EditorSnapshot:
        raw = self.element.evaluate(_SNAPSHOT)
        if not isinstance(raw, dict):
            raise ChaoxingWrittenStateError("大题编辑器检查未返回有效状态，已保留原内容。")

        def count(key: str) -> int:
            value = raw.get(key)
            return value if type(value) is int and value >= 0 else -1

        def fail(reason: str, error: ChaoxingWrittenStateError) -> None:
            # 仅输出程序定义的分类及计数，不记录正文、公式、图片链接或 SDK 异常。
            logger.debug(
                "大题编辑器诊断：question=%s reason=%s frames=%d fields=%d images=%d "
                "invalid_formulas=%d broken_images=%d pending_images=%d unsupported_elements=%d",
                self.question_number,
                reason,
                count("frame_count"),
                count("field_count"),
                count("image_count"),
                count("invalid_formulas"),
                count("broken_images"),
                count("pending_images"),
                count("unsupported_elements"),
            )
            raise error

        if raw.get("status") == "structure":
            frames, fields = count("frame_count"), count("field_count")
            error_type = (
                EditorNotReadyError if frames in (0, 1) and fields in (0, 1) else ChaoxingWrittenStateError
            )
            fail(
                "structure", error_type(f"大题编辑器结构未就绪：正文框 {frames} 个，保存字段 {fields} 个。")
            )
        if raw.get("status") == "inaccessible":
            fail("inaccessible", ChaoxingWrittenStateError("无法读取大题编辑器正文，已保留原内容。"))
        if raw.get("status") == "initializing":
            fail("initializing", EditorNotReadyError("大题编辑器正在初始化，正文尚不可编辑。"))
        if (
            raw.get("status") != "ready"
            or not isinstance(raw.get("text"), str)
            or not isinstance(raw.get("formulas"), list)
            or any(count(key) < 0 for key in ("broken_images", "pending_images", "unsupported_elements"))
        ):
            fail("invalid_state", ChaoxingWrittenStateError("大题编辑器状态数据不完整，已保留原内容。"))
        if any(not isinstance(item, str) for item in raw["formulas"]):
            fail(
                "unrecognized_image",
                ChaoxingWrittenStateError("大题含有普通图片或无法解析的公式数据，已保留原内容。"),
            )
        if count("unsupported_elements"):
            fail(
                "unsupported_content",
                ChaoxingWrittenStateError("大题含有表格、音视频等暂不支持核验的内容，已保留原内容。"),
            )
        if require_images and (count("broken_images") or count("pending_images")):
            fail(
                "images_not_ready",
                EditorImagesNotReadyError(broken=count("broken_images"), pending=count("pending_images")),
            )
        if not allow_cleared and raw.get("stored_content") and not raw["text"] and not raw["formulas"]:
            fail("restoring", EditorNotReadyError("大题已有保存内容，正在等待编辑器恢复。"))
        return EditorSnapshot(raw["text"], tuple(raw["formulas"]))

    def body(self) -> BrowserElement:
        frames = self.element.query_all('iframe[id^="ueditor_"]')
        if len(frames) != 1:
            raise ChaoxingWrittenStateError("大题编辑器不唯一。")
        bodies = frames[0].frame_query_all('body[contenteditable="true"]')
        if len(bodies) != 1:
            raise ChaoxingWrittenStateError("大题正文尚未就绪。")
        return bodies[0]

    def saved_copy_matches(self) -> bool:
        """确认编辑器内容确实同步到了用于暂存的 textarea，而非只显示在 iframe。"""
        return (
            self.element.evaluate(r"""e => {
            const body = e.querySelector('iframe[id^="ueditor_"]')?.contentDocument?.body;
            const field = e.querySelector('textarea[id^="answer"]');
            if (!body || !field) return false;
            const stored = new DOMParser().parseFromString(field.value, 'text/html').body;
            const text = node => (node.textContent || '').replace(/[\s\u200b\ufeff]/g, '');
            const formulas = node => [...node.querySelectorAll('img')].map(i => {
                if (!i.classList.contains('ans-latex-moudle')) return null;
                try { const value = JSON.parse(unescape(i.getAttribute('data') || ''));
                    return typeof value === 'string' ? value : null; } catch { return null; }
            });
            const shown = formulas(body), saved = formulas(stored);
            return text(body) === text(stored)
                && !saved.includes(null) && JSON.stringify(shown) === JSON.stringify(saved);
        }""")
            is True
        )

    def append_text(self, text: str, *, first: bool) -> None:
        body = self.body()
        body.press("ControlOrMeta+End")
        if not first:
            body.press("Enter")
        body.type_text(text)

    def audit_screenshots(self) -> tuple[bytes, ...]:
        """正常移动光标以获取编辑器首尾视图；完整正文和公式另外作为审核输入。"""
        frames = self.element.query_all('iframe[id^="ueditor_"]')
        if len(frames) != 1:
            raise ChaoxingWrittenStateError("审核时大题编辑器不唯一。")
        frame = frames[0]
        body = self.body()
        body.press("ControlOrMeta+Home")
        images = [frame.screenshot()]
        body.press("ControlOrMeta+End")
        if body.evaluate("e => e.ownerDocument.scrollingElement.scrollTop > 0") is True:
            images.append(frame.screenshot())
        return tuple(images)

    def clear(self) -> None:
        body = self.body()
        body.press("ControlOrMeta+A")
        body.press("Backspace")
        if (
            body.evaluate(
                r"e => !(e.innerText || '').replace(/[\s\u200b\ufeff]/g, '') && !e.querySelector('img')"
            )
            is not True
        ):
            raise ChaoxingWrittenStateError("旧答案未能完整清空，已停止写入，请检查页面。")

    def open_formula(self) -> None:
        body = self.body()
        body.press("ControlOrMeta+End")
        body.press("Enter")
        controls = self.element.query_all('[title="TEX"]')
        if len(controls) != 1:
            raise ChaoxingWrittenStateError("未找到唯一的 TEX 公式按钮，已保留当前草稿。")
        containers = self.element.query_all(".edui-editor")
        if len(containers) > 1:
            raise ChaoxingWrittenStateError("大题编辑器容器不唯一，已保留当前草稿。")
        if containers:
            # UEditor autofloat 将工具栏固定在 top:0，可能被作业页顶栏持续遮挡。
            # 对 fixed 按钮 scrollIntoView 不会移动它；先滚动正常文档流中的编辑器起点，
            # 由页面自己的 scroll 处理退出吸顶，再通过正常点击打开 TEX。
            containers[0].evaluate("""e => {
                const view = e.ownerDocument.defaultView;
                view.scrollBy({top:e.getBoundingClientRect().top-view.innerHeight/3, behavior:'instant'});
            }""")
        controls[0].scroll_into_view()
        controls[0].click()
