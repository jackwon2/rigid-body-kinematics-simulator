"""Regenerate the precompiled Tailwind CSS embedded in index.html.

Why: index.html used to load the Tailwind Play CDN (cdn.tailwindcss.com). That script compiles
CSS inside the browser and re-scans the whole page after every DOM change, which made the
simulator lag badly on phones and tablets. Instead, the CSS for the classes actually used is
compiled once with the same Tailwind version and stored in <style id="tailwind-css">.

When to run: after adding Tailwind classes that are not used anywhere in index.html yet
(new classes have no effect until this is run). Editing text or JS logic does not need it.

How it works: every class-like token in index.html (HTML attributes and JS strings, like
Tailwind's own content scanner) is handed to the official Tailwind 3.4.17 compiler, running in
headless Chrome/Edge; the generated CSS is written into the <style id="tailwind-css"> block.

Requirements: Python 3, Playwright (pip install playwright), Google Chrome or Microsoft Edge
(or `python -m playwright install chromium`), and an internet connection.

Usage:  python tools/build_tailwind_css.py
"""
import json
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "index.html"
TAILWIND_URL = "https://cdn.tailwindcss.com/3.4.17"
# hoverOnlyWhenSupported: hover colours apply only with a real mouse, so buttons do not stay
# "stuck" in their hover colour after a tap on touch screens.
CONFIG = {"future": {"hoverOnlyWhenSupported": True}}

BLOCK = re.compile(r'(<style id="tailwind-css">)(.*?)(</style>)', re.S)


def class_candidates(text):
    """Every token that could be a class name (superset; Tailwind ignores the rest)."""
    tokens = re.split(r"""[\s"'`<>=;{}()\\,]+""", text)
    return sorted({t for t in tokens if 0 < len(t) < 100})


def minify(css):
    css = re.sub(r"/\*(?!\s*!).*?\*/", "", css, flags=re.S)  # keep only the /*! license */ comment
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};>])\s*", r"\1", css)
    css = css.replace(";}", "}")
    # Empty custom properties need a space ("--tw-pan-x: ;"), or older Safari drops the declaration
    css = re.sub(r"(--[\w-]+):(?=[;}])", r"\1: ", css)
    return css.strip()


def compile_css(classes):
    page_html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<script src="{TAILWIND_URL}"></script>'
        f"<script>tailwind.config = {json.dumps(CONFIG)};</script>"
        '</head><body><div id="probe"></div></body></html>'
    )
    with sync_playwright() as p:
        browser = None
        for opts in ({"channel": "chrome"}, {"channel": "msedge"}, {}):
            try:
                browser = p.chromium.launch(headless=True, **opts)
                break
            except Exception:  # noqa: BLE001 - try the next browser
                continue
        if browser is None:
            sys.exit("No Chrome/Edge found. Install one, or run: python -m playwright install chromium")
        page = browser.new_page()
        page.set_content(page_html, wait_until="load")
        page.evaluate("cls => document.getElementById('probe').setAttribute('class', cls)", " ".join(classes))
        # Wait until the compiler's <style> output stops changing
        css, stable = "", 0
        for _ in range(60):
            page.wait_for_timeout(250)
            now = page.evaluate(
                "() => [...document.querySelectorAll('style')].map(s => s.textContent)"
                ".filter(t => t.includes('--tw-')).sort((a, b) => b.length - a.length)[0] || ''"
            )
            stable = stable + 1 if now and now == css else 0
            css = now
            if stable >= 3:
                break
        browser.close()
    if ".flex" not in css or ".hidden" not in css:
        sys.exit("Tailwind output looks incomplete; is the internet connection working?")
    return css


def main():
    html = HTML.read_text(encoding="utf-8")
    m = BLOCK.search(html)
    if not m:
        sys.exit('index.html has no <style id="tailwind-css"> block')
    # Scan everything except the previous output (its selectors would keep stale classes alive)
    scanned = html[: m.start(2)] + html[m.end(2):]
    css = minify(compile_css(class_candidates(scanned)))
    new_html = html[: m.start(2)] + "\n" + css + "\n  " + html[m.end(2):]
    HTML.write_text(new_html, encoding="utf-8", newline="\n")
    print(f"Wrote {len(css) / 1024:.1f} KB of Tailwind CSS into {HTML.name}")


if __name__ == "__main__":
    main()
