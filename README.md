# Ghost Buyer Skill

Ghost Buyer is an iterative Codex skill for Taobao/Tmall shopping research: it browses for you, investigates like a careful shopping scout, and turns messy marketplace evidence into concise Markdown + HTML buying reports.

This skill is designed for Chinese marketplace research where details such as exact SKU, material, seller trust, after-sales terms, negative reviews, follow-up reviews, and `问大家` can materially change the recommendation.

## What It Does

- Aligns with the user's requirements before browsing.
- Uses Taobao/Tmall through a browser session controlled by the user.
- Requires manual login inside the browser when needed.
- Checks local readiness with a `shopping_doctor.py` status dashboard.
- Encourages human-speed browsing and respects marketplace risk-control boundaries.
- Captures SKU-level candidate evidence.
- Treats missing hard-constraint evidence as `needs_review`, not as a pass.
- Requires negative review, follow-up review, and Q&A inspection for serious Taobao/Tmall candidates.
- Produces both Markdown and HTML reports for each research pass.

## Safety And Privacy

This repository does not include shopping reports, screenshots, cookies, browser profiles, or account data.

The skill instructs agents to:

- Never ask for passwords or verification codes in chat.
- Let the user log in manually inside the browser.
- Never automate captcha, slider, account-security, checkout, payment, address changes, or coupon redemption.
- Keep browser profiles under `work/shopping-sessions/` local and private.
- Stop and ask the user when Taobao/Tmall shows captcha, account-security checks, repeated access denial, or incomplete login-gated pages.

## Repository Layout

```text
skills/
  ghost-buyer/
    SKILL.md
    agents/
    references/
    scripts/
```

The skill folder follows the Codex skill shape: a required `SKILL.md` plus optional `agents/`, `references/`, and `scripts/` resources.

## Install

Copy the skill folder into your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
cp -R skills/ghost-buyer ~/.codex/skills/
```

Then restart or refresh Codex so the skill list is reloaded.

## Local Setup

From the workspace where you want to run shopping research:

```bash
bash ~/.codex/skills/ghost-buyer/scripts/setup_env.sh
```

Check the environment:

```bash
python3 ~/.codex/skills/ghost-buyer/scripts/verify_env.py
```

Before Taobao/Tmall browsing, run the unified status doctor:

```bash
python3 ~/.codex/skills/ghost-buyer/scripts/shopping_doctor.py --json
```

If the doctor says manual login is needed, launch the user-controlled browser:

```bash
python3 ~/.codex/skills/ghost-buyer/scripts/launch_chrome_cdp.py \
  --profile-dir work/shopping-sessions/taobao-cdp
```

Log in manually in the opened browser window, then keep at least one Taobao/Tmall tab open as the session anchor.

## Example Prompt

```text
Use the ghost-buyer skill to help me choose a compact microwave on Taobao/Tmall.
I want a reliable mainstream brand, white or light color, enough power for daily reheating,
low height for a small shelf, and a budget around 500 RMB.
```

## Notes

- This skill is a decision-support workflow, not an automated buying bot.
- It does not place orders.
- It does not bypass marketplace access controls.
- It is optimized for Taobao/Tmall and Chinese-language shopping evidence.
