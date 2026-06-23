#!/usr/bin/env python3
"""Capture a rendered page screenshot and visible text with Playwright.

Use --profile-dir with --headful/--manual-login for ecommerce sites that
require user login. The browser profile stores cookies locally.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ACCESS_DENIED_MARKERS = [
    "\u4eb2\uff0c\u8bbf\u95ee\u88ab\u62d2\u7edd",
    "\u8bbf\u95ee\u88ab\u62d2\u7edd",
]

HUMAN_ATTENTION_MARKERS = [
    "\u4eb2\uff0c\u8bf7\u767b\u5f55",
    "\u8bf7\u767b\u5f55",
    "\u9a8c\u8bc1\u7801",
    "\u5b89\u5168\u9a8c\u8bc1",
    "\u62d6\u52a8\u6ed1\u5757",
    "\u8d26\u53f7\u5b89\u5168",
]


def ensure_browser_path() -> None:
    local_browsers = Path.cwd() / ".venv" / "playwright-browsers"
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and local_browsers.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_browsers)


def set_window_state(page, state: str) -> bool:
    if state not in {"minimized", "maximized", "normal"}:
        return False
    try:
        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window["windowId"],
                "bounds": {"windowState": state},
            },
        )
        session.detach()
        return True
    except PlaywrightError:
        return False


def get_window_state(page) -> str | None:
    try:
        session = page.context.new_cdp_session(page)
        window = session.send("Browser.getWindowForTarget")
        session.detach()
        bounds = window.get("bounds", {})
        state = bounds.get("windowState")
        if state in {"minimized", "maximized", "normal", "fullscreen"}:
            return state
    except PlaywrightError:
        return None
    return None


def read_body_text(page, timeout: int = 3000) -> str:
    try:
        if not page.locator("body").count():
            return ""
        return page.locator("body").inner_text(timeout=timeout)
    except PlaywrightError:
        return ""


def read_page_and_frame_text(page, timeout: int = 1200) -> str:
    texts = [read_body_text(page, timeout=timeout)]
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            frame_element = frame.frame_element()
            if not frame_element.is_visible():
                continue
            if frame.locator("body").count():
                texts.append(frame.locator("body").inner_text(timeout=timeout))
        except PlaywrightError:
            continue
    return "\n".join(text for text in texts if text)


def has_access_denied(text: str) -> bool:
    return any(marker in text for marker in ACCESS_DENIED_MARKERS)


def needs_human_attention(text: str) -> bool:
    if has_access_denied(text):
        return False
    return any(marker in text for marker in HUMAN_ATTENTION_MARKERS)


def looks_incomplete_marketplace_page(url: str, text: str) -> bool:
    if not should_throttle_url(url):
        return False
    clean = text.strip()
    if len(clean) < 80:
        return True
    product_markers = [
        "\u4ef7",
        "\u5df2\u552e",
        "\u8bc4\u4ef7",
        "\u5e97\u94fa",
        "\u5b9d\u8d1d",
        "\u5546\u54c1",
        "\u5c3a\u7801",
        "\u989c\u8272",
    ]
    return not any(marker in clean for marker in product_markers)


def should_throttle_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(domain in host for domain in ("taobao.com", "tmall.com"))


def wait_for_navigation_throttle(
    url: str,
    state_path: Path,
    throttle_ms: int,
    notes: list[str],
) -> None:
    if throttle_ms <= 0 or not should_throttle_url(url):
        return
    state_path.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    last_started = 0.0
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        last_started = float(state.get("last_started", 0.0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        last_started = 0.0

    wait_seconds = max(0.0, throttle_ms / 1000 - (now - last_started))
    if wait_seconds > 0:
        notes.append(f"throttle_wait_seconds: {wait_seconds:.2f}")
        time.sleep(wait_seconds)

    state_path.write_text(
        json.dumps(
            {"last_started": time.time(), "url": url},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def close_access_denied_overlay(page) -> list[str]:
    """Close dismissible marketplace overlays without bypassing risk controls."""
    notes: list[str] = []
    body = read_page_and_frame_text(page)
    if not has_access_denied(body):
        return notes

    try:
        clicked = page.evaluate(
            """
            () => {
              const baxiaClose = document.querySelector('.baxia-dialog .baxia-dialog-close');
              if (baxiaClose) {
                baxiaClose.click();
                return 'baxia-dialog-close';
              }
              const closeWords = new Set(['\\u00d7', '\\u2715', 'x', 'X', '\\u5173\\u95ed', '\\u77e5\\u9053\\u4e86', '\\u786e\\u5b9a']);
              const closeHints = ['close', 'guanbi', 'dialog-close', 'modal-close'];
              const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style && style.visibility !== 'hidden' && style.display !== 'none' &&
                  rect.width > 0 && rect.height > 0;
              };
              const score = (el) => {
                const text = (el.innerText || el.textContent || '').trim();
                const aria = (el.getAttribute('aria-label') || '').trim();
                const title = (el.getAttribute('title') || '').trim();
                const cls = typeof el.className === 'string' ? el.className : '';
                const blob = `${text} ${aria} ${title} ${cls}`;
                const hasCloseText = closeWords.has(text) || closeWords.has(aria) || closeWords.has(title);
                const hasCloseHint = closeHints.some(hint => blob.toLowerCase().includes(hint));
                if (!hasCloseText && !hasCloseHint) return -1;
                let value = 0;
                if (hasCloseText) value += 5;
                if (hasCloseHint) value += 4;
                const rect = el.getBoundingClientRect();
                if (rect.right > window.innerWidth * 0.45 && rect.top < window.innerHeight * 0.55) value += 2;
                const zIndex = Number(window.getComputedStyle(el).zIndex) || 0;
                if (zIndex > 0) value += Math.min(3, zIndex / 1000);
                return value;
              };
              const candidates = Array.from(document.querySelectorAll('button,a,span,div,i'))
                .filter(isVisible)
                .map(el => ({ el, value: score(el) }))
                .filter(item => item.value >= 4)
                .sort((a, b) => b.value - a.value);
              if (!candidates.length) return false;
              candidates[0].el.click();
              return 'generic-close-candidate';
            }
            """
        )
        if clicked:
            page.wait_for_timeout(800)
            notes.append(f"closed_access_denied_overlay_by_click:{clicked}")
    except PlaywrightError as exc:
        notes.append(f"close_overlay_click_error: {exc}")

    body_after_click = read_page_and_frame_text(page)
    if has_access_denied(body_after_click):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            notes.append("sent_escape_for_access_denied_overlay")
        except PlaywrightError as exc:
            notes.append(f"close_overlay_escape_error: {exc}")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--out-dir", default="work/shopping-captures")
    parser.add_argument("--name", default="capture")
    parser.add_argument("--wait-ms", type=int, default=5000)
    parser.add_argument("--timeout-ms", type=int, default=45000)
    parser.add_argument(
        "--throttle-ms",
        type=int,
        default=5500,
        help="Minimum interval between Taobao/Tmall navigations across capture invocations. Use 0 to disable.",
    )
    parser.add_argument(
        "--retry-on-blocked",
        type=int,
        default=2,
        help="Reload and retry Taobao/Tmall pages when an access-denied overlay remains or the page looks incomplete.",
    )
    parser.add_argument(
        "--retry-wait-ms",
        type=int,
        default=2500,
        help="Wait before reloading a Taobao/Tmall page during retry.",
    )
    parser.add_argument(
        "--throttle-state",
        default="work/shopping-captures/.navigation-throttle.json",
        help="State file used to pace Taobao/Tmall navigation across repeated script calls.",
    )
    parser.add_argument("--headful", action="store_true")
    parser.add_argument(
        "--profile-dir",
        help="Persistent browser profile directory for logged-in marketplace sessions.",
    )
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="Open a headful browser and wait for the user to finish login before capture.",
    )
    parser.add_argument(
        "--channel",
        help="Playwright browser channel, such as msedge or chrome, when using an installed browser.",
    )
    parser.add_argument(
        "--executable-path",
        help="Explicit Chromium-family browser executable path.",
    )
    parser.add_argument(
        "--cdp-url",
        help="Connect to an already-running Chromium/Edge instance, e.g. http://127.0.0.1:9222.",
    )
    parser.add_argument(
        "--window-state",
        choices=["auto", "minimized", "normal", "maximized"],
        default="auto",
        help="Window state for headful/CDP captures. auto keeps manual-login visible and respects the current CDP window state.",
    )
    parser.add_argument(
        "--no-close-access-denied",
        action="store_true",
        help="Do not try to close visible Taobao/Tmall access-denied overlays before capture.",
    )
    parser.add_argument(
        "--no-screenshot",
        action="store_true",
        help="Capture text, links, and metadata only. Useful for minimized CDP browsing.",
    )
    parser.add_argument(
        "--keep-page-open",
        action="store_true",
        help="When connected over CDP, leave the capture tab open to keep login-gated marketplace sessions warm.",
    )
    args = parser.parse_args()

    ensure_browser_path()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = out_dir / f"{args.name}.png"
    text_path = out_dir / f"{args.name}.txt"
    links_path = out_dir / f"{args.name}.links.json"
    meta_path = out_dir / f"{args.name}.meta.txt"

    headless = not (args.headful or args.manual_login)
    window_state = args.window_state
    if window_state == "auto" and args.manual_login:
        window_state = "normal"
    controls_visible_window = bool(args.cdp_url) or not headless
    meta_notes: list[str] = [f"requested_window_state: {args.window_state}"]

    with sync_playwright() as p:
        browser = None
        connected_over_cdp = False
        launch_options = {}
        if not headless and window_state == "minimized":
            launch_options["args"] = ["--start-minimized"]
        if args.channel:
            launch_options["channel"] = args.channel
        if args.executable_path:
            launch_options["executable_path"] = args.executable_path
        if args.cdp_url:
            connected_over_cdp = True
            browser = p.chromium.connect_over_cdp(args.cdp_url)
            context = browser.contexts[0] if browser.contexts else browser.new_context(viewport={"width": 1440, "height": 1200})
            if window_state == "auto":
                current_state = get_window_state(context.pages[0]) if context.pages else None
                window_state = "minimized" if current_state == "minimized" else "normal"
                meta_notes.append(f"auto_window_state_from_cdp: {current_state or 'unknown'} -> {window_state}")
            if window_state in {"minimized", "maximized", "normal"} and context.pages:
                if set_window_state(context.pages[0], window_state):
                    meta_notes.append("set_window_state_before_new_page")
            page = context.new_page()
        elif args.profile_dir:
            if window_state == "auto":
                window_state = "normal"
                meta_notes.append("auto_window_state_defaulted_to_normal_for_profile")
            profile_dir = Path(args.profile_dir)
            profile_dir.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                str(profile_dir),
                headless=headless,
                viewport={"width": 1440, "height": 1200},
                **launch_options,
            )
            page = context.pages[0] if context.pages else context.new_page()
        else:
            if window_state == "auto":
                window_state = "normal"
                meta_notes.append("auto_window_state_defaulted_to_normal")
            browser = p.chromium.launch(headless=headless, **launch_options)
            context = browser.new_context(viewport={"width": 1440, "height": 1200})
            page = context.new_page()
        meta_notes.append(f"window_state: {window_state}")
        page.set_default_timeout(args.timeout_ms)
        if controls_visible_window and window_state in {"minimized", "maximized", "normal"}:
            if set_window_state(page, window_state):
                meta_notes.append("set_window_state_before_navigation")
        try:
            wait_for_navigation_throttle(
                args.url,
                Path(args.throttle_state),
                args.throttle_ms,
                meta_notes,
            )
            max_attempts = max(1, args.retry_on_blocked + 1)
            for attempt in range(max_attempts):
                if attempt == 0:
                    page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout_ms)
                else:
                    meta_notes.append(f"retry_reload_attempt: {attempt + 1}/{max_attempts}")
                    page.wait_for_timeout(args.retry_wait_ms)
                    page.reload(wait_until="domcontentloaded", timeout=args.timeout_ms)
                page.wait_for_timeout(args.wait_ms)
                if not args.no_close_access_denied:
                    meta_notes.extend(close_access_denied_overlay(page))
                    page.wait_for_timeout(500)
                body_snapshot = read_body_text(page)
                if needs_human_attention(body_snapshot):
                    meta_notes.append("human_attention_needed_after_navigation")
                    break
                if has_access_denied(body_snapshot):
                    meta_notes.append(f"access_denied_still_visible_attempt: {attempt + 1}/{max_attempts}")
                    continue
                if looks_incomplete_marketplace_page(args.url, body_snapshot):
                    meta_notes.append(
                        f"incomplete_marketplace_page_attempt: {attempt + 1}/{max_attempts}; text_len={len(body_snapshot.strip())}"
                    )
                    continue
                break
            if controls_visible_window and window_state in {"minimized", "maximized", "normal"}:
                if set_window_state(page, window_state):
                    meta_notes.append("set_window_state_after_navigation")
            if args.manual_login:
                print("Complete login or verification in the opened browser window.")
                print("Press Enter here after the page is ready to capture.")
                input()
                page.wait_for_timeout(1000)
                if not args.no_close_access_denied:
                    meta_notes.extend(close_access_denied_overlay(page))
        except PlaywrightTimeoutError as exc:
            meta_notes.append(f"timeout: {exc}")
            meta_notes.append(f"current_url_on_timeout: {page.url}")
        except PlaywrightError as exc:
            meta_notes.append(f"navigation_error: {exc}")
            meta_notes.append(f"current_url_on_navigation_error: {page.url}")
        title = page.title()
        final_url = page.url
        text = read_body_text(page, timeout=10000)
        links = page.eval_on_selector_all(
            "a",
            """els => els.map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.href
            })).filter(item => item.href || item.text)""",
        )
        if args.no_screenshot:
            meta_notes.append("screenshot_skipped")
        else:
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except PlaywrightError as exc:
                meta_notes.append(f"screenshot_error: {exc}")
                page.screenshot(path=str(screenshot_path), full_page=False)
        if not connected_over_cdp:
            context.close()
            if browser:
                browser.close()
        else:
            if args.keep_page_open:
                meta_notes.append("kept_cdp_page_open_by_request")
            elif len(context.pages) <= 1:
                meta_notes.append("kept_last_cdp_page_open_to_preserve_session")
            else:
                page.close()
                meta_notes.append("closed_cdp_capture_page")

    text_path.write_text(text, encoding="utf-8")
    links_path.write_text(json.dumps(links, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    meta_path.write_text(
        (
            f"title: {title}\n"
            f"url: {args.url}\n"
            f"final_url: {final_url}\n"
            f"profile_dir: {args.profile_dir or ''}\n"
            f"text_path: {text_path}\n"
            f"links_path: {links_path}\n"
            f"screenshot_path: {'' if args.no_screenshot else screenshot_path}\n"
            f"notes: {json.dumps(meta_notes, ensure_ascii=False)}\n"
        ),
        encoding="utf-8",
    )
    print(f"title: {title}")
    print(f"text: {text_path}")
    print(f"links: {links_path}")
    if not args.no_screenshot:
        print(f"screenshot: {screenshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
