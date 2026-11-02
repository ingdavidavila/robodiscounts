def fetch_html(url: str, timeout_ms: int = 45000, screenshot_path: str = None) -> str:
    """Load a page in headless Chromium (handles JS rendering and basic bot checks)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = ctx.new_page()
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)  # let price widgets render
        html = page.content()
        if screenshot_path:
            page.screenshot(path=screenshot_path, full_page=True)
        browser.close()
        return html
