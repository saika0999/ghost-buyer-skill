#!/usr/bin/env python3
"""Launch a long-lived Chrome session for Taobao/Tmall browsing."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


DEFAULT_CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def cdp_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
            json.load(response)
        return True
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def cdp_pages(port: int) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
            targets = json.load(response)
        if isinstance(targets, list):
            return [target for target in targets if target.get("type") == "page"]
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        pass
    return []


def open_cdp_tab(port: int, url: str) -> bool:
    encoded_url = urllib.parse.quote(url, safe="")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/json/new?{encoded_url}",
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            json.load(response)
        return True
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome-path", default=DEFAULT_CHROME_MAC)
    parser.add_argument("--profile-dir", default="work/shopping-sessions/taobao-cdp")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument(
        "--url",
        default="https://login.taobao.com/member/login.jhtml",
        help="Initial page to open for manual login.",
    )
    parser.add_argument(
        "--proxy-mode",
        choices=["direct", "system"],
        default="direct",
        help="Use direct networking by default for Taobao/Tmall. Use system only when the user explicitly wants the OS proxy/VPN.",
    )
    args = parser.parse_args()

    chrome_path = Path(args.chrome_path)
    if not chrome_path.exists():
        print(f"Chrome executable not found: {chrome_path}", file=sys.stderr)
        return 1

    if cdp_ready(args.port):
        print(f"CDP already ready: http://127.0.0.1:{args.port}")
        print(f"requested_profile_dir: {Path(args.profile_dir)}")
        if args.proxy_mode == "direct":
            print(
                "proxy_mode: direct requested; existing Chrome keeps the proxy mode it was originally launched with. "
                "Restart the CDP Chrome if Taobao is still showing IP/risk-control blocks."
            )
        if not cdp_pages(args.port):
            if open_cdp_tab(args.port, args.url):
                print(f"opened session anchor tab: {args.url}")
            else:
                print(
                    "CDP is ready but has no page targets; open a Taobao/Tmall tab manually to keep the session warm.",
                    file=sys.stderr,
                )
        return 0

    profile_dir = Path(args.profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    command = [
        str(chrome_path),
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={profile_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        args.url,
    ]
    if args.proxy_mode == "direct":
        command.insert(-1, "--no-proxy-server")
    subprocess.Popen(command, start_new_session=True)

    for _ in range(30):
        if cdp_ready(args.port):
            print(f"CDP ready: http://127.0.0.1:{args.port}")
            print(f"profile_dir: {profile_dir}")
            return 0
        time.sleep(0.5)

    print(
        f"Chrome launched, but CDP was not ready on http://127.0.0.1:{args.port}. "
        "Check the visible Chrome window.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
