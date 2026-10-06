"""Validated Chaoxing DOM inspection used by detector and task handlers."""

from __future__ import annotations

import json
from math import isfinite
from typing import TypeGuard
from urllib.parse import parse_qs, urlparse

from linkforge.browser.base import Browser
from linkforge.browser.exceptions import BrowserError
from linkforge.platforms.chaoxing.exceptions import ChaoxingInspectionError
from linkforge.platforms.chaoxing.models import (
    ChaoxingModuleState,
    ChaoxingPageState,
    ChaoxingVideoState,
)

FRAME_PATH_SCRIPT = """
    const framePath = [];
    let currentWindow = window;
    while (currentWindow !== currentWindow.top) {
        const parentWindow = currentWindow.parent;
        let childIndex = -1;
        for (let index = 0; index < parentWindow.length; index++) {
            if (parentWindow[index] === currentWindow) {
                childIndex = index;
                break;
            }
        }
        if (childIndex < 0) {
            throw new Error("Frame detached while computing its path");
        }
        framePath.unshift(childIndex);
        currentWindow = parentWindow;
    }
"""

CHAOXING_STATE_SCRIPT = (
    """() => {"""
    + FRAME_PATH_SCRIPT
    + """
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
        const moduleFrames = document.querySelectorAll(
            'iframe[src*="/ananas/modules/"]'
        );

        for (const moduleFrame of moduleFrames) {
            let childIndex = -1;
            for (let index = 0; index < window.length; index++) {
                if (window[index] === moduleFrame.contentWindow) {
                    childIndex = index;
                    break;
                }
            }
            const container = moduleFrame.closest(".ans-attach-ct");
            const hasJobIcon = container
                ? container.querySelector(".ans-job-icon") !== null
                : false;

            modules.push({
                module_url:
                    moduleFrame.src || moduleFrame.getAttribute("src"),
                has_job_icon: hasJobIcon,
                frame_path: childIndex < 0 ? null : [...framePath, childIndex],
                finished:
                    hasJobIcon
                    && container.classList.contains("ans-job-finished"),
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
                current_time: Number.isFinite(element.currentTime)
                    ? element.currentTime
                    : null,
                duration: Number.isFinite(element.duration)
                    ? element.duration
                    : null,
                ready_state: element.readyState,
            };
        }
    }

    return {
        frame_url: frameUrl,
        frame_path: framePath,
        active_tab_count: activeTabs.length,
        active_tab_index: activeTabIndex,
        has_next_tab: hasNextTab,
        modules,
        video_count: videoCount,
        video,
    };
}"""
)


CHAOXING_CARD_STATE_SCRIPT = (
    "() => {"
    + FRAME_PATH_SCRIPT
    + r"""
    const findValue = (value, keys) => {
        if (!value || typeof value !== "object") {
            return null;
        }

        for (const [key, child] of Object.entries(value)) {
            if (
                keys.includes(key.toLowerCase())
                && child !== null
                && child !== ""
            ) {
                return child;
            }
        }

        for (const child of Object.values(value)) {
            const found = findValue(child, keys);
            if (found !== null) {
                return found;
            }
        }

        return null;
    };

    const parseModuleData = (moduleFrame) => {
        const rawData = moduleFrame.getAttribute("data");

        if (!rawData) {
            return {};
        }

        try {
            const data = JSON.parse(rawData);

            const rawObjectId = findValue(
                data,
                ["objectid", "object_id"]
            );

            const rawPageCount = findValue(
                data,
                ["pagenum", "pagecount", "page_count", "pages"]
            );

            const numericPageCount = Number(rawPageCount);

            return {
                object_id:
                    typeof rawObjectId === "string"
                        ? rawObjectId
                        : null,

                declared_page_count:
                    Number.isInteger(numericPageCount)
                    && numericPageCount > 0
                        ? numericPageCount
                        : null,
            };
        } catch (error) {
            return {
                object_id: null,
                declared_page_count: null,
            };
        }
    };

    const objectIdFromUrl = (url) => {
        const fileMatch = url.match(
            /\/screen\/v2\/file_([a-zA-Z0-9]+)/
        );

        if (fileMatch) {
            return fileMatch[1];
        }

        try {
            return new URL(url).searchParams.get("objectid");
        } catch (error) {
            return null;
        }
    };

    const frameUrl = window.location.href;

    const activeTabCount = document.querySelectorAll(
        "#prev_tab li.active"
    ).length;

    const modules = [];

    if (frameUrl.includes("/mooc-ans/knowledge/cards")) {
        const moduleFrames = document.querySelectorAll(
            'iframe[src*="/ananas/modules/"]'
        );

        for (const moduleFrame of moduleFrames) {
            const container = moduleFrame.closest(".ans-attach-ct");
            const moduleData = parseModuleData(moduleFrame);
            let childIndex = -1;
            for (let index = 0; index < window.length; index++) {
                if (window[index] === moduleFrame.contentWindow) {
                    childIndex = index;
                    break;
                }
            }

            const hasJobIcon = container
                ? container.querySelector(".ans-job-icon") !== null
                : false;

            modules.push({
                module_url: moduleFrame.getAttribute("src"),
                frame_path: childIndex < 0 ? null : [...framePath, childIndex],
                object_id: moduleData.object_id || null,
                declared_page_count:
                    moduleData.declared_page_count || null,
                has_job_icon: hasJobIcon,
                finished:
                    hasJobIcon
                    && container.classList.contains("ans-job-finished"),
            });
        }
    }

    let viewer = null;

    const viewerObjectId = objectIdFromUrl(frameUrl);

    if (
        viewerObjectId
        && frameUrl.includes("/screen/v2/file_")
    ) {
        const scrollY = Math.max(
            window.scrollY,
            document.documentElement
                ? document.documentElement.scrollTop
                : 0,
            document.body
                ? document.body.scrollTop
                : 0
        );

        const innerHeight = window.innerHeight;

        const scrollHeight = Math.max(
            document.documentElement
                ? document.documentElement.scrollHeight
                : 0,
            document.body
                ? document.body.scrollHeight
                : 0
        );

        const bottomDistance =
            scrollHeight - (scrollY + innerHeight);

        const pageImages = Array.from(
            document.querySelectorAll(
                'img[src*="/thumb/"]'
            )
        );

        const pageNumbers = pageImages
            .map((image) => {
                const match = (
                    image.getAttribute("src") || ""
                ).match(/\/thumb\/(\d+)\.png/);

                return match
                    ? Number(match[1])
                    : null;
            })
            .filter((pageNumber) =>
                Number.isInteger(pageNumber)
            );

        const visiblePages = pageImages
            .filter((image) => {
                const rect = image.getBoundingClientRect();

                return (
                    rect.bottom > 0
                    && rect.top < innerHeight
                );
            })
            .map((image) => {
                const match = (
                    image.getAttribute("src") || ""
                ).match(/\/thumb\/(\d+)\.png/);

                return match
                    ? Number(match[1])
                    : null;
            })
            .filter((pageNumber) =>
                Number.isInteger(pageNumber)
            );

        viewer = {
            object_id: viewerObjectId,
            page_count:
                pageNumbers.length
                    ? Math.max(...pageNumbers)
                    : 0,
            visible_pages: Array.from(
                new Set(visiblePages)
            ),
            scroll_y: scrollY,
            inner_height: innerHeight,
            scroll_height: scrollHeight,
            bottom_distance: bottomDistance,
            at_bottom: bottomDistance <= 8,
        };
    }

    return {
        frame_url: frameUrl,
        active_tab_count: activeTabCount,
        modules,
        viewer,
    };
}"""
)


def inspect_chaoxing_page(
    browser: Browser,
) -> ChaoxingPageState:
    """Read and validate one dynamic Chaoxing page snapshot."""
    try:
        frame_results = browser.evaluate_in_frames(CHAOXING_STATE_SCRIPT)
    except BrowserError as exc:
        raise ChaoxingInspectionError("Failed to inspect Chaoxing page frames.") from exc

    active_frames: list[tuple[int, bool]] = []

    content_frames: list[
        tuple[
            str,
            tuple[ChaoxingModuleState, ...],
        ]
    ] = []

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

            if not _is_non_negative_int(active_tab_index) or not isinstance(
                has_next_tab,
                bool,
            ):
                raise ChaoxingInspectionError("Chaoxing active-tab details are malformed.")

            active_frames.append(
                (
                    active_tab_index,
                    has_next_tab,
                )
            )

        elif active_tab_count != 0:
            raise ChaoxingInspectionError("Multiple active Chaoxing tabs were found in one frame.")

        modules = _parse_modules(result.get("modules"))

        if "/mooc-ans/knowledge/cards" in frame_url:
            content_frames.append(
                (
                    frame_url,
                    modules,
                )
            )

        elif modules:
            raise ChaoxingInspectionError("Chaoxing modules were reported outside a content frame.")

        video = _parse_video(
            frame_url,
            result,
        )

        if video is not None:
            videos.append(video)

    if len(active_frames) != 1 or len(content_frames) != 1:
        raise ChaoxingInspectionError("Current Chaoxing card is missing or ambiguous.")

    active_tab_index, has_next_tab = active_frames[0]

    content_frame_url, modules = content_frames[0]

    return ChaoxingPageState(
        content_frame_url=content_frame_url,
        knowledge_id=_parse_knowledge_id(content_frame_url),
        active_tab_index=active_tab_index,
        has_next_tab=has_next_tab,
        modules=modules,
        videos=tuple(videos),
    )


def first_pending_module(
    state: ChaoxingPageState,
) -> ChaoxingModuleState | None:
    """Return the first module not proven complete by its task marker."""
    for module in state.modules:
        if module.has_job_icon and module.finished:
            continue

        return module

    return None


def build_document_scroll_script(
    object_id: str,
    delta_y: int,
) -> str:
    """Build a scroll action restricted to one real PDF viewer frame."""
    encoded_object_id = json.dumps(object_id)
    encoded_delta_y = json.dumps(delta_y)

    return f"""() => {{
        const targetObjectId = {encoded_object_id};

        const match = window.location.href.match(
            /\\/screen\\/v2\\/file_([a-zA-Z0-9]+)/
        );

        if (
            !match
            || match[1] !== targetObjectId
        ) {{
            return {{
                matched: false
            }};
        }}

        const before = window.scrollY;

        window.scrollBy({{
            top: {encoded_delta_y},
            left: 0,
            behavior: "auto"
        }});

        return {{
            matched: true,
            before_scroll_y: before,
            after_scroll_y: window.scrollY
        }};
    }}"""


def _parse_knowledge_id(
    content_frame_url: str,
) -> str | None:
    parsed_url = urlparse(content_frame_url)

    values = parse_qs(parsed_url.query).get("knowledgeid")

    # Local data-URL fixtures encode the Chaoxing
    # route in the fragment.
    if values is None and "?" in parsed_url.fragment:
        values = parse_qs(parsed_url.fragment.partition("?")[2]).get("knowledgeid")

    if values is None:
        return None

    if len(values) != 1 or not values[0].strip():
        raise ChaoxingInspectionError("Chaoxing content frame knowledgeId is malformed.")

    return values[0]


def _parse_modules(
    value: object,
) -> tuple[ChaoxingModuleState, ...]:
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
            not isinstance(
                module_url,
                str,
            )
            or not isinstance(
                has_job_icon,
                bool,
            )
            or not isinstance(
                finished,
                bool,
            )
        ):
            raise ChaoxingInspectionError("Chaoxing module fields are malformed.")

        modules.append(
            ChaoxingModuleState(
                url=module_url,
                has_job_icon=has_job_icon,
                finished=finished,
                frame_path=_parse_frame_path(item.get("frame_path")),
            )
        )

    return tuple(modules)


def _parse_video(
    frame_url: str,
    result: dict[object, object],
) -> ChaoxingVideoState | None:
    video_count = result.get("video_count")

    video_value = result.get("video")

    if not _is_non_negative_int(video_count):
        raise ChaoxingInspectionError("Chaoxing video count is malformed.")

    if video_count == 0:
        if video_value is not None:
            raise ChaoxingInspectionError("Chaoxing video state is inconsistent.")

        return None

    if video_count != 1 or not isinstance(
        video_value,
        dict,
    ):
        raise ChaoxingInspectionError(
            f"Expected exactly one HTML video element in module frame: {frame_url}"
        )

    paused = video_value.get("paused")

    ended = video_value.get("ended")

    current_time = video_value.get("current_time")

    duration = video_value.get("duration")

    ready_state = video_value.get("ready_state")

    if (
        not isinstance(
            paused,
            bool,
        )
        or not isinstance(
            ended,
            bool,
        )
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
        duration=(float(duration) if duration is not None else None),
        ready_state=ready_state,
        frame_path=_parse_frame_path(result.get("frame_path")),
    )


def _parse_frame_path(value: object) -> tuple[int, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(_is_non_negative_int(index) for index in value):
        raise ChaoxingInspectionError("Chaoxing frame path is malformed.")
    return tuple(value)


def _is_non_negative_int(
    value: object,
) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_number(
    value: object,
) -> TypeGuard[int | float]:
    return (
        isinstance(
            value,
            (int, float),
        )
        and not isinstance(
            value,
            bool,
        )
        and isfinite(float(value))
        and value >= 0
    )


DOCUMENT_RECON_SCRIPT = r"""() => {
    const describe = (element) => ({
        tag: element.tagName.toLowerCase(),
        id: element.id || null,
        classes: Array.from(
            element.classList || []
        ).slice(0, 8),
        role: element.getAttribute("role"),
        title: element.getAttribute("title"),
        aria_label: element.getAttribute("aria-label"),
    });

    const describeResource = (element) => ({
        ...describe(element),
        src: element.getAttribute("src"),
        data: element.getAttribute("data"),
        type: element.getAttribute("type"),
    });

    const limited = (
        items,
        limit = 40
    ) => Array.from(items).slice(
        0,
        limit
    );

    const moduleStates = [];

    for (
        const moduleFrame of document.querySelectorAll(
            'iframe[src*="/ananas/modules/"]'
        )
    ) {
        const container = moduleFrame.closest(
            ".ans-attach-ct"
        );

        moduleStates.push({
            module_url:
                moduleFrame.getAttribute("src"),

            container:
                container
                    ? describe(container)
                    : null,

            has_job_icon:
                container
                    ? container.querySelector(
                        ".ans-job-icon"
                    ) !== null
                    : false,

            finished:
                container
                    ? container.classList.contains(
                        "ans-job-finished"
                    )
                    : false,
        });
    }

    const scrollContainers = limited(
        document.querySelectorAll(
            "body, body *"
        ),
        2000
    )
        .filter((element) => {
            const style =
                window.getComputedStyle(
                    element
                );

            return (
                element.scrollHeight
                    > element.clientHeight + 1
                && ["auto", "scroll"].includes(
                    style.overflowY
                )
            );
        })
        .slice(0, 40)
        .map((element) => ({
            ...describe(element),
            scroll_top: element.scrollTop,
            scroll_height:
                element.scrollHeight,
            client_height:
                element.clientHeight,
        }));

    const pageSignals = limited(
        document.querySelectorAll(
            '[data-page-number], '
            + '[aria-label*="page" i], '
            + '[aria-label*="页"], '
            + '[class*="page" i], '
            + '[id*="page" i]'
        )
    ).map((element) => ({
        ...describe(element),

        data_page_number:
            element.getAttribute(
                "data-page-number"
            ),

        text:
            (
                element.innerText
                || element.textContent
                || ""
            )
                .trim()
                .slice(0, 120),
    }));

    const controls = limited(
        document.querySelectorAll(
            'button, a, input, [role="button"]'
        ),
        300
    )
        .map((element) => ({
            ...describe(element),

            text:
                (
                    element.innerText
                    || element.textContent
                    || element.value
                    || ""
                )
                    .trim()
                    .slice(0, 120),

            disabled:
                Boolean(element.disabled)
                || element.getAttribute(
                    "aria-disabled"
                ) === "true",
        }))
        .filter((item) => {
            const label =
                `${item.text} `
                + `${item.title || ""} `
                + `${item.aria_label || ""}`;

            return (
                /(next|prev|previous|page|下一|上一|翻页|页码)/i
                    .test(label)
            );
        })
        .slice(0, 40);

    const toolbarCandidates = limited(
        document.querySelectorAll(
            '[class*="toolbar" i], '
            + '[id*="toolbar" i], '
            + '[class*="pager" i], '
            + '[id*="pager" i], '
            + '[class*="navigation" i], '
            + '[id*="navigation" i]'
        )
    ).map(describe);

    return {
        frame_url:
            window.location.href,

        title:
            document.title,

        ready_state:
            document.readyState,

        active_tab_count:
            document.querySelectorAll(
                "#prev_tab li.active"
            ).length,

        document_module_states:
            moduleStates,

        resources: {
            iframes:
                limited(
                    document.querySelectorAll(
                        "iframe"
                    )
                ).map(
                    describeResource
                ),

            embeds:
                limited(
                    document.querySelectorAll(
                        "embed"
                    )
                ).map(
                    describeResource
                ),

            objects:
                limited(
                    document.querySelectorAll(
                        "object"
                    )
                ).map(
                    describeResource
                ),

            canvases:
                limited(
                    document.querySelectorAll(
                        "canvas"
                    )
                ).map((element) => ({
                    ...describe(element),
                    width: element.width,
                    height: element.height,
                })),

            images:
                limited(
                    document.querySelectorAll(
                        "img"
                    )
                ).map(
                    describeResource
                ),
        },

        viewport: {
            scroll_x:
                window.scrollX,

            scroll_y:
                window.scrollY,

            inner_width:
                window.innerWidth,

            inner_height:
                window.innerHeight,

            document_scroll_height:
                document.documentElement
                    .scrollHeight,

            body_scroll_height:
                document.body
                    ? document.body.scrollHeight
                    : null,
        },

        scroll_containers:
            scrollContainers,

        page_signals:
            pageSignals,

        controls,

        toolbar_candidates:
            toolbarCandidates,
    };
}"""
