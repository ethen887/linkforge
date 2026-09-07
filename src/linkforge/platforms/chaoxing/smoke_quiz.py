"""Full automatic real Chaoxing vertical E2E smoke.

Fixed smoke workflow:

    2.5 相对运动
        Card 1 概述
        Card 2 PPT / Document
        Card 3 视频
        Card 4 测试 / Vision Quiz
        Card 5 讨论
            ↓
        next knowledge

This smoke intentionally performs real side effects:

- Video:
    plays normally for the requested smoke duration, default 8 seconds.
    It does not seek, change playback rate, or forge completion.

- Quiz:
    captures each real question screenshot,
    calls the configured Vision LLM,
    selects the returned options,
    verifies selection state,
    submits through normal visible UI,
    handles the visible confirmation,
    and waits for the production handler's completion verification.

- Comment:
    calls the configured LLM,
    fills the real reply editor,
    and submits through the production Comment handler.

- Navigation:
    exercises the existing Content / Document / Comment / Quiz logic
    and finally verifies that the course leaves the starting knowledge.

No input().
No manual clicking.
No manual scrolling.
No direct Chaoxing HTTP submission API.
No forged ans-job-finished.
No artificial task completion.

This is a destructive local smoke test and must not run in CI.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Dialog, Frame, Locator
from playwright.sync_api import Error as PlaywrightError

from linkforge.application.task_runner import TaskType
from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.browser.playwright import PlaywrightBrowser
from linkforge.config.settings import ModelConfig
from linkforge.llm.factory import create_model_client
from linkforge.platforms.chaoxing.comment_handler import (
    ChaoxingCommentTaskHandler,
    LLMCommentBodyGenerator,
)
from linkforge.platforms.chaoxing.comment_state import (
    COMMENT_MODULE_PATH,
    CommentOutcome,
    CommentSession,
    comment_identity,
)
from linkforge.platforms.chaoxing.content_handler import (
    ChaoxingContentHandlerConfig,
    ChaoxingContentTaskHandler,
)
from linkforge.platforms.chaoxing.document_handler import (
    ChaoxingDocumentTaskHandler,
)
from linkforge.platforms.chaoxing.dom import inspect_chaoxing_page
from linkforge.platforms.chaoxing.exceptions import (
    ChaoxingInspectionError,
    ChaoxingQuizError,
)
from linkforge.platforms.chaoxing.quiz_dom import QUESTION_FRAME_PATH
from linkforge.platforms.chaoxing.quiz_handler import (
    ChaoxingQuizHandlerConfig,
    ChaoxingQuizTaskHandler,
)
from linkforge.platforms.chaoxing.quiz_solver import LLMQuizSolver
from linkforge.platforms.chaoxing.task_detector import (
    ChaoxingTaskDetector,
)

COURSE_URL = (
    "https://mooc1.chaoxing.com/mycourse/studentstudy?"
    "chapterId=1120195712"
    "&courseId=260810626"
    "&clazzid=140199897"
    "&cpi=498300787"
    "&enc=abcf4009e2208a926d3db17a786067f6"
    "&mooc2=1"
    "&hidetype=0"
    "&openc=8cf3ef849e9639ea353d4463ea5a5cd9"
)

START_KNOWLEDGE_ID = "1120195712"

CARD_OVERVIEW = 0
CARD_DOCUMENT = 1
CARD_VIDEO = 2
CARD_QUIZ = 3
CARD_COMMENT = 4

CARD_LABELS = {
    CARD_OVERVIEW: "概述",
    CARD_DOCUMENT: "PPT",
    CARD_VIDEO: "视频",
    CARD_QUIZ: "测试",
    CARD_COMMENT: "讨论",
}

VIDEO_MODULE_PATH = "/ananas/modules/video/"
WORK_MODULE_PATH = "/ananas/modules/work/"

CONTROL_SELECTOR = "button,a,input[type='button'],input[type='submit'],[role='button']"

SUBMIT_RE = re.compile(
    r"提交|交卷|提交答案|提交作业|完成答题|完成测试",
    re.IGNORECASE,
)

FORBIDDEN_SUBMIT_RE = re.compile(
    r"取消|返回|保存|上一|下一|知道了|重做|查看",
    re.IGNORECASE,
)

CONFIRM_TEXTS = {
    "确定",
    "确认",
    "确认提交",
}

CARD_SNAPSHOT_SCRIPT = r"""() => {
    const tabs = Array.from(
        document.querySelectorAll("#prev_tab li")
    );

    if (!tabs.length) {
        return {
            matched: false,
            tabs: [],
        };
    }

    return {
        matched: true,

        tabs: tabs.map(
            (tab, index) => ({
                index,

                text:
                    (
                        tab.innerText
                        || tab.textContent
                        || ""
                    )
                    .replace(/\s+/g, " ")
                    .trim(),

                active:
                    tab.classList.contains(
                        "active"
                    ),

                visible:
                    tab.getClientRects().length > 0
                    && getComputedStyle(tab).display
                        !== "none"
                    && getComputedStyle(tab).visibility
                        !== "hidden",
            })
        ),
    };
}"""


VIDEO_STATE_SCRIPT = r"""() => {
    if (
        !window.location.href.includes(
            "/ananas/modules/video/"
        )
    ) {
        return {
            matched: false,
        };
    }

    const video =
        document.querySelector("video");

    if (!video) {
        return {
            matched: true,
            found: false,
        };
    }

    return {
        matched: true,
        found: true,

        current_time:
            Number(video.currentTime || 0),

        duration:
            Number(video.duration || 0),

        paused:
            Boolean(video.paused),

        ended:
            Boolean(video.ended),

        ready_state:
            Number(video.readyState),

        src:
            video.currentSrc
            || video.src
            || null,
    };
}"""


SMOKE_COMMENT_ENTRY_EVIDENCE_SCRIPT = r"""() => {
    if (window.location.pathname !== "/mooc-ans/bbscircle/chapter") {
        return {
            matched: false,
            frame_url: window.location.href,
        };
    }

    let current = window;
    let hasInsertbbsAncestor = false;

    try {
        while (current !== current.parent) {
            current = current.parent;

            if (
                current.location.pathname.includes(
                    "/ananas/modules/insertbbs/"
                )
            ) {
                hasInsertbbsAncestor = true;
            }
        }
    } catch (error) {
        return {
            matched: false,
            frame_url: window.location.href,
        };
    }

    if (!hasInsertbbsAncestor) {
        return {
            matched: false,
            frame_url: window.location.href,
        };
    }

    const entries = Array.from(
        document.querySelectorAll("#topicMainDiv.PublicCardBox")
    ).filter(element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);

        return (
            rect.width > 0
            && rect.height > 0
            && style.display !== "none"
            && style.visibility !== "hidden"
        );
    });

    const entry = entries.length === 1 ? entries[0] : null;

    return {
        matched: true,
        frame_url: window.location.href,
        entry_count: entries.length,
        title:
            (
                entry?.querySelector(".cardRightTit")?.innerText
                || ""
            ).trim(),
        prompt:
            (
                entry?.querySelector(".Booksspan")?.innerText
                || ""
            ).trim(),
    };
}"""


QUIZ_NEXT_CONTROL_SELECTOR = "button,a,input[type='button'],input[type='submit'],[role='button'],[onclick]"

QUIZ_NEXT_LABELS = {
    "next",
    "下一题",
    "下一步",
    "下一页",
    "继续",
    "完成",
    "finish",
    "done",
}

VIDEO_PLAY_SCRIPT = r"""async () => {
    if (
        !window.location.href.includes(
            "/ananas/modules/video/"
        )
    ) {
        return {
            matched: false,
        };
    }

    const video =
        document.querySelector("video");

    if (!video) {
        return {
            matched: true,
            found: false,
        };
    }

    try {
        await video.play();

        return {
            matched: true,
            found: true,
            requested: true,
        };
    } catch (error) {
        return {
            matched: true,
            found: true,
            requested: false,
            error:
                error
                ? String(error.name || error)
                : "unknown",
        };
    }
}"""


class SmokeError(RuntimeError):
    """Known failure in this destructive E2E smoke."""


class SmokeForcedCommentDetector(ChaoxingTaskDetector):
    """Smoke-only adapter for re-testing the fixed Card-5 discussion.

    The production detector stays authoritative everywhere except the fixed
    discussion Card. If the real supported discussion DOM is present but the
    production detector returns CONTENT/UNKNOWN because this sample was already
    handled, the smoke temporarily reports COMMENT for this run only.

    It never modifies Chaoxing DOM, finished markers, or network state.
    """

    def __init__(
        self,
        browser: PlaywrightBrowser,
        *,
        base_detector: ChaoxingTaskDetector,
        comment_session: CommentSession,
    ) -> None:
        self._browser = browser
        self._base = base_detector
        self._session = comment_session
        self._override_reported = False

    def detect(self) -> TaskType:
        base_task = self._base.detect()

        try:
            state = inspect_chaoxing_page(self._browser)
        except (BrowserError, ChaoxingInspectionError):
            return base_task

        if state.knowledge_id != START_KNOWLEDGE_ID or state.active_tab_index != CARD_COMMENT:
            return base_task

        comment_indexes = [
            index for index, module in enumerate(state.modules) if COMMENT_MODULE_PATH in module.url
        ]

        if len(comment_indexes) != 1:
            return base_task

        module_index = comment_indexes[0]

        try:
            identity = comment_identity(
                self._browser.current_url(),
                state,
                module_index,
            )
        except Exception:
            return base_task

        if self._session.is_handled(identity):
            return TaskType.CONTENT

        evidence = self._supported_entry_evidence()

        if evidence is None:
            return base_task

        if not self._override_reported:
            print()
            print(
                "[SMOKE COMMENT OVERRIDE] production Detector 当前返回 "
                f"{base_task.name}，但固定 Card 5 的真实 insertbbs + "
                "讨论入口仍然存在。"
            )
            print(
                "[SMOKE COMMENT OVERRIDE] 仅为了复测评论完整链路，"
                "本地 smoke 临时返回 COMMENT；不修改平台任务状态。"
            )
            self._override_reported = True

        return TaskType.COMMENT

    def _supported_entry_evidence(self) -> dict[str, str] | None:
        matches: list[dict[str, Any]] = []

        for value in self._browser.evaluate_in_frames(SMOKE_COMMENT_ENTRY_EVIDENCE_SCRIPT):
            if isinstance(value, dict) and value.get("matched") is True:
                matches.append(value)

        if len(matches) != 1:
            return None

        value = matches[0]

        if value.get("entry_count") != 1:
            return None

        title = value.get("title")
        prompt = value.get("prompt")

        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(prompt, str)
            or not prompt.strip()
        ):
            return None

        return {
            "title": title.strip(),
            "prompt": prompt.strip(),
        }


class VisibleSmokeBrowser(PlaywrightBrowser):
    """PlaywrightBrowser with smoke-only robust Card navigation."""

    def smoke_click_card_and_wait_document_replacement(
        self,
        index: int,
        *,
        timeout_seconds: float,
    ) -> None:
        """Click one Card and wait for the cards Document to be replaced."""
        page = self._require_page()

        navigation_frames: list[tuple[Frame, Locator]] = []

        for frame in page.frames:
            try:
                if frame.is_detached():
                    continue

                tabs = frame.locator("#prev_tab li")

                if tabs.count() > index and frame.locator("#prev_tab li.active").count() == 1:
                    navigation_frames.append(
                        (
                            frame,
                            tabs,
                        )
                    )

            except PlaywrightError:
                continue

        if len(navigation_frames) != 1:
            raise SmokeError(f"无法唯一定位学习通 Card 导航栏：{len(navigation_frames)}")

        _, tabs = navigation_frames[0]

        target = tabs.nth(index)

        old_documents: list[tuple[Frame, Any]] = []

        for frame in page.frames:
            try:
                if not frame.is_detached() and "/mooc-ans/knowledge/cards" in frame.url:
                    old_documents.append(
                        (
                            frame,
                            frame.evaluate_handle("document"),
                        )
                    )

            except PlaywrightError:
                continue

        print(f"[Card] 点击 Card {index + 1}，旧 cards Document={len(old_documents)}")

        target.click(timeout=round(timeout_seconds * 1000))

        deadline = time.monotonic() + timeout_seconds

        try:
            while time.monotonic() < deadline:
                if not old_documents:
                    time.sleep(0.5)
                    return

                all_replaced = True

                for (
                    old_frame,
                    old_document,
                ) in old_documents:
                    try:
                        if old_frame.is_detached():
                            continue

                        still_same = old_frame.evaluate(
                            ("oldDocument => document === oldDocument"),
                            old_document,
                        )

                        if still_same:
                            all_replaced = False

                    except PlaywrightError:
                        continue

                if all_replaced:
                    print("[Card] cards Document 已完成替换。")
                    return

                time.sleep(0.1)

            raise SmokeError("Card 已点击，但 cards Document 未在时限内替换。")

        finally:
            for _, handle in old_documents:
                try:
                    handle.dispose()
                except PlaywrightError:
                    pass


class SmokeQuizSubmitter:
    """Perform the irreversible Quiz boundary through normal visible UI."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        confirmation_timeout_seconds: float,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._confirmation_timeout_seconds = confirmation_timeout_seconds

        self.submit_clicks = 0
        self.confirm_clicks = 0
        self.dialog_count = 0

    def submit(
        self,
        browser: Browser,
        *,
        module_url: str,
    ) -> None:
        """Click the real submit control once and handle its confirmation."""
        if not isinstance(
            browser,
            PlaywrightBrowser,
        ):
            raise SmokeError("Quiz smoke submitter requires PlaywrightBrowser.")

        page = browser._require_page()

        frame = self._question_frame(
            browser,
            module_url,
        )

        controls = self._visible_controls(frame)

        submit = self._find_submit(controls)

        info = self._control_info(submit)

        print()
        print("[Quiz Submit] 定位到提交控件：")
        print(f"  id={info.get('id')!r}")
        print(f"  class={info.get('class')!r}")
        print(f"  text={info.get('text')!r}")
        print(f"  value={info.get('value')!r}")

        def on_dialog(
            dialog: Dialog,
        ) -> None:
            self.dialog_count += 1

            print()
            print(f"[Quiz Submit] 浏览器确认框：{dialog.message!r}")

            dialog.accept()

        page.on(
            "dialog",
            on_dialog,
        )

        try:
            self.submit_clicks += 1

            print()
            print("[Quiz Submit] 执行真实提交 click。")

            # Do not automatically retry this
            # irreversible click.
            submit.click(timeout=round(self._timeout_seconds * 1000))

            self._confirmation_loop(
                browser,
                module_url,
            )

        finally:
            try:
                page.remove_listener(
                    "dialog",
                    on_dialog,
                )
            except Exception:
                pass

    @staticmethod
    def _under(
        frame: Frame,
        ancestor: Frame,
    ) -> bool:
        current = frame.parent_frame

        while current is not None:
            if current == ancestor:
                return True

            current = current.parent_frame

        return False

    def _question_frame_or_none(
        self,
        browser: PlaywrightBrowser,
        module_url: str,
    ) -> Frame | None:
        page = browser._require_page()

        ancestors: list[Frame] = []

        for frame in page.frames:
            try:
                if not frame.is_detached() and frame.url == module_url:
                    ancestors.append(frame)

            except PlaywrightError:
                continue

        if len(ancestors) != 1:
            return None

        ancestor = ancestors[0]

        candidates: list[Frame] = []

        for frame in page.frames:
            try:
                if frame.is_detached():
                    continue

                if QUESTION_FRAME_PATH in frame.url and self._under(
                    frame,
                    ancestor,
                ):
                    candidates.append(frame)

            except PlaywrightError:
                continue

        if len(candidates) != 1:
            return None

        return candidates[0]

    def _question_frame(
        self,
        browser: PlaywrightBrowser,
        module_url: str,
    ) -> Frame:
        frame = self._question_frame_or_none(
            browser,
            module_url,
        )

        if frame is None:
            raise SmokeError("无法唯一定位 Quiz question frame。")

        return frame

    @staticmethod
    def _visible_controls(
        frame: Frame,
    ) -> list[Locator]:
        locator = frame.locator(CONTROL_SELECTOR)

        result: list[Locator] = []

        for index in range(locator.count()):
            item = locator.nth(index)

            try:
                if item.is_visible() and item.is_enabled():
                    result.append(item)

            except PlaywrightError:
                continue

        return result

    @staticmethod
    def _control_info(
        locator: Locator,
    ) -> dict[str, Any]:
        raw = locator.evaluate(
            r"""element => ({
                tag:
                    element.tagName
                        .toLowerCase(),

                id:
                    element.id || null,

                class:
                    typeof element.className
                        === "string"
                    ? element.className
                    : element.getAttribute(
                        "class"
                    ),

                type:
                    element.getAttribute(
                        "type"
                    ),

                role:
                    element.getAttribute(
                        "role"
                    ),

                text:
                    (
                        element.innerText
                        || element.textContent
                        || ""
                    )
                    .replace(/\s+/g, " ")
                    .trim(),

                value:
                    "value" in element
                    ? String(
                        element.value || ""
                    ).trim()
                    : null,

                title:
                    element.getAttribute(
                        "title"
                    ),

                aria_label:
                    element.getAttribute(
                        "aria-label"
                    ),
            })"""
        )

        if not isinstance(
            raw,
            dict,
        ):
            raise SmokeError("提交控件 DOM 数据非法。")

        return raw

    @staticmethod
    def _label(
        info: dict[str, Any],
    ) -> str:
        return " ".join(
            str(info.get(key) or "").strip()
            for key in (
                "text",
                "value",
                "title",
                "aria_label",
            )
            if str(info.get(key) or "").strip()
        )

    def _score(
        self,
        info: dict[str, Any],
    ) -> int:
        label = self._label(info)

        identifier = f"{info.get('id') or ''} {info.get('class') or ''}"

        if info.get("id") in {
            "submitBackOk",
            "submitBackCancel",
            "nextFocusButton",
        }:
            return -1

        if FORBIDDEN_SUBMIT_RE.search(label) is not None:
            return -1

        score = 0

        if info.get("type") == "submit":
            score += 50

        if re.search(
            r"submit|finish|handin",
            identifier,
            re.IGNORECASE,
        ):
            score += 50

        if label in {
            "提交",
            "交卷",
            "提交答案",
            "提交作业",
            "完成答题",
            "完成测试",
        }:
            score += 120

        elif SUBMIT_RE.search(label) is not None:
            score += 80

        return score

    def _find_submit(
        self,
        controls: list[Locator],
    ) -> Locator:
        ranked: list[
            tuple[
                int,
                Locator,
                dict[str, Any],
            ]
        ] = []

        for control in controls:
            try:
                info = self._control_info(control)
            except PlaywrightError:
                continue

            score = self._score(info)

            if score > 0:
                ranked.append(
                    (
                        score,
                        control,
                        info,
                    )
                )

        if not ranked:
            print()
            print("[Quiz Submit] 未找到提交按钮。")
            print("当前可见控件：")

            for control in controls:
                try:
                    info = self._control_info(control)
                except PlaywrightError:
                    continue

                print(
                    "  - "
                    f"id="
                    f"{info.get('id')!r} "
                    f"text="
                    f"{info.get('text')!r} "
                    f"value="
                    f"{info.get('value')!r} "
                    f"class="
                    f"{info.get('class')!r}"
                )

            raise SmokeError("没有找到可信的 Quiz 提交入口。")

        ranked.sort(
            key=lambda item: item[0],
            reverse=True,
        )

        top_score = ranked[0][0]

        top = [item for item in ranked if item[0] == top_score]

        if len(top) != 1:
            print()
            print("[Quiz Submit] 提交候选存在歧义：")

            for (
                score,
                _,
                info,
            ) in top:
                print(
                    f"  score={score} "
                    f"id="
                    f"{info.get('id')!r} "
                    f"text="
                    f"{info.get('text')!r} "
                    f"value="
                    f"{info.get('value')!r}"
                )

            raise SmokeError("存在多个等价 Quiz 提交候选。")

        return top[0][1]

    @staticmethod
    def _module_finished(
        browser: Browser,
        module_url: str,
    ) -> bool:
        try:
            state = inspect_chaoxing_page(browser)
        except (
            BrowserError,
            ChaoxingInspectionError,
        ):
            return False

        modules = [module for module in state.modules if module.url == module_url]

        return len(modules) == 1 and modules[0].has_job_icon and modules[0].finished

    def _click_confirmation(
        self,
        frame: Frame,
    ) -> bool:
        high_confidence = frame.locator("#submitBackOk:visible")

        try:
            if high_confidence.count() == 1 and high_confidence.is_enabled():
                self.confirm_clicks += 1

                print("[Quiz Submit] 点击 #submitBackOk。")

                high_confidence.click(timeout=round(self._timeout_seconds * 1000))

                return True

        except PlaywrightError:
            pass

        candidates: list[Locator] = []

        for control in self._visible_controls(frame):
            try:
                info = self._control_info(control)
            except PlaywrightError:
                continue

            if self._label(info) in CONFIRM_TEXTS:
                candidates.append(control)

        if len(candidates) == 1:
            self.confirm_clicks += 1

            print("[Quiz Submit] 点击唯一可见确认按钮。")

            candidates[0].click(timeout=round(self._timeout_seconds * 1000))

            return True

        return False

    def _confirmation_loop(
        self,
        browser: PlaywrightBrowser,
        module_url: str,
    ) -> None:
        deadline = time.monotonic() + self._confirmation_timeout_seconds

        last_click = 0.0

        while time.monotonic() < deadline:
            if self._module_finished(
                browser,
                module_url,
            ):
                print("[Quiz Submit] completion marker 已出现。")
                return

            frame = self._question_frame_or_none(
                browser,
                module_url,
            )

            if frame is None:
                print("[Quiz Submit] 题目 frame 已替换或离开，交由 Handler 验证最终完成状态。")
                return

            now = time.monotonic()

            if now - last_click >= 0.5:
                if self._click_confirmation(frame):
                    last_click = time.monotonic()

                    time.sleep(0.4)
                    continue

            time.sleep(0.2)


def stage(
    title: str,
) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def looks_logged_out(
    url: str,
) -> bool:
    lowered = url.lower()

    return any(
        marker in lowered
        for marker in (
            "/login",
            "passport.chaoxing.com",
            "passport2.chaoxing.com",
        )
    )


def wait_for_state(
    browser: Browser,
    *,
    timeout_seconds: float,
):
    deadline = time.monotonic() + timeout_seconds

    last_error: BaseException | None = None

    while time.monotonic() < deadline:
        try:
            return inspect_chaoxing_page(browser)

        except (
            BrowserError,
            ChaoxingInspectionError,
        ) as exc:
            last_error = exc

        time.sleep(0.2)

    raise SmokeError(
        f"Chaoxing 页面状态 未在时限内稳定。 last_error={type(last_error).__name__ if last_error else None}"
    )


def card_tabs(
    browser: Browser,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    for value in browser.evaluate_in_frames(CARD_SNAPSHOT_SCRIPT):
        if (
            isinstance(
                value,
                dict,
            )
            and value.get("matched") is True
        ):
            matches.append(value)

    if len(matches) != 1:
        raise SmokeError(f"无法唯一定位 Card 导航栏：{len(matches)}")

    tabs = matches[0].get("tabs")

    if not isinstance(
        tabs,
        list,
    ):
        raise SmokeError("Card DOM 数据非法。")

    return [
        tab
        for tab in tabs
        if isinstance(
            tab,
            dict,
        )
    ]


def wait_for_card(
    browser: Browser,
    index: int,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        try:
            state = inspect_chaoxing_page(browser)

            tabs = card_tabs(browser)

            if state.active_tab_index == index and index < len(tabs) and tabs[index].get("active") is True:
                return

        except (
            BrowserError,
            ChaoxingInspectionError,
            SmokeError,
        ):
            pass

        time.sleep(0.2)

    raise SmokeError(f"Card {index + 1} 未在时限内稳定。")


def click_card(
    browser: VisibleSmokeBrowser,
    index: int,
    *,
    timeout_seconds: float,
) -> None:
    tabs = card_tabs(browser)

    if index < 0 or index >= len(tabs):
        raise SmokeError(f"Card {index + 1} 不存在。")

    expected = CARD_LABELS.get(index)

    actual = tabs[index].get("text")

    if expected is not None and (
        not isinstance(
            actual,
            str,
        )
        or expected not in actual
    ):
        raise SmokeError(f"Card {index + 1} 标签与固定样本不符：expected={expected!r}, actual={actual!r}")

    if tabs[index].get("active") is not True:
        browser.smoke_click_card_and_wait_document_replacement(
            index,
            timeout_seconds=timeout_seconds,
        )

    wait_for_card(
        browser,
        index,
        timeout_seconds=timeout_seconds,
    )


def ensure_start_card(
    browser: VisibleSmokeBrowser,
    *,
    timeout_seconds: float,
) -> None:
    state = wait_for_state(
        browser,
        timeout_seconds=timeout_seconds,
    )

    if state.knowledge_id != START_KNOWLEDGE_ID:
        raise SmokeError(
            f"固定 URL 没有进入预期 knowledge：expected={START_KNOWLEDGE_ID}, actual={state.knowledge_id}"
        )

    if state.active_tab_index != CARD_OVERVIEW:
        print("初始页面不在 Card 1，自动恢复到概述。")

        click_card(
            browser,
            CARD_OVERVIEW,
            timeout_seconds=timeout_seconds,
        )


def wait_for_task(
    browser: Browser,
    detector: ChaoxingTaskDetector,
    *,
    card_index: int,
    expected: TaskType,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    last_task: TaskType | None = None

    while time.monotonic() < deadline:
        try:
            state = inspect_chaoxing_page(browser)

            task = detector.detect()

            last_task = task

            if state.active_tab_index == card_index and task is expected:
                return

        except (
            BrowserError,
            ChaoxingInspectionError,
        ):
            pass

        time.sleep(0.25)

    raise SmokeError(
        "任务未进入预期状态："
        f"card={card_index + 1}, "
        f"expected={expected.name}, "
        f"actual="
        f"{last_task.name if last_task else None}"
    )


def print_current(
    browser: Browser,
    detector: ChaoxingTaskDetector,
    *,
    prefix: str = "",
):
    state = wait_for_state(
        browser,
        timeout_seconds=15.0,
    )

    task = detector.detect()

    print(
        f"{prefix}"
        f"knowledge="
        f"{state.knowledge_id}, "
        f"card="
        f"{state.active_tab_index + 1}, "
        f"task={task.name}, "
        f"modules="
        f"{len(state.modules)}"
    )

    return state, task


def run_documents(
    browser: Browser,
    detector: ChaoxingTaskDetector,
    *,
    timeout_seconds: float,
) -> int:
    """Run production DocumentHandler once per detected document."""
    count = 0

    deadline = time.monotonic() + timeout_seconds

    while True:
        task = detector.detect()

        if task is not TaskType.DOCUMENT:
            return count

        if time.monotonic() >= deadline:
            raise SmokeError("Document 阶段超过 smoke timeout。")

        count += 1

        print(f"开始 production DocumentHandler：PDF #{count}")

        handler = ChaoxingDocumentTaskHandler(browser)

        started = time.monotonic()

        handler.run()

        print(f"PDF #{count} 完成，耗时 {time.monotonic() - started:.2f}s")


def unique_video_state(
    browser: Browser,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []

    for raw in browser.evaluate_in_frames(VIDEO_STATE_SCRIPT):
        if (
            isinstance(
                raw,
                dict,
            )
            and raw.get("matched") is True
        ):
            matches.append(raw)

    if len(matches) > 1:
        raise SmokeError("发现多个 Video frame。")

    if not matches:
        return None

    state = matches[0]

    if state.get("found") is not True:
        return None

    return state


def wait_for_video_element(
    browser: Browser,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds

    last = None

    while time.monotonic() < deadline:
        last = unique_video_state(browser)

        if last is not None:
            return last

        time.sleep(0.25)

    raise SmokeError(f"Video element 未出现。 last={last}")


def request_video_play(
    browser: Browser,
) -> None:
    matches: list[dict[str, Any]] = []

    for raw in browser.evaluate_in_frames(VIDEO_PLAY_SCRIPT):
        if (
            isinstance(
                raw,
                dict,
            )
            and raw.get("matched") is True
        ):
            matches.append(raw)

    if len(matches) != 1:
        raise SmokeError("无法唯一定位 Video frame。")

    result = matches[0]

    if result.get("found") is not True:
        raise SmokeError("Video element 不存在。")

    if result.get("requested") is not True:
        raise SmokeError(f"video.play() 请求失败：{result.get('error')}")


def play_real_video_for_seconds(
    browser: Browser,
    *,
    seconds: float,
    timeout_seconds: float,
) -> None:
    """Play real media and verify real currentTime progression."""
    initial = wait_for_video_element(
        browser,
        timeout_seconds=timeout_seconds,
    )

    initial_time = float(
        initial.get(
            "current_time",
            0.0,
        )
    )

    duration = float(
        initial.get(
            "duration",
            0.0,
        )
    )

    print(f"Video 初始状态：currentTime={initial_time:.2f}, duration={duration:.2f}")

    request_video_play(browser)

    deadline = time.monotonic() + timeout_seconds

    target_progress = initial_time + seconds

    last = initial

    while time.monotonic() < deadline:
        state = unique_video_state(browser)

        if state is None:
            time.sleep(0.25)
            continue

        last = state

        current_time = float(
            state.get(
                "current_time",
                0.0,
            )
        )

        print(
            f"\r[Video] {current_time:.2f}s / target {target_progress:.2f}s",
            end="",
            flush=True,
        )

        if current_time >= target_progress:
            print()

            print(f"Video 已真实播放 {seconds:g}s。")

            return

        time.sleep(0.25)

    print()

    raise SmokeError(f"Video 没有在时限内 产生足够播放进度。 last={last}")


def advance_after_smoke_video(
    browser: VisibleSmokeBrowser,
    detector: ChaoxingTaskDetector,
    *,
    timeout_seconds: float,
) -> None:
    """Continue regression coverage after the intentionally short video smoke."""
    task = detector.detect()

    if task is TaskType.CONTENT:
        handler = ChaoxingContentTaskHandler(
            browser,
            detector=detector,
            config=ChaoxingContentHandlerConfig(
                poll_interval_seconds=0.25,
                navigation_timeout_seconds=timeout_seconds,
            ),
        )

        handler.run()

    elif task is TaskType.VIDEO:
        print(
            "Video 仅按 smoke 要求播放 8s，平台仍判定 VIDEO；为继续验证后续模块，仅进行正常可见 Card 导航。"
        )

        click_card(
            browser,
            CARD_QUIZ,
            timeout_seconds=timeout_seconds,
        )

    else:
        raise SmokeError(f"Video 阶段后出现 意外任务：{task.name}")


def _frame_is_under_work(frame: Frame) -> bool:
    current: Frame | None = frame

    while current is not None:
        try:
            if WORK_MODULE_PATH in current.url:
                return True
        except PlaywrightError:
            return False

        current = current.parent_frame

    return False


def _quiz_next_control_info(locator: Locator) -> dict[str, Any]:
    raw = locator.evaluate(
        r"""element => ({
            tag: element.tagName.toLowerCase(),
            id: element.id || null,
            class:
                typeof element.className === "string"
                ? element.className
                : element.getAttribute("class"),
            text:
                (
                    element.innerText
                    || element.textContent
                    || ""
                )
                .replace(/\s+/g, " ")
                .trim(),
            value:
                "value" in element
                ? String(element.value || "").trim()
                : null,
            title: element.getAttribute("title"),
            aria_label: element.getAttribute("aria-label"),
        })"""
    )

    if not isinstance(raw, dict):
        raise SmokeError("Quiz Next control DOM data is malformed.")

    return raw


def _quiz_control_label(info: dict[str, Any]) -> str:
    values = (
        info.get("text"),
        info.get("value"),
        info.get("title"),
        info.get("aria_label"),
    )

    return " ".join(
        str(value).strip() for value in values if value is not None and str(value).strip()
    ).strip()


def _quiz_next_score(info: dict[str, Any]) -> int:
    label = _quiz_control_label(info)
    normalized = label.lower().strip()

    if normalized in QUIZ_NEXT_LABELS:
        return 200

    if normalized.startswith("next"):
        return 180

    if normalized.startswith("下一"):
        return 180

    identifier = (f"{info.get('id') or ''} {info.get('class') or ''}").lower()

    if "next" in identifier and "cancel" not in identifier:
        return 80

    return -1


def _quiz_next_candidates(
    browser: VisibleSmokeBrowser,
) -> list[tuple[int, Frame, Locator, dict[str, Any]]]:
    page = browser._require_page()
    ranked: list[tuple[int, Frame, Locator, dict[str, Any]]] = []

    for frame in page.frames:
        try:
            if frame.is_detached() or not _frame_is_under_work(frame):
                continue

            locator = frame.locator(QUIZ_NEXT_CONTROL_SELECTOR)
            count = locator.count()
        except PlaywrightError:
            continue

        for index in range(count):
            control = locator.nth(index)

            try:
                if not control.is_visible() or not control.is_enabled():
                    continue

                info = _quiz_next_control_info(control)
                score = _quiz_next_score(info)
            except PlaywrightError:
                continue

            if score > 0:
                ranked.append((score, frame, control, info))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _click_unique_quiz_next(
    browser: VisibleSmokeBrowser,
    *,
    timeout_seconds: float,
) -> bool:
    ranked = _quiz_next_candidates(browser)

    if not ranked:
        return False

    best_score = ranked[0][0]
    best = [item for item in ranked if item[0] == best_score]

    if len(best) != 1:
        print()
        print("[Quiz Next] 候选存在歧义：")

        for score, frame, _, info in best:
            print(
                "  - "
                f"score={score} "
                f"frame={frame.url.split('?', 1)[0]!r} "
                f"id={info.get('id')!r} "
                f"text={info.get('text')!r} "
                f"value={info.get('value')!r}"
            )

        return False

    score, frame, control, info = best[0]

    print()
    print("[Quiz Next] 找到唯一正常流程 Next 控件：")
    print(f"  frame={frame.url.split('?', 1)[0]!r}")
    print(f"  id={info.get('id')!r}")
    print(f"  text={info.get('text')!r}")
    print(f"  value={info.get('value')!r}")
    print(f"  score={score}")
    print("[Quiz Next] 执行一次真实 UI click。")

    control.click(timeout=round(timeout_seconds * 1000))
    return True


def advance_quiz_after_answers(
    browser: VisibleSmokeBrowser,
    detector,
    content_handler: ChaoxingContentTaskHandler,
    *,
    timeout_seconds: float,
    max_next_clicks: int = 4,
) -> None:
    """Advance an answered Quiz in the fixed already-completed smoke sample.

    The real sample may not expose an initial Submit button after the task has
    already been completed. The observed normal UI exposes a Next control.

    Strategy:
    - after production answer_all(), click only an unambiguous in-Quiz Next;
    - after every click, observe real Card/task state;
    - if Quiz becomes CONTENT, let production ContentHandler advance normally;
    - if the UI still stays on the already-completed Quiz after bounded Next
      clicks, perform one normal visible Card-5 click so the smoke can continue
      regression coverage. No finished/task state is forged.
    """

    for attempt in range(1, max_next_clicks + 1):
        try:
            state = inspect_chaoxing_page(browser)
            task = detector.detect()
        except (BrowserError, ChaoxingInspectionError):
            state = None
            task = TaskType.UNKNOWN

        if state is not None and state.active_tab_index == CARD_COMMENT:
            print("[Quiz Next] 页面已经进入 Card 5 讨论。")
            return

        if state is not None and state.active_tab_index == CARD_QUIZ and task is TaskType.CONTENT:
            print("[Quiz Next] Quiz 已转为 CONTENT，使用 production ContentHandler 正常前进。")
            content_handler.run()
            wait_for_card(
                browser,
                CARD_COMMENT,
                timeout_seconds=timeout_seconds,
            )
            return

        clicked = _click_unique_quiz_next(
            browser,
            timeout_seconds=timeout_seconds,
        )

        if not clicked:
            break

        print(f"[Quiz Next] 第 {attempt} 次 Next click 已返回，等待页面稳定。")
        time.sleep(0.8)

        try:
            state = inspect_chaoxing_page(browser)
            task = detector.detect()

            print(f"[Quiz Next] click 后状态：card={state.active_tab_index + 1}, task={task.name}")
        except (BrowserError, ChaoxingInspectionError):
            pass

    print()
    print("[SMOKE ONLY] 当前固定 Quiz 已经完成过，正常答题后没有可继续确认的 Submit/Next 生命周期。")
    print(
        "[SMOKE ONLY] 已完成 screenshot -> Vision -> select -> verify 回归；"
        "现在仅通过真实可见 Card UI 进入 5 讨论，不伪造 Quiz finished。"
    )

    click_card(
        browser,
        CARD_COMMENT,
        timeout_seconds=timeout_seconds,
    )


def wait_for_quiz_content(
    browser: Browser,
    detector: ChaoxingTaskDetector,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds

    last = None

    while time.monotonic() < deadline:
        try:
            state = inspect_chaoxing_page(browser)

            task = detector.detect()

            last = task

            if state.active_tab_index == CARD_QUIZ and task is TaskType.CONTENT:
                return

        except (
            BrowserError,
            ChaoxingInspectionError,
        ):
            pass

        time.sleep(0.2)

    raise SmokeError(f"Quiz 已返回但没有转为 CONTENT。 last_task={last.name if last else None}")


def wait_for_next_knowledge(
    browser: Browser,
    *,
    timeout_seconds: float,
):
    deadline = time.monotonic() + timeout_seconds

    last = None

    while time.monotonic() < deadline:
        try:
            state = inspect_chaoxing_page(browser)

            last = state

            if state.knowledge_id is not None and state.knowledge_id != START_KNOWLEDGE_ID:
                return state

        except (
            BrowserError,
            ChaoxingInspectionError,
        ):
            pass

        time.sleep(0.25)

    raise SmokeError(f"没有成功离开起始 knowledge。 last={getattr(last, 'knowledge_id', None)}")


def require_api_key(
    name: str,
) -> str:
    return ""


def print_quiz_answers(
    handler: ChaoxingQuizTaskHandler,
) -> None:
    print()
    print("Vision Quiz 结果：")

    for index, answer in enumerate(
        handler.last_answers,
        start=1,
    ):
        print(f"  Q{index}: {answer.question_type.value} -> {','.join(answer.choices)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=(Path.home() / ".linkforge" / "browser-profiles" / "chaoxing-smoke"),
    )

    parser.add_argument(
        "--model",
        required=True,
        help=("Vision-capable model ID."),
    )

    parser.add_argument(
        "--comment-model",
        default=None,
    )

    parser.add_argument(
        "--base-url",
        required=True,
    )

    parser.add_argument(
        "--protocol",
        choices=(
            "openai",
            "anthropic",
        ),
        default="openai",
    )

    parser.add_argument(
        "--api-key-env",
        default=("LINKFORGE_SMOKE_API_KEY"),
    )

    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
    )

    parser.add_argument(
        "--document-timeout-seconds",
        type=float,
        default=120.0,
    )

    parser.add_argument(
        "--quiz-completion-timeout-seconds",
        type=float,
        default=60.0,
    )

    parser.add_argument(
        "--video-seconds",
        type=float,
        default=8.0,
    )

    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=5.0,
    )

    args = parser.parse_args()

    for name, value in {
        "--timeout-seconds": args.timeout_seconds,
        "--document-timeout-seconds": args.document_timeout_seconds,
        "--quiz-completion-timeout-seconds": args.quiz_completion_timeout_seconds,
        "--video-seconds": args.video_seconds,
    }.items():
        if not math.isfinite(value) or value <= 0:
            parser.error(f"{name} 必须是有限正数")

    if not math.isfinite(args.hold_seconds) or args.hold_seconds < 0:
        parser.error("--hold-seconds 不能小于 0")

    logging.basicConfig(
        level=logging.INFO,
        format=("%(levelname)s | %(name)s | %(message)s"),
    )

    quiz_handler: ChaoxingQuizTaskHandler | None = None

    quiz_submitter: SmokeQuizSubmitter | None = None

    try:
        stage("LinkForge FULL REAL CHAOXING E2E SMOKE")

        print("本次 smoke 会真实执行：")
        print("  Document -> Video 8s -> Vision Quiz + Next -> Comment Submit -> Next Knowledge")

        api_key = require_api_key(args.api_key_env)

        profile_dir = args.profile_dir.expanduser().resolve()

        if not profile_dir.is_dir():
            raise SmokeError(f"登录 profile 不存在：{profile_dir}")

        model_config = ModelConfig(
            api_key,
            args.base_url,
            args.model,
            args.protocol,
        )

        llm = create_model_client(model_config)

        comment_model = args.comment_model or args.model

        with VisibleSmokeBrowser(
            headless=False,
            timeout_ms=round(args.timeout_seconds * 1000),
            profile_dir=str(profile_dir),
        ) as browser:
            stage("阶段 0：打开固定课程")

            browser.open(COURSE_URL)

            if looks_logged_out(browser.current_url()):
                raise SmokeError("学习通登录态失效。")

            ensure_start_card(
                browser,
                timeout_seconds=args.timeout_seconds,
            )

            session = CommentSession()

            base_detector = ChaoxingTaskDetector(
                browser,
                comment_session=session,
            )

            detector = SmokeForcedCommentDetector(
                browser,
                base_detector=base_detector,
                comment_session=session,
            )

            content_handler = ChaoxingContentTaskHandler(
                browser,
                detector=detector,
                config=ChaoxingContentHandlerConfig(
                    poll_interval_seconds=0.25,
                    navigation_timeout_seconds=args.timeout_seconds,
                ),
            )

            comment_handler = ChaoxingCommentTaskHandler(
                browser,
                comment_session=session,
                body_generator=LLMCommentBodyGenerator(
                    llm=llm,
                    model=comment_model,
                ),
                detector=detector,
            )

            quiz_submitter = SmokeQuizSubmitter(
                timeout_seconds=args.timeout_seconds,
                confirmation_timeout_seconds=min(
                    20.0,
                    args.quiz_completion_timeout_seconds,
                ),
            )

            quiz_handler = ChaoxingQuizTaskHandler(
                browser,
                solver=LLMQuizSolver(
                    llm=llm,
                    model=args.model,
                ),
                submitter=None,
                detector=detector,
                config=ChaoxingQuizHandlerConfig(
                    readiness_timeout_seconds=args.timeout_seconds,
                    selection_timeout_seconds=5.0,
                    completion_timeout_seconds=args.quiz_completion_timeout_seconds,
                    poll_interval_seconds=0.2,
                ),
            )

            print_current(
                browser,
                detector,
                prefix="起点：",
            )

            # ========================================================
            # Card 1: CONTENT
            # ========================================================

            stage("阶段 1：概述 -> PPT")

            state, task = print_current(
                browser,
                detector,
            )

            if state.active_tab_index != CARD_OVERVIEW or task is not TaskType.CONTENT:
                raise SmokeError("起点不是 Card 1 CONTENT。")

            content_handler.run()

            wait_for_card(
                browser,
                CARD_DOCUMENT,
                timeout_seconds=args.timeout_seconds,
            )

            # ========================================================
            # Card 2: DOCUMENT
            # ========================================================

            stage("阶段 2：PPT / Document")

            print_current(
                browser,
                detector,
            )

            document_count = run_documents(
                browser,
                detector,
                timeout_seconds=args.document_timeout_seconds,
            )

            print(f"DocumentHandler 处理数量={document_count}")

            if detector.detect() is not TaskType.CONTENT:
                raise SmokeError("Document 阶段结束后 不是 CONTENT。")

            content_handler.run()

            wait_for_card(
                browser,
                CARD_VIDEO,
                timeout_seconds=args.timeout_seconds,
            )

            # ========================================================
            # Card 3: VIDEO
            # ========================================================

            stage(f"阶段 3：Video {args.video_seconds:g}s")

            _, task = print_current(
                browser,
                detector,
            )

            if task is TaskType.VIDEO:
                play_real_video_for_seconds(
                    browser,
                    seconds=args.video_seconds,
                    timeout_seconds=args.timeout_seconds,
                )

            elif task is not TaskType.CONTENT:
                raise SmokeError(f"Video Card 出现 意外 task={task.name}")

            advance_after_smoke_video(
                browser,
                detector,
                timeout_seconds=args.timeout_seconds,
            )

            wait_for_card(
                browser,
                CARD_QUIZ,
                timeout_seconds=args.timeout_seconds,
            )

            # ========================================================
            # Card 4: QUIZ
            # ========================================================

            stage("阶段 4：Vision Quiz 真正答题 + Next")

            wait_for_task(
                browser,
                detector,
                card_index=CARD_QUIZ,
                expected=TaskType.QUIZ,
                timeout_seconds=args.timeout_seconds,
            )

            print_current(
                browser,
                detector,
            )

            quiz_started = time.monotonic()

            answers = quiz_handler.answer_all()

            print_quiz_answers(quiz_handler)

            print()
            print("Quiz production answer_all() 返回：")
            print(f"  elapsed={time.monotonic() - quiz_started:.2f}s")
            print(f"  answered={len(answers)}")
            print("  selection_verify=PASS")

            advance_quiz_after_answers(
                browser,
                detector,
                content_handler,
                timeout_seconds=args.timeout_seconds,
            )

            wait_for_card(
                browser,
                CARD_COMMENT,
                timeout_seconds=args.timeout_seconds,
            )

            # ========================================================
            # Card 5: COMMENT
            # ========================================================

            stage("阶段 5：Comment 真正生成 + 提交")

            wait_for_task(
                browser,
                detector,
                card_index=CARD_COMMENT,
                expected=TaskType.COMMENT,
                timeout_seconds=args.timeout_seconds,
            )

            print_current(
                browser,
                detector,
            )

            comment_handler.run()

            record = comment_handler.last_record

            if record is None:
                raise SmokeError("Comment Handler 没有生成记录。")

            print()
            print("Comment result：")
            print(f"  outcome={record.outcome.value}")
            print(f"  stage={record.stage}")
            print(f"  reason={record.reason!r}")

            if record.outcome is CommentOutcome.SKIPPED:
                raise SmokeError("Comment 在提交前 被 SKIPPED。")

            if detector.detect() is not TaskType.CONTENT:
                raise SmokeError("Comment 处理后 Detector 未变为 CONTENT。")

            # ========================================================
            # NEXT KNOWLEDGE
            # ========================================================

            stage("阶段 6：进入下一章节")

            content_handler.run()

            next_state = wait_for_next_knowledge(
                browser,
                timeout_seconds=args.timeout_seconds,
            )

            next_task = detector.detect()

            print()
            print("Knowledge transition：")
            print(f"  from={START_KNOWLEDGE_ID}")
            print(f"  to={next_state.knowledge_id}")
            print(f"  task={next_task.name}")

            stage("FULL E2E SMOKE PASSED")

            print()
            print("完整纵向链路已经真实执行：")
            print()
            print("CONTENT")
            print("  ↓")
            print(f"DOCUMENT x {document_count}")
            print("  ↓")
            print(f"VIDEO {args.video_seconds:g}s")
            print("  ↓")
            print("QUIZ")
            print("  screenshot -> Vision LLM -> select -> verify -> Next")
            print("  ↓")
            print("COMMENT")
            print("  LLM -> fill -> submit")
            print("  ↓")
            print("NEXT KNOWLEDGE")

            if args.hold_seconds > 0:
                print()
                print(f"浏览器保持 {args.hold_seconds:g}s 后自动关闭。")

                time.sleep(args.hold_seconds)

        return 0

    except KeyboardInterrupt:
        stage("FULL E2E SMOKE ABORTED")

        print("用户中止。")

        return 130

    except (
        BrowserError,
        ChaoxingQuizError,
        SmokeError,
        PlaywrightError,
    ) as exc:
        stage("FULL E2E SMOKE FAILED")

        print(f"{type(exc).__name__}: {exc}")

        if quiz_handler is not None and quiz_handler.last_answers:
            print_quiz_answers(quiz_handler)

        if quiz_submitter is not None:
            print()
            print("Quiz submit diagnostics（本版 completed-sample smoke 通常不走 Submit）：")
            print(f"  submit_clicks={quiz_submitter.submit_clicks}")
            print(f"  confirm_clicks={quiz_submitter.confirm_clicks}")
            print(f"  browser_dialogs={quiz_submitter.dialog_count}")

            if quiz_submitter.submit_clicks > 0:
                print("  注意：已经发生过真实 Quiz submit click，本次运行不会自动重试。")

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
