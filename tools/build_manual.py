"""Build a genuinely standalone illustrated HTML manual.

All layout CSS and REAL screenshots are embedded in docs/MANUAL.html itself.
No CSS, JS, fonts, images or network requests are needed to READ this file.
Edit docs/MANUAL.source.html and docs/manual.css instead of generated output.
"""
import argparse
import base64
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SOURCE = DOCS / "MANUAL.source.html"
STYLES = DOCS / "manual.css"
OUTPUT = DOCS / "MANUAL.html"
PLACEHOLDER = "<!--MANUAL_STYLES-->"
ASSET = re.compile(r'(?P<prefix>(?:src|href)=")images/(?P<name>[a-zA-Z0-9_-]+\.png)"')


def render():
    html = SOURCE.read_text(encoding="utf-8")
    css = STYLES.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise RuntimeError("Missing standalone style insertion marker")
    html = html.replace(PLACEHOLDER, "<style>\n" + css + "\n</style>")
    images = set()

    def replace_asset(match):
        name = match.group("name")
        asset = DOCS / "images" / name
        if not asset.is_file():
            raise FileNotFoundError("Missing REAL screenshot: " + str(asset))
        images.add(name)
        image_data = base64.b64encode(asset.read_bytes()).decode("ascii")
        return match.group("prefix") + "data:image/png;base64," + image_data + '"'

    html = ASSET.sub(replace_asset, html)
    if not images or "overview.png" not in images or "code-trace.png" not in images:
        raise RuntimeError("Real screenshot images must be embedded")
    if 'href="manual.css"' in html or 'src="images/' in html:
        raise RuntimeError("HTML manual contains unresolved external assets")
    return "<!-- Generated standalone manual: edit MANUAL.source.html, manual.css. -->\n" + html + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="fail if generated manual is stale")
    args = parser.parse_args()
    result = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != result:
            print("Standalone manual outdated; run: python tools/build_manual.py", file=sys.stderr)
            return 1
        print("Standalone HTML verified:", len(result), "characters")
        return 0
    OUTPUT.write_text(result, encoding="utf-8")
    print("Built:", OUTPUT, "(self-contained:", len(result), "characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
