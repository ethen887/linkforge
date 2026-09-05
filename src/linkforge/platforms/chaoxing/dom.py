"""Validated Chaoxing DOM inspection used by detector and task handlers."""

from math import isfinite
from typing import TypeGuard

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.models import (
    ChaoxingModuleState,
    ChaoxingPageState,
    ChaoxingVideoState,
)

CHAOXING_STATE_SCRIPT = """() => {
    const frameUrl = window.location.href;
    const activeTabs = Array.from(document.querySelectorAll("#prev_tab li.active"));
    let activeTabIndex = null;
    let hasNextTab = false;

    if (activeTabs.length === 1) {
        const activeTab = activeTabs[0];
        const siblings = activeTab.parentElement
            ? Array.from(activeTab.parentElement.children)
            : [];
        activeTabIndex = siblings.indexOf(activeTab);
        hasNextTab = activeTab.nextElementSibling?.matches("li") === true;
    }

    const modules = [];
    if (frameUrl.includes("/mooc-ans/knowledge/cards")) {
        const moduleFrames = document.querySelectorAll('iframe[src*="/ananas/modules/"]');
        for (const moduleFrame of moduleFrames) {
            const container = moduleFrame.closest(".ans-attach-ct");
            const hasJobIcon = container
                ? container.querySelector(".ans-job-icon") !== null
                : false;

            modules.push({
                module_url: moduleFrame.src || moduleFrame.getAttribute("src"),
                has_job_icon: hasJobIcon,
                finished: hasJobIcon && container.classList.contains("ans-job-finished"),
            });
        }
    }

    let video = null;
    let videoCount = 0;
    if (frameUrl.includes("/ananas/modules/video/")) {
        const videoElements = document.querySelectorAll("video");
        videoCount = videoElements.length;
        if (videoCount === 1) {
            const element = videoElements[0];
            video = {
                paused: element.paused,
                ended: element.ended,
                current_time: Number.isFinite(element.currentTime) ? element.currentTime : null,
                duration: Number.isFinite(element.duration) ? element.duration : null,
                ready_state: element.readyState,
            };
        }
    }

    return {
        frame_url: frameUrl,
        active_tab_count: activeTabs.length,
        active_tab_index: activeTabIndex,
        has_next_tab: hasNextTab,
        modules,
        video_count: videoCount,
        video,
    };
}"""


def inspect_chaoxing_page(browser: Browser) -> ChaoxingPageState:
    """Read and validate one dynamic Chaoxing page snapshot."""
    try:
        frame_results = browser.evaluate_in_frames(CHAOXING_STATE_SCRIPT)
    except BrowserError as exc:
        raise ChaoxingInspectionError("Failed to inspect Chaoxing page frames.") from exc

    active_frames: list[tuple[int, bool]] = []
    content_frames: list[tuple[str, tuple[ChaoxingModuleState, ...]]] = []
    videos: list[ChaoxingVideoState] = []

    for result in frame_results:
        if not isinstance(result, dict):
            raise ChaoxingInspectionError("Chaoxing frame inspection returned a non-object result.")

        frame_url = result.get("frame_url")
        active_tab_count = result.get("active_tab_count")
        if not isinstance(frame_url, str) or not _is_non_negative_int(active_tab_count):
            raise ChaoxingInspectionError("Chaoxing frame identity or active-tab state is malformed.")

        if active_tab_count == 1:
            active_tab_index = result.get("active_tab_index")
            has_next_tab = result.get("has_next_tab")
            if not _is_non_negative_int(active_tab_index) or not isinstance(has_next_tab, bool):
                raise ChaoxingInspectionError("Chaoxing active-tab details are malformed.")
            active_frames.append((active_tab_index, has_next_tab))
        elif active_tab_count != 0:
            raise ChaoxingInspectionError("Multiple active Chaoxing tabs were found in one frame.")

        modules = _parse_modules(result.get("modules"))
        if "/mooc-ans/knowledge/cards" in frame_url:
            content_frames.append((frame_url, modules))
        elif modules:
            raise ChaoxingInspectionError("Chaoxing modules were reported outside a content frame.")

        video = _parse_video(frame_url, result)
        if video is not None:
            videos.append(video)

    if len(active_frames) != 1 or len(content_frames) != 1:
        raise ChaoxingInspectionError("Current Chaoxing card is missing or ambiguous.")

    active_tab_index, has_next_tab = active_frames[0]
    content_frame_url, modules = content_frames[0]
    return ChaoxingPageState(
        content_frame_url=content_frame_url,
        active_tab_index=active_tab_index,
        has_next_tab=has_next_tab,
        modules=modules,
        videos=tuple(videos),
    )


def first_pending_module(state: ChaoxingPageState) -> ChaoxingModuleState | None:
    """Return the first module not proven complete by its task-point marker."""
    for module in state.modules:
        if module.has_job_icon and module.finished:
            continue
        return module
    return None


def _parse_modules(value: object) -> tuple[ChaoxingModuleState, ...]:
    if not isinstance(value, list):
        raise ChaoxingInspectionError("Chaoxing module state is malformed.")

    modules: list[ChaoxingModuleState] = []
    for item in value:
        if not isinstance(item, dict):
            raise ChaoxingInspectionError("Chaoxing module state contains a non-object item.")
        module_url = item.get("module_url")
        has_job_icon = item.get("has_job_icon")
        finished = item.get("finished")
        if (
            not isinstance(module_url, str)
            or not isinstance(has_job_icon, bool)
            or not isinstance(finished, bool)
        ):
            raise ChaoxingInspectionError("Chaoxing module fields are malformed.")
        modules.append(
            ChaoxingModuleState(
                url=module_url,
                has_job_icon=has_job_icon,
                finished=finished,
            )
        )
    return tuple(modules)


def _parse_video(frame_url: str, result: dict[object, object]) -> ChaoxingVideoState | None:
    video_count = result.get("video_count")
    video_value = result.get("video")
    if not _is_non_negative_int(video_count):
        raise ChaoxingInspectionError("Chaoxing video count is malformed.")
    if video_count == 0:
        if video_value is not None:
            raise ChaoxingInspectionError("Chaoxing video state is inconsistent.")
        return None
    if video_count != 1 or not isinstance(video_value, dict):
        raise ChaoxingInspectionError(
            f"Expected exactly one HTML video element in module frame: {frame_url}"
        )

    paused = video_value.get("paused")
    ended = video_value.get("ended")
    current_time = video_value.get("current_time")
    duration = video_value.get("duration")
    ready_state = video_value.get("ready_state")
    if (
        not isinstance(paused, bool)
        or not isinstance(ended, bool)
        or not _is_finite_number(current_time)
        or (duration is not None and not _is_finite_number(duration))
        or not _is_non_negative_int(ready_state)
    ):
        raise ChaoxingInspectionError("Chaoxing HTML video state is malformed.")

    return ChaoxingVideoState(
        frame_url=frame_url,
        paused=paused,
        ended=ended,
        current_time=float(current_time),
        duration=float(duration) if duration is not None else None,
        ready_state=ready_state,
    )


def _is_non_negative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(value: object) -> TypeGuard[int | float]:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(float(value))
        and value >= 0
    )
