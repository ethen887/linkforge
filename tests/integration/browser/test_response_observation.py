"""浏览器响应观察只收集指定主页面 UI 请求，并可靠移除监听器。"""

from linkforge.browser.playwright import PlaywrightBrowser


def test_response_observation_filters_requests_and_releases_listener():
    with PlaywrightBrowser(headless=True, timeout_ms=2_000) as browser:
        page = browser._require_page()
        requests = []

        def route(request):
            requests.append(request.request.url)
            if request.request.url == "https://example.test/":
                request.fulfill(content_type="text/html", body="<p>Local fixture</p>")
            else:
                request.fulfill(json={"status": True, "secret": "local-fixture"})

        page.route("**/*", route)
        page.goto("https://example.test/")
        with browser.capture_json_responses("/submit") as responses:
            assert responses == []
            assert len(requests) == 1  # 监听本身不发起请求。
            page.evaluate("async () => {await fetch('/submit'); await fetch('/other', {method:'POST'});}")
            assert responses == []
            with page.expect_response(
                lambda response: (
                    response.url == "https://example.test/submit" and response.request.method == "POST"
                )
            ) as submitted:
                page.evaluate("async () => {await (await fetch('/submit', {method:'POST'})).json();}")
            submitted.value.finished()
            assert len(responses) == 1
            assert responses[0].data == {"status": True, "secret": "local-fixture"}
            assert "local-fixture" not in repr(responses[0])
        page.evaluate("async () => {await fetch('/submit', {method:'POST'});}")
        assert len(responses) == 1
