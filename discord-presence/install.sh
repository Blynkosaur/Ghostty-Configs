#!/usr/bin/env bash
#
# Installer for discord-presence (macOS / zsh).
#
# What it does:
#   1. Verifies python3 is available.
#   2. Creates config.py from config.example.py if it doesn't exist.
#   3. Prompts for your Discord Application (client) ID if it's still blank.
#   4. Makes the scripts executable.
#   5. Adds a managed auto-start block to ~/.zshrc so the presence launches
#      once per Ghostty session (with the right $TMUX / GHOSTTY_* / $TMPDIR
#      env it needs — which a launchd agent would NOT have).
#
# Re-running is safe: every step is idempotent. Use --uninstall to remove the
# ~/.zshrc block (your config.py is left untouched).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZSHRC="${HOME}/.zshrc"
MARK_BEGIN="# >>> discord-presence (ghostty) >>>"
MARK_END="# <<< discord-presence (ghostty) <<<"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33mwarning:\033[0m %s\n' "$1"; }
err()   { printf '\033[1;31merror:\033[0m %s\n' "$1" >&2; }

remove_zshrc_block() {
    [ -f "$ZSHRC" ] || return 0
    if grep -qF "$MARK_BEGIN" "$ZSHRC"; then
        # Delete the marker block in place (BSD sed needs the '' backup arg).
        sed -i '' "/^${MARK_BEGIN}\$/,/^${MARK_END}\$/d" "$ZSHRC"
        info "Removed auto-start block from ${ZSHRC}."
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    info "Uninstalling discord-presence auto-start."
    remove_zshrc_block
    pkill -f ghostty_presence.py 2>/dev/null || true
    info "Done. config.py was left in place; delete it manually if you want."
    exit 0
fi

# --- 1. python3 -------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found on PATH. Install it (e.g. 'brew install python') and re-run."
    exit 1
fi
info "Using $(python3 --version) at $(command -v python3)."

# --- 2. config.py -----------------------------------------------------------
if [ ! -f "${REPO_DIR}/config.py" ]; then
    cp "${REPO_DIR}/config.example.py" "${REPO_DIR}/config.py"
    info "Created config.py from config.example.py."
else
    info "config.py already exists; leaving it as-is."
fi

# --- 3. client id -----------------------------------------------------------
current_id="$(python3 - "$REPO_DIR" <<'PY'
import sys, os
sys.path.insert(0, sys.argv[1])
import config
print(config.GHOSTTY_CLIENT_ID or "")
PY
)"

if [ -z "$current_id" ]; then
    cat <<'EOM'

You need a Discord Application ID for the presence to appear:
  1. Open https://discord.com/developers/applications
  2. New Application -> name it "Ghostty" (this name shows in Discord).
  3. Copy the "Application ID" from General Information.
  4. (Optional) Rich Presence -> Art Assets: upload images named
     'ghostty', and optionally 'tmux' / 'neovim' for the corner icons.

EOM
    read -r -p "Paste your Ghostty Application ID (or leave blank to skip): " entered_id || true
    if [ -n "${entered_id:-}" ]; then
        python3 - "$REPO_DIR" "$entered_id" <<'PY'
import re, sys
repo, new_id = sys.argv[1], sys.argv[2]
path = f"{repo}/config.py"
src = open(path).read()
src = re.sub(r'GHOSTTY_CLIENT_ID\s*=\s*\(?\s*"[^"]*"\s*\)?',
             f'GHOSTTY_CLIENT_ID = "{new_id}"', src, count=1)
open(path, "w").write(src)
print("config.py updated.")
PY
        info "Saved client ID to config.py."
    else
        warn "No client ID set. Edit config.py and set GHOSTTY_CLIENT_ID before running."
    fi
else
    info "GHOSTTY_CLIENT_ID is already set."
fi

# --- 4. make executable -----------------------------------------------------
chmod +x "${REPO_DIR}/ghostty_presence.py" "${REPO_DIR}/tmux_presence.py" 2>/dev/null || true

# --- 5. zshrc auto-start ----------------------------------------------------
remove_zshrc_block  # drop any previous version first, then re-add cleanly
{
    echo ""
    echo "$MARK_BEGIN"
    echo "# Starts the combined Ghostty/tmux/Neovim Discord presence once per"
    echo "# Ghostty session. Managed by ${REPO_DIR}/install.sh."
    echo "if [[ -n \"\$GHOSTTY_BIN_DIR\$GHOSTTY_RESOURCES_DIR\" ]] && ! pgrep -f ghostty_presence.py >/dev/null; then"
    echo "  (cd \"${REPO_DIR}\" && nohup python3 -u ghostty_presence.py --force >/tmp/ghostty-presence.log 2>&1 &) >/dev/null 2>&1"
    echo "fi"
    echo "$MARK_END"
} >> "$ZSHRC"
info "Added auto-start block to ${ZSHRC}."

cat <<EOM

$(info "Install complete.")
Next steps:
  • Make sure the Discord DESKTOP app is running, with
    Settings -> Activity Privacy -> "Share your detected activities" ON.
  • Open a new Ghostty window (or run: source ~/.zshrc) to start it.
  • Logs:  tail -f /tmp/ghostty-presence.log
  • Stop:  pkill -f ghostty_presence.py
  • Uninstall auto-start:  ${REPO_DIR}/install.sh --uninstall
EOM
