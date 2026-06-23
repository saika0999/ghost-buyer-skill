# Toolchain

Use Python 3.11 or newer. `browser-use` currently requires Python `>=3.11`; `crawl4ai` requires Python `>=3.10`.

On macOS, `/usr/bin/python3` may be Python 3.9 and cannot be safely replaced. In Codex Desktop, prefer the project `.venv/bin/python` after setup; `scripts/setup_env.sh` also checks Codex's bundled Python runtime at `~/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3` before falling back to system commands.

## Recommended Layers

1. `browser-use`
   - Use for interactive browser tasks: search, click, inspect product pages, handle dynamic content, and capture screenshots.
   - Best for Taobao/JD pages that require normal browser rendering.

2. `crawl4ai`
   - Use for turning accessible pages into clean Markdown or structured text for extraction.
   - Best for public pages, brand pages, docs, and pages that do not block automated access.

3. `playwright`
   - Use as the low-level browser automation fallback.
   - Use directly when a deterministic click/screenshot/extraction script is more reliable than a general agent.

4. `shopping_research.py`
   - Use after extraction to evaluate candidates deterministically.
   - Keep business rules here instead of burying them in natural-language prompts.

## Environment Setup

Taobao/Tmall browsing requires a working local browser automation environment. In a fresh workspace, run the setup before attempting product search. Resolve `<skill-dir>` to the actual installed skill folder, usually `${CODEX_HOME:-$HOME/.codex}/skills/ghost-buyer`:

```bash
bash <skill-dir>/scripts/setup_env.sh
```

The setup script creates `.venv/`, installs Python dependencies, installs a project-local Chromium browser, and runs `verify_env.py`.

Manual equivalent with Python 3.11+:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r <skill-dir>/scripts/requirements.txt
PLAYWRIGHT_BROWSERS_PATH=.venv/playwright-browsers python -m playwright install chromium
python <skill-dir>/scripts/verify_env.py
```

If only system `python3` is available and it is older than 3.11, do not install `browser-use` into it. Use a newer interpreter.

If a test still reports "Python too old", rerun it with the project interpreter:

```bash
.venv/bin/python <skill-dir>/scripts/verify_env.py
```

Keep `PLAYWRIGHT_BROWSERS_PATH=.venv/playwright-browsers` for project-local browser installs. This avoids relying on user-global Playwright cache paths.

Do not treat a missing environment as a marketplace blocker. It is a local setup issue; fix it before recording shopping evidence.

## Unified Shopping Doctor

Before Taobao/Tmall browsing, run the doctor. It is modeled as a lightweight readiness router: it checks which layer is healthy, names the active backend, and prints the next repair action instead of leaving the agent to guess.

```bash
python3 <skill-dir>/scripts/shopping_doctor.py --json
```

Use the JSON fields consistently:

- `overall_status`: whether shopping can proceed now.
- `active_backend`: the current route, such as `taobao_cdp_direct`, `manual_login_needed`, `manual_user_assist`, or `not_ready`.
- `runtime`: Python version and required browser modules.
- `network`: system/environment proxy signals that can raise Taobao/Tmall risk.
- `cdp_browser` and `cdp_process`: whether the long-lived browser is reachable and whether it was launched in direct mode.
- `taobao_session`: visible Taobao/Tmall tabs, login state, access-denied text, captcha/security text, and other page risk.
- `next_step`: the action to take before continuing.

Do not treat a non-ready doctor result as product evidence. If the doctor reports `manual_login_needed`, ask the user to log in inside the CDP browser. If it reports `manual_user_assist`, pause for user help with captcha/account-security/access-denied behavior. If it reports proxy risk and access denial keeps recurring, relaunch the CDP browser with direct networking.

## Marketplace Safety

- Respect marketplace terms, rate limits, robots/captcha boundaries, and account-security prompts.
- Do not bypass anti-bot controls.
- Use user-controlled browser sessions for login-required flows.
- Always require explicit approval before checkout, payment, address changes, coupon redemption, or order submission.

## Logged-In Marketplace Sessions

Use a persistent browser profile when Taobao, Tmall, JD, or another marketplace requires user login before search results, product pages, reviews, or store information are visible. For Taobao/Tmall, assume manual login will often be required.

Default Taobao/Tmall CDP profile:

```text
work/shopping-sessions/taobao-cdp
```

This profile can contain cookies and account state. Keep it local, private, and out of reports, handoffs, and commits.

This CDP profile is separate from the user's everyday Chrome/Edge profile. A long-term login in the user's normal browser does not automatically transfer here. If the CDP Taobao page still says `亲，请登录`, ask the user to log in again inside this launched CDP browser and choose long-term login there.

Open one long-lived Chrome/Edge browser and let the user log in manually:

```bash
python3 <skill-dir>/scripts/launch_chrome_cdp.py \
  --profile-dir work/shopping-sessions/taobao-cdp \
  --url "https://login.taobao.com/member/login.jhtml"
```

By default, `launch_chrome_cdp.py` starts the Taobao/Tmall CDP browser in direct networking mode with Chrome `--no-proxy-server`. This is intentional: Taobao/Tmall can show `亲，访问被拒绝` with Baxia risk-control URLs such as `bixi.alicdn.com` and `cloud_ip_bl` when the browser traffic goes through a VPN/proxy/datacenter-like exit. Use `--proxy-mode system` only when the user explicitly wants the shopping browser to inherit the OS proxy.

Keep one logged-in Taobao/Tmall page open in this CDP browser as the session anchor. Do not close every tab in the CDP browser after login; on Taobao/Tmall, some login signals are session-bound and a cold new tab can ask the user to log in again even when cookies exist on disk.

After login, reuse the same live browser through CDP for search and product capture:

```bash
python3 <skill-dir>/scripts/browser_capture.py \
  "https://s.taobao.com/search?q=微波炉%20白色%20800W%20小型" \
  --cdp-url http://127.0.0.1:9222 \
  --out-dir work/shopping-captures \
  --name taobao-search \
  --no-screenshot
```

`browser_capture.py` preserves the last CDP tab by default so the session does not end up with zero tabs. Use `--keep-page-open` when intentionally creating or refreshing a session-anchor page.

The script defaults to `--throttle-ms 5500` for Taobao/Tmall URLs, a quick but still human-like browsing pace. It also defaults to `--retry-on-blocked 2`: when a dismissible `亲，访问被拒绝` popup remains or the detail page looks incomplete, close the popup, reload the same page, and retry briefly. If Taobao repeatedly asks for login, captcha, or account-security confirmation, stop browsing and ask the user to intervene; resume later with a slower pace such as `--throttle-ms 10000`, `--throttle-ms 15000`, or `--throttle-ms 30000`.

Do not repeatedly start and stop Chrome with `--profile-dir` for Taobao/Tmall product pages. Repeated persistent-context launches can close the user's browser window after each capture, leave profile singleton locks, and trigger Taobao's repeated login confirmation. Prefer the long-lived CDP browser above.

Session states to record:

- `not_ready`: dependencies or browser install are missing.
- `manual_login_needed`: visible browser is waiting for user login, captcha, or account-security check.
- `ready`: logged-in profile can load search/product/review pages.
- `blocked`: repeated access denial, captcha/risk control, or unavailable pages prevent evidence collection.

For routine post-login captures, respect the user's observed browser-window preference. With `--window-state auto`, the script keeps later CDP captures minimized if the user minimized the browser, and keeps them visible if the user left the browser visible:

```bash
python3 <skill-dir>/scripts/browser_capture.py \
  "https://s.taobao.com/search?q=微波炉%20800W" \
  --cdp-url http://127.0.0.1:9222 \
  --out-dir work/shopping-captures \
  --name taobao-search \
  --no-screenshot
```

The script will also try to close only a visible Taobao/Tmall `亲，访问被拒绝` overlay before extracting page text or screenshots. Some real Baxia denial overlays put the denial text inside an iframe while the close button is in the parent page; the script scans visible frames and prefers the parent `.baxia-dialog-close` button for this case. If the same detail page still cannot display, reload the same page and retry briefly. If a separate access-denied tab appears, close only that tab and continue from the original logged-in tab. Treat it as a blocker only when denial repeatedly returns after retry, cannot be closed, or becomes a captcha/account-security page.

Rules:

- The user enters credentials only in the browser window.
- Verify Taobao/Tmall is logged in before evidence collection. If the page still says `亲，请登录` or hides key product data behind login, ask the user to confirm/login again instead of inferring missing details.
- Do not request, print, save, or transform account passwords.
- Keep `work/shopping-sessions/` local and private; it may contain cookies and local storage.
- If a captcha or account-security check appears, let the user complete it manually; do not automate or bypass it.
- Capturing product pages, search results, store pages, review pages, screenshots, and visible text is allowed for research. Checkout and payment require separate explicit approval.
