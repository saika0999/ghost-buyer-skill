#!/usr/bin/env python3
"""Launch Chromium with Playwright and verify a basic page render."""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    local_browsers = Path.cwd() / ".venv" / "playwright-browsers"
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and local_browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_browsers)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content("<title>ghost-buyer smoke</title><h1>ok</h1>")
        title = page.title()
        text = page.locator("h1").inner_text()
        browser.close()
    if title != "ghost-buyer smoke" or text != "ok":
        raise RuntimeError("browser smoke test rendered unexpected content")
    print("OK browser_smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
