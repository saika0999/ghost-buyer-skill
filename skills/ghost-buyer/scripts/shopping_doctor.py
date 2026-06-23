#!/usr/bin/env python3
"""Diagnose the local Taobao/Tmall Ghost Buyer runtime.

This is a status dashboard, not a bypass tool. It checks local readiness,
the live CDP browser session, login/risk-control signals, and the next
action an agent should take before shopping.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request


REQUIRED_PYTHON = (3, 11)
TAOBAO_HOST_MARKERS = ("taobao.com", "tmall.com")
ACCESS_DENIED_MARKERS = ("亲，访问被拒绝", "访问被拒绝")
LOGIN_MARKERS = ("亲，请登录", "请登录")
HUMAN_ATTENTION_MARKERS = (
    "验证码",
    "安全验证",
    "拖动滑块",
    "账号安全",
    "异常流量",
)
LOGIN_READY_MARKERS = ("账号管理", "退出", "购物车")


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def status(level: str, message: str, **extra):
    data = {"status": level, "message": message}
    data.update(extra)
    return data


def cdp_json(path: str, cdp_url: str, timeout: int = 2):
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}{path}", timeout=timeout) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def get_cdp_pages(cdp_url: str) -> list[dict]:
    targets = cdp_json("/json/list", cdp_url)
    if isinstance(targets, list):
        return [target for target in targets if target.get("type") == "page"]
    return []


def cdp_ready(cdp_url: str) -> bool:
    return isinstance(cdp_json("/json/version", cdp_url), dict)


def page_is_taobao(url: str) -> bool:
    lower = (url or "").lower()
    return any(marker in lower for marker in TAOBAO_HOST_MARKERS)


def read_visible_text(page, timeout_ms: int = 1200) -> str:
    try:
        if not page.locator("body").count():
            return ""
        texts = [page.locator("body").inner_text(timeout=timeout_ms)]
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                element = frame.frame_element()
                if not element.is_visible():
                    continue
                if frame.locator("body").count():
                    texts.append(frame.locator("body").inner_text(timeout=timeout_ms))
            except Exception:
                continue
        return "\n".join(text for text in texts if text)
    except Exception:
        return ""


def page_has_login_ready_signal(page, text: str) -> bool:
    if any(marker in text for marker in LOGIN_MARKERS):
        return False
    if any(marker in text for marker in LOGIN_READY_MARKERS):
        return True
    try:
        return bool(
            page.evaluate(
                "() => Boolean(document.querySelector('.site-nav-status-login, [href*=\"logout.jhtml\"], [href*=\"account_security\"]'))"
            )
        )
    except Exception:
        return False


def inspect_cdp_targets_only(cdp_url: str, message_prefix: str | None = None) -> dict:
    pages = get_cdp_pages(cdp_url)
    taobao_pages = [
        {
            "index": index,
            "status": "needs_review",
            "title": target.get("title") or "",
            "url": target.get("url") or "",
            "text_len": None,
        }
        for index, target in enumerate(pages)
        if page_is_taobao(target.get("url") or "")
    ]
    if not pages:
        return {
            "status": "manual_login_needed",
            "message": "CDP browser is open, but it has no inspectable page tabs. Open a Taobao/Tmall login or search tab as the session anchor.",
            "taobao_pages": [],
            "page_risk": [],
        }
    if not taobao_pages:
        return {
            "status": "manual_login_needed",
            "message": "CDP browser is open, but no Taobao/Tmall page is available as a session anchor.",
            "taobao_pages": [],
            "page_risk": [],
        }
    message = "Taobao/Tmall page targets exist, but visible login/risk state could not be inspected."
    if message_prefix:
        message = f"{message_prefix} {message}"
    return {
        "status": "needs_review",
        "message": message,
        "taobao_pages": taobao_pages,
        "page_risk": [],
    }


def inspect_cdp_pages(cdp_url: str) -> dict:
    result = {
        "status": "not_ready",
        "message": "Playwright is not installed; cannot inspect live CDP pages.",
        "taobao_pages": [],
        "page_risk": [],
    }
    if not module_available("playwright"):
        return inspect_cdp_targets_only(cdp_url, "Playwright is not installed.")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return inspect_cdp_targets_only(cdp_url, f"Playwright import failed: {exc}")

    if not get_cdp_pages(cdp_url):
        return inspect_cdp_targets_only(cdp_url)

    taobao_pages = []
    risks = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url)
            contexts = browser.contexts
            pages = [page for context in contexts for page in context.pages]
            for index, page in enumerate(pages):
                url = page.url
                if not page_is_taobao(url):
                    continue
                try:
                    title = page.title()
                except Exception:
                    title = ""
                text = read_visible_text(page)
                page_status = "unknown"
                if any(marker in text for marker in ACCESS_DENIED_MARKERS):
                    page_status = "access_denied"
                    risks.append(
                        {
                            "kind": "access_denied",
                            "page_index": index,
                            "url": url,
                            "message": "Visible Taobao/Tmall access-denied overlay or frame detected.",
                        }
                    )
                elif any(marker in text for marker in HUMAN_ATTENTION_MARKERS):
                    page_status = "human_attention_needed"
                    risks.append(
                        {
                            "kind": "human_attention_needed",
                            "page_index": index,
                            "url": url,
                            "message": "Captcha, slider, account-security, or traffic-risk text is visible.",
                        }
                    )
                elif any(marker in text for marker in LOGIN_MARKERS):
                    page_status = "login_needed"
                elif page_has_login_ready_signal(page, text):
                    page_status = "logged_in"
                taobao_pages.append(
                    {
                        "index": index,
                        "status": page_status,
                        "title": title,
                        "url": url,
                        "text_len": len(text.strip()),
                    }
                )
            browser.close()
    except Exception as exc:
        fallback = inspect_cdp_targets_only(cdp_url, f"Could not inspect visible CDP pages: {exc}")
        if taobao_pages:
            fallback["taobao_pages"] = taobao_pages
        if risks:
            fallback["page_risk"] = risks
        return fallback

    if not taobao_pages:
        session_status = "manual_login_needed"
        message = "CDP browser is open, but no Taobao/Tmall page is available as a session anchor."
    elif any(page["status"] == "logged_in" for page in taobao_pages):
        session_status = "ready"
        message = "At least one Taobao/Tmall page appears logged in."
    elif any(page["status"] == "login_needed" for page in taobao_pages):
        session_status = "manual_login_needed"
        message = "Taobao/Tmall page is visible but asks for login."
    elif risks:
        session_status = "blocked"
        message = "Taobao/Tmall page is visible but risk-control or access-denied text is present."
    else:
        session_status = "needs_review"
        message = "Taobao/Tmall pages exist, but login state is unclear."

    return {
        "status": session_status,
        "message": message,
        "taobao_pages": taobao_pages,
        "page_risk": risks,
    }


def check_runtime() -> dict:
    modules = {}
    for module in ("playwright", "browser_use", "crawl4ai", "bs4", "lxml", "pydantic"):
        modules[module] = module_available(module)
    if sys.version_info < REQUIRED_PYTHON:
        level = "not_ready"
        message = "Python is too old for the shopping browser toolchain."
    elif not modules.get("playwright"):
        level = "not_ready"
        message = "Playwright is missing."
    else:
        level = "ready"
        message = "Python and core browser automation dependency are available."
    return {
        "status": level,
        "message": message,
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "modules": modules,
    }


def detect_system_proxy() -> dict:
    env_proxy = {
        key: value
        for key, value in os.environ.items()
        if key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }
    mac_proxy = {}
    if platform.system() == "Darwin" and shutil.which("scutil"):
        try:
            output = subprocess.run(
                ["scutil", "--proxy"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
            for flag, host_key, port_key in (
                ("HTTPEnable", "HTTPProxy", "HTTPPort"),
                ("HTTPSEnable", "HTTPSProxy", "HTTPSPort"),
                ("SOCKSEnable", "SOCKSProxy", "SOCKSPort"),
            ):
                enabled = f"{flag} : 1" in output
                if enabled:
                    host = ""
                    port = ""
                    for line in output.splitlines():
                        if host_key in line:
                            host = line.split(":", 1)[-1].strip()
                        if port_key in line:
                            port = line.split(":", 1)[-1].strip()
                    mac_proxy[flag.replace("Enable", "").lower()] = f"{host}:{port}".strip(":")
        except Exception:
            pass
    proxy_enabled = bool(env_proxy or mac_proxy)
    return {
        "status": "warn" if proxy_enabled else "ready",
        "message": (
            "System or environment proxy is enabled; Taobao/Tmall CDP browser should be launched in direct mode."
            if proxy_enabled
            else "No system/env proxy detected by this script."
        ),
        "proxy_enabled": proxy_enabled,
        "env_proxy_keys": sorted(env_proxy.keys()),
        "mac_proxy": mac_proxy,
    }


def detect_cdp_process(port: int) -> dict:
    info = {
        "status": "unknown",
        "message": "Could not inspect process arguments.",
        "port": port,
        "process_found": False,
        "profile_dir": None,
        "proxy_mode": "unknown",
        "raw_command": None,
    }
    try:
        output = subprocess.run(
            ["ps", "-axo", "pid,command"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except Exception:
        return info
    needle = f"--remote-debugging-port={port}"
    for line in output.splitlines():
        if needle not in line:
            continue
        if "Helper" in line:
            continue
        info["process_found"] = True
        info["raw_command"] = line.strip()
        if "--no-proxy-server" in line:
            info["proxy_mode"] = "direct"
        else:
            info["proxy_mode"] = "system_or_unknown"
        profile_match = re.search(r"--user-data-dir=(.*?)(?:\s--|$)", line)
        if profile_match:
            info["profile_dir"] = profile_match.group(1).strip()
        info["status"] = "ready" if info["proxy_mode"] == "direct" else "warn"
        info["message"] = (
            "CDP Chrome appears launched in direct mode."
            if info["proxy_mode"] == "direct"
            else "CDP Chrome is running, but direct proxy bypass was not detected."
        )
        return info
    info["status"] = "not_ready"
    info["message"] = "No Chrome process with the expected remote-debugging port was found."
    return info


def decide_backend(runtime: dict, cdp: dict, process_info: dict, session: dict, network: dict) -> str:
    if runtime["status"] != "ready":
        return "not_ready"
    if cdp["status"] != "ready":
        return "manual_browser_needed"
    if session["status"] == "ready":
        if process_info.get("proxy_mode") == "direct":
            return "taobao_cdp_direct"
        if network.get("proxy_enabled"):
            return "taobao_cdp_system_proxy_risk"
        return "taobao_cdp_live"
    if session["status"] == "manual_login_needed":
        return "manual_login_needed"
    if session["status"] == "blocked":
        return "manual_user_assist"
    return "needs_review"


def choose_next_step(backend: str, session: dict, network: dict, process_info: dict) -> str:
    if backend == "not_ready":
        return "先运行 setup_env.sh 或 verify_env.py，修好本地 Python/Playwright 环境。"
    if backend == "manual_browser_needed":
        return "启动购物专用 CDP Chrome：python3 scripts/launch_chrome_cdp.py --profile-dir work/shopping-sessions/taobao-cdp。"
    if backend == "manual_login_needed":
        return "请用户在购物专用 CDP Chrome 里手工登录淘宝/天猫，并保留一个已登录标签页。"
    if backend == "taobao_cdp_system_proxy_risk":
        return "建议关闭当前 CDP Chrome，重新用 direct 模式启动，避免系统代理/VPN触发淘宝风控。"
    if backend == "manual_user_assist":
        if session.get("page_risk"):
            return "先关闭访问拒绝弹层并刷新同一页；若仍反复出现，请用户手工检查或截图该页面。"
        return "页面状态被阻塞，需要用户完成验证码、滑块或账号安全确认。"
    if backend == "needs_review":
        if session.get("status") == "needs_review":
            return "CDP 浏览器存在但登录/风控状态不明确；先打开或刷新一个淘宝/天猫标签确认已登录，再继续采集证据。"
        return "当前购物会话状态不明确；先复查 CDP 浏览器、淘宝登录态和页面风险。"
    if backend == "taobao_cdp_direct":
        return "可以开始淘宝搜索；保持人类速度，并在报告中记录本次 doctor 状态。"
    if process_info.get("proxy_mode") != "direct" and network.get("proxy_enabled"):
        return "可以谨慎继续，但如遇访问拒绝，应优先重启为 direct 模式。"
    return "可以继续，但若关键证据缺失，先复查登录态和页面风险。"


def build_report(args) -> dict:
    runtime = check_runtime()
    network = detect_system_proxy()
    cdp = status(
        "ready" if cdp_ready(args.cdp_url) else "not_ready",
        f"CDP endpoint reachable at {args.cdp_url}." if cdp_ready(args.cdp_url) else f"CDP endpoint not reachable at {args.cdp_url}.",
        cdp_url=args.cdp_url,
        pages=len(get_cdp_pages(args.cdp_url)) if cdp_ready(args.cdp_url) else 0,
    )
    process_info = detect_cdp_process(args.port)
    session = inspect_cdp_pages(args.cdp_url) if cdp["status"] == "ready" else {
        "status": "not_ready",
        "message": "CDP browser is not ready; Taobao session not checked.",
        "taobao_pages": [],
        "page_risk": [],
    }
    backend = decide_backend(runtime, cdp, process_info, session, network)
    overall_status = "ready" if backend in {"taobao_cdp_direct", "taobao_cdp_live"} else session.get("status", cdp["status"])
    if backend == "needs_review":
        overall_status = "needs_review"
    report = {
        "schema_version": 1,
        "overall_status": overall_status,
        "active_backend": backend,
        "runtime": runtime,
        "network": network,
        "cdp_browser": cdp,
        "cdp_process": process_info,
        "taobao_session": session,
        "next_step": choose_next_step(backend, session, network, process_info),
    }
    return report


def format_human(report: dict) -> str:
    labels = {
        "ready": "OK",
        "warn": "WARN",
        "not_ready": "MISS",
        "manual_login_needed": "LOGIN",
        "blocked": "BLOCKED",
        "needs_review": "CHECK",
    }

    def line(name: str, item: dict) -> str:
        status_text = labels.get(str(item.get("status")), str(item.get("status")).upper())
        return f"- {name}: {status_text} - {item.get('message', '')}"

    session = report["taobao_session"]
    lines = [
        "Ghost Buyer Doctor",
        "=" * 32,
        f"Overall: {report['overall_status']}",
        f"Active backend: {report['active_backend']}",
        line("Runtime", report["runtime"]),
        line("Network", report["network"]),
        line("CDP browser", report["cdp_browser"]),
        line("CDP process", report["cdp_process"]),
        line("Taobao session", session),
    ]
    pages = session.get("taobao_pages") or []
    if pages:
        lines.append("Taobao/Tmall pages:")
        for page in pages[:8]:
            lines.append(f"  - #{page['index']} {page['status']}: {page['url']}")
    risks = session.get("page_risk") or []
    if risks:
        lines.append("Page risks:")
        for risk in risks:
            lines.append(f"  - {risk['kind']}: {risk['message']}")
    lines.append(f"Next step: {report['next_step']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON only.")
    args = parser.parse_args()

    report = build_report(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_human(report))
    return 0 if report["overall_status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
