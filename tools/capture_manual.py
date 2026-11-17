"""Capture ACTUAL UI screenshots against the real pinned upstream PyBot.

Runs only in a browser-capable documentation workflow, not on user's machines.
Requires Playwright in CI; the application itself stays dependency-free.
"""
from pathlib import Path
import threading
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.bootstrap import ensure_upstream, PROJECT_ROOT
from demo.server import serve


def main():
    from playwright.sync_api import sync_playwright
    source = ensure_upstream()
    url, server = serve(source)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = PROJECT_ROOT / "docs" / "images"
    output.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1460, "height": 1120}, device_scale_factor=1)
            page.goto(url, wait_until="domcontentloaded")
            page.locator("#statusDot.ready").wait_for(timeout=120000)
            page.locator('button[data-scenario="0"]').click()
            page.locator("#sendBtn").click()
            page.locator(".bubble-row.bot").first.wait_for(timeout=180000)
            page.locator(".workspace").screenshot(path=str(output / "overview.png"))
            page.locator(".candidate-item").first.click()
            page.locator(".code-line").first.wait_for(timeout=120000)
            page.locator("#traceBtn").click()
            page.locator(".trace-note.good, .trace-note.warn").first.wait_for(timeout=180000)
            page.locator(".insight-panel").screenshot(path=str(output / "code-trace.png"))
            print("Captured real PyBot UI screenshots in", output)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
