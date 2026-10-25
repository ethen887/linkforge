"""已观察到的 UEditor/TEX 页面适配；仅通过普通输入和按钮写入。"""

import re
from dataclasses import dataclass

from linkforge.browser.element import BrowserElement
from linkforge.platforms.chaoxing.exceptions import ChaoxingWrittenStateError

_WRITTEN_TITLE = re.compile(r"^\s*(?:\d+\s*[.．、]\s*)?[（(【\[]?\s*(简答题|计算题)(?=$|[\s,，:：)）】\]])")


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
    if (frames.length !== 1 || fields.length !== 1) return null;
    const body = frames[0].contentDocument?.body;
    if (!body || !body.isContentEditable) return null;
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
        text: text(body),
        formulas,
        ready: images.every(img => img.complete && img.naturalWidth > 0),
        stored_content: !!text(stored) || !!stored.querySelector('img,video,audio,object'),
        unsupported: !!body.querySelector('video,audio,canvas,svg,object,embed,table,iframe')
    };
}"""


class WrittenEditor:
    def __init__(self, element: BrowserElement) -> None:
        self.element = element

    def snapshot(self, *, require_images: bool = True, allow_cleared: bool = False) -> EditorSnapshot:
        raw = self.element.evaluate(_SNAPSHOT)
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("text"), str)
            or not isinstance(raw.get("formulas"), list)
            or any(not isinstance(item, str) for item in raw["formulas"])
            or raw.get("unsupported") is not False
        ):
            raise ChaoxingWrittenStateError("大题编辑器未适配，或包含不能自动核验的内容；已保留原内容。")
        if require_images and raw.get("ready") is not True:
            raise ChaoxingWrittenStateError("大题公式图片尚未加载完成，请检查页面。")
        if not allow_cleared and raw.get("stored_content") and not raw["text"] and not raw["formulas"]:
            raise ChaoxingWrittenStateError("大题已有保存内容，但编辑器尚未恢复，请检查页面。")
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
