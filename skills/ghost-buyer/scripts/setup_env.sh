#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_RUNTIME_PYTHON="${CODEX_RUNTIME_PYTHON:-$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

if [ -n "${PYTHON_BIN:-}" ]; then
  true
elif [ -x "$CODEX_RUNTIME_PYTHON" ]; then
  PYTHON_BIN="$CODEX_RUNTIME_PYTHON"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3.12}"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON_BIN:-python3.11}"
else
  echo "Need Python 3.11+ for browser-use. Set PYTHON_BIN=/path/to/python3.11+." >&2
  exit 1
fi

"$PYTHON_BIN" -m venv .venv
. .venv/bin/activate
python -m pip install -r "$SCRIPT_DIR/requirements.txt" PyYAML
PLAYWRIGHT_BROWSERS_PATH=.venv/playwright-browsers python -m playwright install chromium
python "$SCRIPT_DIR/verify_env.py"
