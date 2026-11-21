"""Visual QA for two portable learning documents, using real browser rendering."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo.bootstrap import PROJECT_ROOT


def main():
    from playwright.sync_api import sync_playwright

    docs = PROJECT_ROOT / "docs"
    images = docs / "images"
    images.mkdir(parents=True, exist_ok=True)

    manual = docs / "MANUAL.html"
    raw = manual.read_text(encoding="utf-8")
    assert '<style>' in raw and "data:image/png;base64," in raw
    assert 'href="manual.css"' not in raw
    assert 'src="images/' not in raw
    assert raw.count("data:image/png;base64,") >= 2
    assert len(raw) > 100000, "The standalone manual should embed original images"

    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page = context.new_page()
        page.goto(manual.as_uri(), wait_until="load")
        assert page.locator(".manual-hero").count() == 1
        assert page.locator(".guide-nav").count() == 1
        assert page.locator(".step-card").count() == 3
        assert page.locator("#voice").count() == 1
        screenshots = page.locator(".screen-figure img")
        assert screenshots.count() == 2, "Expected app overview and traced call map"
        for picture in screenshots.all():
            assert picture.evaluate("(img) => img.complete && img.naturalWidth > 100")
        assert page.locator(".trace-figure img").evaluate("(img) => img.complete && img.naturalWidth > 100")
        assert page.locator(".film-manual-visual img").evaluate(
            "(img) => img.complete && img.naturalWidth > 100"), "Video-style player screenshot did not load"
        color = page.locator(".guide-top").evaluate("(el) => getComputedStyle(el).backgroundColor")
        assert color != "rgba(0, 0, 0, 0)", "Manual stylesheet did not load"
        page.screenshot(path=str(images / "manual-preview.png"), full_page=False)
        print("Standalone HTML file passed CSS and real image test:", manual.name)

        research = docs / "RESEARCH.html"
        page.goto(research.as_uri(), wait_until="load")
        assert page.locator(".pipeline").count() == 1
        assert page.locator(".source-card").count() >= 8
        assert page.locator("a[href='https://doi.org/10.1145/365153.365168']").count() == 1
        research_bg = page.locator("header").evaluate("(el) => getComputedStyle(el).backgroundColor")
        assert research_bg != "rgba(0, 0, 0, 0)"
        page.screenshot(path=str(images / "research-preview.png"), full_page=False)
        print("Standalone research atlas passed style and citation checks:", research.name)
        browser.close()


if __name__ == "__main__":
    main()
