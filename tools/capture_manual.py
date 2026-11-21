"""Capture ACTUAL UI screenshots against the real pinned upstream PyBot.

Runs only in a browser-capable documentation workflow, not on user's machines.
Requires Playwright in CI; the application itself stays dependency-free.
"""
from pathlib import Path
import threading
import sys
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from demo.bootstrap import ensure_upstream, PROJECT_ROOT
from demo.server import serve


def contrast_ratio(first, second):
    def luminance(color):
        nums = [float(v) for v in re.findall(r"[\d.]+", color)[:3]]
        if len(nums) != 3:
            raise AssertionError("Not an RGB color: " + color)
        rgb = [v / 255 for v in nums]
        rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in rgb]
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
    a, b = sorted([luminance(first), luminance(second)], reverse=True)
    return (a + .05) / (b + .05)


def assert_readable(page, mode):
    pairs = (
        (".panel-head h2", ".panel-head"),
        (".composer textarea", ".composer textarea"),
        (".scenario-chips button.active", ".scenario-chips button.active"),
        (".candidate-item.picked .candidate-name", ".candidate-item.picked"),
        (".result-module", ".tab-body"),
    )
    for foreground, background in pairs:
        fg = page.locator(foreground).first.evaluate("(el) => getComputedStyle(el).color")
        bg = page.locator(background).first.evaluate("(el) => getComputedStyle(el).backgroundColor")
        ratio = contrast_ratio(fg, bg)
        assert ratio >= 4.5, (mode, foreground, fg, bg, ratio)
    print(mode, "contrast checks passed (>= 4.5:1),", len(pairs), "text/background pairs")


def assert_japanese_glyphs(page):
    # When CJK fonts are absent, two unrelated ideographs often rasterise
    # as the SAME replacement square. Canvas pixels make the test explicit.
    distinct = page.locator("body").evaluate("""(el) => {
      function pixels(letter) {
        const canvas = document.createElement("canvas");
        canvas.width = 88; canvas.height = 88;
        const c = canvas.getContext("2d");
        c.fillStyle = "#fff"; c.fillRect(0,0,88,88);
        c.fillStyle = "#000"; c.font = '60px "Noto Sans CJK JP", "IPAGothic", sans-serif';
        c.fillText(letter, 10, 64);
        return c.getImageData(0,0,88,88).data;
      }
      const first=pixels("会"), second=pixels("話");
      let changed=0;
      for(let i=0;i<first.length;i+=4) {
        if (Math.abs(first[i]-second[i])>60) changed++;
      }
      return changed;
    }""")
    assert distinct > 100, "CJK text resembles replacement squares; install Japanese fonts"
    print("Japanese glyph rasterization verified:", distinct, "different pixels")


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
            page.emulate_media(color_scheme="dark")
            page.goto(url, wait_until="domcontentloaded")
            assert page.locator("html").get_attribute("data-theme") == "dark"
            assert_japanese_glyphs(page)
            page.locator("#statusDot.ready").wait_for(timeout=120000)
            page.locator('button[data-scenario="0"]').click()
            page.locator("#sendBtn").click()
            page.locator(".bubble-row.bot").first.wait_for(timeout=180000)
            assert "PyBot純正" in page.locator(".reply-provenance").first.inner_text()
            assert page.locator("#jaBridgeBtn").get_attribute("aria-pressed") == "false"
            original_font = float(page.locator(".bubble-row.bot .bubble").first.evaluate(
                "(el) => parseFloat(getComputedStyle(el).fontSize)"))
            page.locator("#fontPlus").click()
            assert "125%" in page.locator("#fontScale").inner_text()
            larger_font = float(page.locator(".bubble-row.bot .bubble").first.evaluate(
                "(el) => parseFloat(getComputedStyle(el).fontSize)"))
            assert larger_font > original_font * 1.2, (larger_font, original_font)
            page.locator("#presentationToggle").click()
            assert page.locator("html").get_attribute("data-presentation") == "on"
            page.locator("#presentationToggle").click()
            page.locator("#fontMinus").click()
            assert "100%" in page.locator("#fontScale").inner_text()
            print("Presentation font scaling and focused mode: passed")
            assert_readable(page, "Dark")
            page.locator(".workspace").screenshot(path=str(output / "overview.png"))
            # Real light-mode screenshot from the SAME conversation, not a design mock.
            page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == "light"
            assert_readable(page, "Light")
            page.locator(".workspace").screenshot(path=str(output / "overview-light.png"))
            page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == "dark"
            page.locator(".candidate-item").first.click()
            page.locator(".code-line").first.wait_for(timeout=120000)
            page.locator("#traceBtn").click()
            page.locator(".trace-note.good, .trace-note.warn").first.wait_for(timeout=180000)
            page.locator(".insight-panel").screenshot(path=str(output / "code-trace.png"))
            page.locator('button[data-tab="architecture"]').click()
            assert page.locator(".map-step").count() == 4
            assert page.locator(".map-function").count() > 0
            assert page.locator(".map-flag.lab").count() == 1
            page.locator(".insight-panel").screenshot(path=str(output / "trace-map.png"))
            page.locator(".map-function").first.click()
            assert page.locator('button[data-tab="code"]').get_attribute("aria-selected") == "true"
            print("Replay hook phases and clickable function call map: passed")

            # A real source-code film is seekable, can play and can jump
            # backwards to the beginning without modifying the real chat.
            page.locator('button[data-tab="architecture"]').click()
            page.locator("#filmGenerateBtn").click()
            page.locator("#filmPlayer:not(.hidden)").wait_for(timeout=180000)
            page.locator(".film-line.focused").first.wait_for(timeout=60000)
            frame_count = int(page.locator("#filmSeek").get_attribute("max"))
            assert frame_count > 5, "Expected multiple observed code frames"
            page.locator("#filmNext").click()
            assert page.locator("#filmSeek").input_value() == "1"
            # Emulate user dragging the range thumb to a mid-film frame:
            mid = frame_count // 2
            page.locator("#filmSeek").evaluate("""(element, position) => {
              element.value=String(position);
              element.dispatchEvent(new Event("input",{bubbles:true}));
            }""", mid)
            assert int(page.locator("#filmSeek").input_value()) == mid
            assert ("再生位置 " + str(mid + 1)) in page.locator("#filmTime").inner_text()
            page.locator("#filmFirst").click()
            assert page.locator("#filmSeek").input_value() == "0"
            page.locator("#filmPlay").click()
            page.wait_for_timeout(500)
            assert int(page.locator("#filmSeek").input_value()) > 0
            page.locator("#filmPlay").click()
            page.locator("#filmLast").click()
            assert page.locator("#filmSeek").input_value() == str(frame_count)
            page.locator("#filmPrevious").click()
            assert int(page.locator("#filmSeek").input_value()) == frame_count - 1
            page.locator("#filmExpand").click()
            assert page.locator("#filmPlayer").get_attribute("class").find("expanded") >= 0
            page.locator("#filmExpand").click()
            assert "expanded" not in (page.locator("#filmPlayer").get_attribute("class") or "")
            print("Film player: play/pause, step, rewind, seek last and fullscreen checks passed")

            # Validate the exact example supplied in the workshop: PyBot's
            # literal average explanation must lead to maths.py L5101.
            math_page = browser.new_page(viewport={"width": 1460, "height": 1080})
            math_page.emulate_media(color_scheme="light")
            math_page.goto(url, wait_until="domcontentloaded")
            math_page.locator("#questionInput").fill("Do you know how to calculate mean?")
            math_page.locator("#sendBtn").click()
            math_page.locator(".bubble-row.bot").first.wait_for(timeout=180000)
            raw_math = math_page.locator(".bubble-row.bot .bubble").first.inner_text()
            assert "The mean, which is what most people mean by an average" in raw_math, raw_math[:280]
            math_page.locator('button[data-tab="architecture"]').click()
            math_page.locator("#filmGenerateBtn").click()
            math_page.locator("#filmPlayer:not(.hidden)").wait_for(timeout=180000)
            math_page.locator(".film-line.focused").first.wait_for(timeout=60000)
            math_page.locator("#filmLast").click()
            math_page.locator("#filmFile").wait_for(timeout=60000)
            assert "bot/knowledge/maths.py" in math_page.locator("#filmFile").inner_text()
            assert "L5101" in math_page.locator("#filmFile").inner_text()
            assert "静的" in math_page.locator("#filmElapsed").inner_text() or "ソース調査" in math_page.locator("#filmElapsed").inner_text()
            assert "元の回答と完全一致" in math_page.locator("#filmPurpose").inner_text()
            math_page.locator(".film-line.focused").first.wait_for(timeout=20000)
            math_page.locator("#filmPlayer").screenshot(path=str(output / "code-film.png"))
            math_page.close()
            print("Exact user average-example answer matched maths.py L5101 in last film frame")

            page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == "light"
            page.reload(wait_until="domcontentloaded")
            assert page.locator("html").get_attribute("data-theme") == "light", "Stored theme was not retained"
            page.locator("#themeToggle").click()
            assert page.locator("html").get_attribute("data-theme") == "dark"

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.emulate_media(color_scheme="light")
            mobile.goto(url, wait_until="domcontentloaded")
            assert mobile.locator("html").get_attribute("data-theme") == "light"
            size = mobile.locator("html").evaluate(
                "(el) => ({ width: el.clientWidth, scroll: el.scrollWidth })")
            assert size["scroll"] <= size["width"] + 1, ("mobile horizontal overflow", size)
            mobile.close()
            print("Desktop theme persistence and mobile width: passed")
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
            # Playwright wait_for_function uses eval and is correctly blocked by
            # our app's strict Content-Security-Policy. Use direct locator reads.
            voice_page.wait_for_timeout(250)
            assert "Why is the sky blue?" in voice_page.locator("#questionInput").input_value()
            assert voice_page.locator("#voiceBtn").get_attribute("aria-pressed") == "false"
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

            # The translation experiment is intentionally isolated from
            # real on-device models. A mocked browser model verifies that the
            # untranslated original PyBot reply and both bridge texts appear.
            translate_page = browser.new_page(viewport={"width": 1280, "height": 870})
            translate_page.add_init_script("""(function() {
              class MockTranslator {
                static create(options) {
                  return Promise.resolve({
                    translate: async (text) => options.sourceLanguage === "ja"
                      ? "Why is the sky blue?"
                      : "空が青く見える理由を説明します（模擬和訳）。",
                    destroy: () => {}
                  });
                }
              }
              window.Translator = MockTranslator;
            })();""")
            translate_page.goto(url, wait_until="domcontentloaded")
            translate_page.locator("#jaBridgeBtn").click()
            translate_page.locator("#jaBridgeBtn.is-on").wait_for(timeout=12000)
            translate_page.locator("#questionInput").fill("空が青いのはなぜ？")
            translate_page.locator("#sendBtn").click()
            translate_page.locator(".bubble-row.bot").first.wait_for(timeout=180000)
            assert "空が青いのはなぜ？" in translate_page.locator(".bubble-row.user .bubble").last.inner_text()
            assert "Why is the sky blue?" in translate_page.locator(".message-provenance.lab").last.inner_text()
            assert "PyBot純正" in translate_page.locator(".reply-provenance").last.inner_text()
            assert "模擬和訳" in translate_page.locator(".translated-reply").last.inner_text()
            translate_page.locator("#jaBridgeBtn").click()
            assert translate_page.locator("#jaBridgeBtn").get_attribute("aria-pressed") == "false"
            translate_page.close()
            print("Japanese bridge browser-mock end-to-end: raw PyBot reply + distinct Lab translations passed")

            unsupported_translation = browser.new_page()
            unsupported_translation.add_init_script("""(function() {
              window.Translator = undefined;
            })();""")
            unsupported_translation.goto(url, wait_until="domcontentloaded")
            assert unsupported_translation.locator("#jaBridgeBtn").is_disabled()
            unsupported_translation.close()
            print("Unsupported Translator API degrades cleanly to pure PyBot")
            print("Captured real PyBot UI screenshots in", output)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
