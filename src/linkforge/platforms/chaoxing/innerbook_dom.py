"""DOM probes restricted to the observed Chaoxing continuous-scroll book reader."""

import json

from linkforge.platforms.chaoxing.dom import FRAME_PATH_SCRIPT

INNERBOOK_VIEWER_SCRIPT = (
    "() => {"
    + FRAME_PATH_SCRIPT
    + r"""
    const container = document.querySelector('#Readweb');
    const route = window.location.pathname;
    if (!route.includes('/readsvr/book/mooc/') || !container) {
        return {innerbook_viewer: null};
    }
    const pages = Array.from(container.querySelectorAll('.duxiuimg'));
    const inputs = pages.map(page => page.querySelector('input.Jimg[type="image"]'));
    if (!pages.length || inputs.some(input => !input)) {
        return {innerbook_viewer: null};
    }
    const rect = container.getBoundingClientRect();
    const visible = pages.filter(page => {
        const pageRect = page.getBoundingClientRect();
        return pageRect.bottom > rect.top && pageRect.top < rect.bottom;
    });
    // Cache native image-load checks; placeholder inputs are never readiness evidence.
    const cache = window.__linkforgeInnerbookImages ||= new Map();
    const visibleSources = new Set(visible.map(page =>
        page.querySelector('input.Jimg[type="image"]').getAttribute('src') || ''));
    for (const src of cache.keys()) {
        if (!visibleSources.has(src)) cache.delete(src);
    }
    const ready = visible.length > 0 && visible.every(page => {
        const input = page.querySelector('input.Jimg[type="image"]');
        const src = input.getAttribute('src') || '';
        const message = page.querySelector('.J_Msg');
        if (!src || /(?:^|\/)dot\.gif(?:$|[?#])/.test(src)
            || (message && getComputedStyle(message).display !== 'none')) {
            return false;
        }
        let image = cache.get(src);
        if (!image) {
            image = new Image();
            image.src = input.src;
            cache.set(src, image);
        }
        return image.complete && image.naturalWidth > 0;
    });
    return {innerbook_viewer: {
        url: window.location.href,
        frame_path: framePath,
        scroll_y: container.scrollTop,
        height: container.clientHeight,
        scroll_height: container.scrollHeight,
        page_count: pages.length,
        visible_pages_ready: document.readyState === 'complete' && ready,
    }};
}"""
)


def build_innerbook_action_script(
    module_path: tuple[int, ...], reader_path: tuple[int, ...], delta: int
) -> str:
    """Reveal one outer module and scroll only its uniquely associated reader."""
    return (
        "() => {"
        + FRAME_PATH_SCRIPT
        + f"""
        const modulePath = {json.dumps(module_path)};
        const readerPath = {json.dumps(reader_path)};
        const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
        if (same(framePath, modulePath.slice(0, -1))) {{
            for (const iframe of document.querySelectorAll('iframe')) {{
                if (iframe.contentWindow === window[modulePath[modulePath.length - 1]]) {{
                    iframe.scrollIntoView({{block: 'center'}});
                }}
            }}
        }}
        if (same(framePath, readerPath)
            && location.pathname.includes('/readsvr/book/mooc/')) {{
            const container = document.querySelector('#Readweb');
            if (container) {{
                container.scrollBy({{top: {delta}, behavior: 'instant'}});
                return {{matched: true}};
            }}
        }}
        return {{matched: false}};
    }}"""
    )
