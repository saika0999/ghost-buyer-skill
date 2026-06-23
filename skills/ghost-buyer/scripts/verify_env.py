#!/usr/bin/env python3
"""Check whether the Ghost Buyer runtime dependencies are available."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


REQUIRED_PYTHON = (3, 11)
OPTIONAL_MODULES = [
    ("browser_use", "browser-use"),
    ("crawl4ai", "crawl4ai"),
    ("playwright", "playwright"),
    ("bs4", "beautifulsoup4"),
    ("lxml", "lxml"),
    ("pydantic", "pydantic"),
]


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def playwright_has_chromium() -> str:
    if not module_available("playwright"):
        return "not checked"
    local_browsers = Path.cwd() / ".venv" / "playwright-browsers"
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and local_browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_browsers)
    executable = shutil.which("python") or sys.executable
    code = (
        "from playwright.sync_api import sync_playwright\n"
        "with sync_playwright() as p:\n"
        "    print(p.chromium.executable_path)\n"
    )
    try:
        result = subprocess.run(
            [executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:  # pragma: no cover - diagnostic path
        return f"error: {exc}"
    if result.returncode == 0 and result.stdout.strip():
        path = Path(result.stdout.strip())
        if path.exists():
            return str(path)
        return f"missing executable at {path}; run `python -m playwright install chromium`"
    return "missing; run `python -m playwright install chromium`"


def main() -> int:
    ok = True
    script_dir = Path(__file__).resolve().parent
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    if "PLAYWRIGHT_BROWSERS_PATH" in os.environ:
        print(f"INFO PLAYWRIGHT_BROWSERS_PATH={os.environ['PLAYWRIGHT_BROWSERS_PATH']}")
    if sys.version_info < REQUIRED_PYTHON:
        ok = False
        print("FAIL python_version: need Python >= 3.11 for browser-use")
    else:
        print("OK   python_version")

    for module_name, package_name in OPTIONAL_MODULES:
        if module_available(module_name):
            print(f"OK   import {module_name}")
        else:
            ok = False
            print(f"MISS import {module_name} ({package_name})")

    chromium_status = playwright_has_chromium()
    print(f"INFO playwright_chromium: {chromium_status}")
    if chromium_status.startswith("missing") or chromium_status.startswith("error"):
        ok = False

    if not ok:
        print("\nInstall with:")
        print(f"  python -m pip install -r {script_dir / 'requirements.txt'}")
        print("  PLAYWRIGHT_BROWSERS_PATH=.venv/playwright-browsers python -m playwright install chromium")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
