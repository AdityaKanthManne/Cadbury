#!/usr/bin/env bash
# Desktop Butler — one-command setup for macOS.
#
#   cd "/Users/<you>/Downloads/Github Projects/Cadbury"
#   bash scripts/setup_mac.sh
#
# What it does (nothing needs sudo):
#   1. checks Xcode command line tools, Python 3.10+, Node 18+, Rust
#   2. creates .venv and installs the Python backend
#   3. runs the test suites
#   4. asks for an optional FRED key, then does ONE live fetch (arXiv, news, markets)
#   5. builds "Desktop Butler.app" and installs it in Applications
#   6. removes the broken LaunchAgents from the earlier attempt, if present
#   7. opens the app

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
say()  { printf "\n\033[1m%s\033[0m\n" "$*"; }
fail() { printf "\n\033[31m%s\033[0m\n" "$*" >&2; exit 1; }

[[ "$(uname)" == "Darwin" ]] || fail "This script is for macOS."

# ---- 1. prerequisites -------------------------------------------------------
say "1/7  Checking tools"
xcode-select -p >/dev/null 2>&1 || {
  xcode-select --install || true
  fail "Install the Xcode command line tools from the dialog that just opened, then run this script again."
}

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
[[ -n "$PY" ]] || fail "Python 3.10+ not found (macOS's built-in python3 is 3.9). Install it with:  brew install python@3.12"
echo "  Python: $PY ($("$PY" --version))"

command -v node >/dev/null 2>&1 || fail "Node.js not found. Install it with:  brew install node"
node -e 'process.exit(parseInt(process.versions.node) < 18 ? 1 : 0)' || fail "Node 18+ needed (you have $(node --version)). Run:  brew upgrade node"
echo "  Node:   $(node --version)"

if ! command -v cargo >/dev/null 2>&1; then
  [[ -x "$HOME/.cargo/bin/cargo" ]] && export PATH="$HOME/.cargo/bin:$PATH"
fi
if ! command -v cargo >/dev/null 2>&1; then
  read -r -p "  Rust is needed to build the desktop app. Install it now via rustup? [Y/n] " ans
  [[ "${ans:-Y}" =~ ^[Nn] ]] && fail "Rust is required. Install from https://rustup.rs and re-run."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
  export PATH="$HOME/.cargo/bin:$PATH"
fi
echo "  Rust:   $(rustc --version)"

# ---- 2. Python backend --------------------------------------------------------
# updating? stop the running butler first, so its old backend doesn't stay on port 8765
if pgrep -x "Desktop Butler" >/dev/null 2>&1 || pgrep -x "desktop-butler" >/dev/null 2>&1; then
  echo "  Quitting the running Desktop Butler so it can be updated..."
  osascript -e 'quit app "Desktop Butler"' >/dev/null 2>&1 || true
  sleep 3
fi
if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "  An old butler backend is still running on port 8765; stopping it."
  lsof -nP -tiTCP:8765 -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi
say "2/7  Installing the Python backend into .venv"
[[ -x .venv/bin/python ]] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r services/butler/requirements-dev.txt

# ---- 3. tests -----------------------------------------------------------------
say "3/7  Running tests"
.venv/bin/python -m pytest tests -q
( cd apps/desktop && npm install --no-audit --no-fund --silent && npx vitest run --reporter=dot && npx tsc -b )

# ---- 4. FRED key (optional) + one live fetch ------------------------------------
DATA_DIR="$HOME/Library/Application Support/DesktopButler"
mkdir -p "$DATA_DIR"
if [[ -z "${FRED_API_KEY:-}" ]] && ! grep -q "^FRED_API_KEY=" "$DATA_DIR/.env" 2>/dev/null; then
  say "4/7  Optional: FRED key for CPI, unemployment and rates"
  echo "  Free key: https://fred.stlouisfed.org/docs/api/api_key.html (create an account, request a key)."
  read -r -p "  Paste your FRED API key, or press Return to skip: " fredkey
  if [[ -n "$fredkey" ]]; then
    printf 'FRED_API_KEY=%s\n' "$fredkey" >> "$DATA_DIR/.env"
    chmod 600 "$DATA_DIR/.env"
    echo "  Saved to $DATA_DIR/.env (outside the repo, readable only by you)."
  else
    echo "  Skipped. The Markets view will show how to add it later."
  fi
fi

say "4/7  Live fetch: arXiv, Fed and lab blogs, GDELT news, Hacker News, markets (2-3 minutes)"
if lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "  A butler backend is already running; skipping the test fetch."
elif .venv/bin/python services/butler/butler_main.py --once; then
  echo "  Live fetch worked. Everything is stored in $DATA_DIR/butler.db"
  echo "  (Any source listed under 'errors' above failed on its own; the rest still work.)"
else
  echo "  The live fetch failed (see messages above). The app will still install and will retry every 30 minutes."
fi

# ---- 5. build + install the app -------------------------------------------------
say "5/7  Building Desktop Butler.app (first build takes 3-6 minutes)"
( cd apps/desktop && npx tauri build --bundles app )
APP_SRC="apps/desktop/src-tauri/target/release/bundle/macos/Desktop Butler.app"
[[ -d "$APP_SRC" ]] || fail "Build finished but the .app wasn't found at $APP_SRC"

DEST="/Applications"
[[ -w "$DEST" ]] || { DEST="$HOME/Applications"; mkdir -p "$DEST"; }
osascript -e 'quit app "Desktop Butler"' >/dev/null 2>&1 || true
sleep 1
rm -rf "$DEST/Desktop Butler.app"
cp -R "$APP_SRC" "$DEST/"
echo "  Installed: $DEST/Desktop Butler.app"

# ---- 6. clean up the earlier attempt ------------------------------------------------
say "6/7  Removing leftovers from the earlier setup attempt"
for label in com.desktopbutler.backend com.desktopbutler.app; do
  plist="$HOME/Library/LaunchAgents/$label.plist"
  if [[ -f "$plist" ]]; then
    launchctl unload "$plist" 2>/dev/null || true
    rm -f "$plist"
    echo "  removed $plist"
  fi
done
echo "  done"

# ---- 7. launch ----------------------------------------------------------------------
say "7/7  Opening Desktop Butler"
open "$DEST/Desktop Butler.app"
cat <<'MSG'

  The butler appears in the bottom-right corner of your screen, with a small
  icon in the menu bar.

  Click him      open the briefing
  Drag him       move him anywhere (he remembers where)
  Right-click    fetch now, quiet mode, keep on top, start at login, quit

  To keep him running after restarts, right-click him and turn on
  "Start at login". Briefings run at 8:00 AM and 8:00 PM Eastern.

MSG
