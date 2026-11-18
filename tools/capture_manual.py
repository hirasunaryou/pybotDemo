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
            # Verify spoken text is staged for review, NEVER auto-submitted.
            voice_page = browser.new_page(viewport={"width": 1280, "height": 840})
            voice_page.add_init_script("""(function() {
              class MockSpeech {
                start() {
                  setTimeout(() => {
                    if (this.onstart) this.onstart();
                    if (this.onresult) this.onresult({ results: [
                      Object.assign([{ transcript: "Why is the sky blue?" }], { isFinal: true })
                    ]});
                    if (this.onend) this.onend();
                  }, 25);
                }
                stop() { if (this.onend) this.onend(); }
              }
              window.SpeechRecognition = MockSpeech;
              window.webkitSpeechRecognition = MockSpeech;
            })();""")
            voice_page.goto(url, wait_until="domcontentloaded")
            voice_page.locator("#voiceBtn").click()
            voice_page.wait_for_function(
                'document.querySelector("#questionInput").value.includes("Why is the sky blue?")',
                timeout=15000)
            voice_page.wait_for_function(
                'document.querySelector("#voiceBtn").getAttribute("aria-pressed") === "false"',
                timeout=15000)
            assert voice_page.locator(".bubble-row.bot").count() == 0, "Voice auto-sent the question"
            voice_page.close()
            print("Voice dictation browser-mock test passed: editable transcript, no auto-send")

            unsupported = browser.new_page()
            unsupported.add_init_script("""(function() {
                window.SpeechRecognition = undefined;
                window.webkitSpeechRecognition = undefined;
            })();""")
            unsupported.goto(url, wait_until="domcontentloaded")
            assert unsupported.locator("#voiceBtn").is_disabled()
            assert "Win+H" in unsupported.locator("#voiceStatus").inner_text()
            unsupported.close()
            print("Voice unsupported-browser fallback test passed")
            print("Captured real PyBot UI screenshots in", output)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
