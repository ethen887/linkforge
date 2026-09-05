"""Chaoxing-specific DOM inspection scripts."""

CHAOXING_CARD_STATE_SCRIPT = r"""() => {
    const findValue = (value, keys) => {
        if (!value || typeof value !== "object") {
            return null;
        }
        for (const [key, child] of Object.entries(value)) {
            if (keys.includes(key.toLowerCase()) && child !== null && child !== "") {
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
            const rawObjectId = findValue(data, ["objectid", "object_id"]);
            const rawPageCount = findValue(
                data,
                ["pagenum", "pagecount", "page_count", "pages"]
            );
            const numericPageCount = Number(rawPageCount);
            return {
                object_id: typeof rawObjectId === "string" ? rawObjectId : null,
                declared_page_count: Number.isInteger(numericPageCount) && numericPageCount > 0
                    ? numericPageCount
                    : null,
            };
        } catch (error) {
            return {object_id: null, declared_page_count: null};
        }
    };
    const objectIdFromUrl = (url) => {
        const fileMatch = url.match(/\/screen\/v2\/file_([a-zA-Z0-9]+)/);
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
    const activeTabCount = document.querySelectorAll("#prev_tab li.active").length;
    const modules = [];

    if (frameUrl.includes("/mooc-ans/knowledge/cards")) {
        const moduleFrames = document.querySelectorAll('iframe[src*="/ananas/modules/"]');
        for (const moduleFrame of moduleFrames) {
            const container = moduleFrame.closest(".ans-attach-ct");
            const moduleData = parseModuleData(moduleFrame);
            const hasJobIcon = container
                ? container.querySelector(".ans-job-icon") !== null
                : false;

            modules.push({
                module_url: moduleFrame.getAttribute("src"),
                object_id: moduleData.object_id || null,
                declared_page_count: moduleData.declared_page_count || null,
                has_job_icon: hasJobIcon,
                finished: hasJobIcon && container.classList.contains("ans-job-finished"),
            });
        }
    }

    let viewer = null;
    const viewerObjectId = objectIdFromUrl(frameUrl);
    if (viewerObjectId && frameUrl.includes("/screen/v2/file_")) {
        const scrollY = Math.max(
            window.scrollY,
            document.documentElement ? document.documentElement.scrollTop : 0,
            document.body ? document.body.scrollTop : 0
        );
        const innerHeight = window.innerHeight;
        const scrollHeight = Math.max(
            document.documentElement ? document.documentElement.scrollHeight : 0,
            document.body ? document.body.scrollHeight : 0
        );
        const bottomDistance = scrollHeight - (scrollY + innerHeight);
        const pageImages = Array.from(document.querySelectorAll('img[src*="/thumb/"]'));
        const pageNumbers = pageImages.map((image) => {
            const match = (image.getAttribute("src") || "").match(/\/thumb\/(\d+)\.png/);
            return match ? Number(match[1]) : null;
        }).filter((pageNumber) => Number.isInteger(pageNumber));
        const visiblePages = pageImages.filter((image) => {
            const rect = image.getBoundingClientRect();
            return rect.bottom > 0 && rect.top < innerHeight;
        }).map((image) => {
            const match = (image.getAttribute("src") || "").match(/\/thumb\/(\d+)\.png/);
            return match ? Number(match[1]) : null;
        }).filter((pageNumber) => Number.isInteger(pageNumber));

        viewer = {
            object_id: viewerObjectId,
            page_count: pageNumbers.length ? Math.max(...pageNumbers) : 0,
            visible_pages: Array.from(new Set(visiblePages)),
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


def build_document_scroll_script(object_id: str, delta_y: int) -> str:
    """Build a trusted scroll action restricted to one real PDF viewer frame."""
    import json

    encoded_object_id = json.dumps(object_id)
    encoded_delta_y = json.dumps(delta_y)
    return f"""() => {{
        const targetObjectId = {encoded_object_id};
        const match = window.location.href.match(/\\/screen\\/v2\\/file_([a-zA-Z0-9]+)/);
        if (!match || match[1] !== targetObjectId) {{
            return {{matched: false}};
        }}
        const before = window.scrollY;
        window.scrollBy({{top: {encoded_delta_y}, left: 0, behavior: "auto"}});
        return {{matched: true, before_scroll_y: before, after_scroll_y: window.scrollY}};
    }}"""


DOCUMENT_RECON_SCRIPT = r"""() => {
    const describe = (element) => ({
        tag: element.tagName.toLowerCase(),
        id: element.id || null,
        classes: Array.from(element.classList || []).slice(0, 8),
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
    const limited = (items, limit = 40) => Array.from(items).slice(0, limit);
    const moduleStates = [];

    for (const moduleFrame of document.querySelectorAll('iframe[src*="/ananas/modules/"]')) {
        const container = moduleFrame.closest(".ans-attach-ct");
        moduleStates.push({
            module_url: moduleFrame.getAttribute("src"),
            container: container ? describe(container) : null,
            has_job_icon: container
                ? container.querySelector(".ans-job-icon") !== null
                : false,
            finished: container
                ? container.classList.contains("ans-job-finished")
                : false,
        });
    }

    const scrollContainers = limited(document.querySelectorAll("body, body *"), 2000)
        .filter((element) => {
            const style = window.getComputedStyle(element);
            return element.scrollHeight > element.clientHeight + 1
                && ["auto", "scroll"].includes(style.overflowY);
        })
        .slice(0, 40)
        .map((element) => ({
            ...describe(element),
            scroll_top: element.scrollTop,
            scroll_height: element.scrollHeight,
            client_height: element.clientHeight,
        }));

    const pageSignals = limited(document.querySelectorAll(
        '[data-page-number], [aria-label*="page" i], [aria-label*="页"], '
        + '[class*="page" i], [id*="page" i]'
    )).map((element) => ({
        ...describe(element),
        data_page_number: element.getAttribute("data-page-number"),
        text: (element.innerText || element.textContent || "").trim().slice(0, 120),
    }));

    const controls = limited(document.querySelectorAll(
        'button, a, input, [role="button"]'
    ), 300).map((element) => ({
        ...describe(element),
        text: (element.innerText || element.textContent || element.value || "")
            .trim().slice(0, 120),
        disabled: Boolean(element.disabled) || element.getAttribute("aria-disabled") === "true",
    })).filter((item) => {
        const label = `${item.text} ${item.title || ""} ${item.aria_label || ""}`;
        return /(next|prev|previous|page|下一|上一|翻页|页码)/i.test(label);
    }).slice(0, 40);

    const toolbarCandidates = limited(document.querySelectorAll(
        '[class*="toolbar" i], [id*="toolbar" i], [class*="pager" i], '
        + '[id*="pager" i], [class*="navigation" i], [id*="navigation" i]'
    )).map(describe);

    return {
        frame_url: window.location.href,
        title: document.title,
        ready_state: document.readyState,
        active_tab_count: document.querySelectorAll("#prev_tab li.active").length,
        document_module_states: moduleStates,
        resources: {
            iframes: limited(document.querySelectorAll("iframe")).map(describeResource),
            embeds: limited(document.querySelectorAll("embed")).map(describeResource),
            objects: limited(document.querySelectorAll("object")).map(describeResource),
            canvases: limited(document.querySelectorAll("canvas")).map((element) => ({
                ...describe(element),
                width: element.width,
                height: element.height,
            })),
            images: limited(document.querySelectorAll("img")).map(describeResource),
        },
        viewport: {
            scroll_x: window.scrollX,
            scroll_y: window.scrollY,
            inner_width: window.innerWidth,
            inner_height: window.innerHeight,
            document_scroll_height: document.documentElement.scrollHeight,
            body_scroll_height: document.body ? document.body.scrollHeight : null,
        },
        scroll_containers: scrollContainers,
        page_signals: pageSignals,
        controls,
        toolbar_candidates: toolbarCandidates,
    };
}"""
