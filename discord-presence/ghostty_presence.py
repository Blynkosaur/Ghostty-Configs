#!/usr/bin/env python3
"""Discord Rich Presence for the Ghostty terminal.

Shows a near-static "Using Ghostty" presence with an elapsed timer that counts
up from when the script started. The current working directory's basename is
shown as the state so the full (possibly home-relative) path is not leaked.

Run inside a Ghostty terminal::

    ./ghostty_presence.py

Detection prefers the GHOSTTY_* environment variables (which survive tmux,
unlike TERM_PROGRAM). If Ghostty is not detected the script warns and exits
unless ``--force`` is given.

Discord clears the presence as soon as the IPC socket closes, so this script
keeps the connection open in a loop and tidies up on Ctrl-C / SIGTERM.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

import glob
import shutil

import config
import discord_rpc
from tmux_presence import TmuxQuery

# How often (seconds) to wake up and service the IPC connection. Discord rate
# limits SET_ACTIVITY to roughly once every 15s, so we never push faster.
REFRESH_SECONDS = 15


def _tmux_query() -> "TmuxQuery | None":
    """Return a TmuxQuery if we're inside a tmux session, else None.

    We only fold tmux into the presence when this process is itself running in
    a tmux pane ($TMUX set); GHOSTTY_* vars survive tmux, so Ghostty is still
    detected correctly underneath. If tmux isn't on PATH we silently skip it.
    """
    if not os.environ.get("TMUX"):
        return None
    tmux_path = shutil.which("tmux")
    if tmux_path is None:
        return None
    return TmuxQuery(tmux_path)


def _nvim_status() -> "tuple[str, str] | None":
    """Return ``(filename, filetype)`` for the active Neovim, else None.

    Discord only renders one activity card, so rather than run a competing
    Neovim presence we fold Neovim into this one card. Neovim exposes an RPC
    server socket under ``$TMPDIR/nvim.<user>/<id>/nvim.<pid>.0``; we query the
    most recently started instance with ``--remote-expr`` for the open file's
    basename and its filetype. ``filename`` is "" when no real file is open
    (e.g. a dashboard/empty buffer). Returns None when no Neovim is running.
    """
    nvim = shutil.which("nvim")
    if nvim is None:
        return None

    tmpdir = os.environ.get("TMPDIR") or "/tmp"
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    patterns = [os.path.join(tmpdir, "nvim.*", "*", "nvim.*")]
    if runtime:
        patterns.append(os.path.join(runtime, "nvim.*", "*", "nvim.*"))

    socks: list[str] = []
    for pat in patterns:
        socks.extend(glob.glob(pat))
    if not socks:
        return None
    # Most recently created socket == the instance the user most likely means.
    socks.sort(key=lambda p: os.path.getmtime(p), reverse=True)

    def ask(sock: str, expr: str) -> "str | None":
        try:
            out = subprocess.run(
                [nvim, "--server", sock, "--remote-expr", expr],
                capture_output=True,
                text=True,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip()

    for sock in socks:
        fname = ask(sock, 'expand("%:t")')
        if fname is None:
            continue  # dead socket; try the next
        ftype = ask(sock, "&filetype") or ""
        return fname, ftype
    return None


# Foreground commands that are "just a shell" -> treated as plain command line.
# (tmux reports the login shell with or without a leading dash.)
_SHELLS = {"zsh", "bash", "fish", "sh", "-zsh", "-bash", "-fish", "tmux", "login"}

# Editors we report as "Editing ..."; Neovim additionally gets file detail via
# its RPC socket (see _nvim_status).
_EDITORS = {"nvim", "vim", "vi", "nano", "hx", "helix", "emacs", "emacsclient"}


def _headline(active_cmd: "str | None") -> tuple[str, str | None, str | None]:
    """Map the focused program to (details, small_text, small_image).

    - an editor       -> "Editing in <editor>".
    - any other tool  -> "Running <tool>" (e.g. claude, htop, lazygit, python).
    - a plain shell / unknown -> "In the command line".

    Neovim is intentionally NOT handled here: the dedicated presence.nvim plugin
    owns the Neovim card, and _presence_fields yields the slot to it (see below).
    """
    # The alias map prettifies ugly raw process names for the "Running" label.
    pretty = (
        config.GHOSTTY_PROGRAM_ALIASES.get(active_cmd, active_cmd)
        if active_cmd
        else active_cmd
    )

    if active_cmd in _EDITORS:
        return f"Editing in {active_cmd}", active_cmd, None

    if active_cmd and active_cmd not in _SHELLS:
        # Some other foreground program: claude, htop, lazygit, python, etc.
        return f"Running {pretty}", pretty, None

    return "In the command line", None, None


def _presence_fields(
    tmux: "TmuxQuery | None",
) -> "tuple[str, str, str | None, str | None] | None":
    """Compute (details, state, small_image, small_text), or None to YIELD.

    Returns None when a Neovim instance is running: Discord shows only one card,
    and the dedicated presence.nvim plugin owns the Neovim card, so this script
    clears its own presence and gets out of the way. Otherwise it reports the
    focused tmux pane's program with the session (or cwd) as the state.
    """
    if _nvim_status() is not None:
        return None  # yield the slot to the presence.nvim plugin

    session = None
    active_cmd = None
    if tmux is not None:
        current = tmux.current_session()  # (session, windows) or None
        if current is not None:
            session = current[0]
            active_cmd = tmux.active_command(session)

    details, small_text, small_image = _headline(active_cmd)

    if session is not None:
        state = f"TMUX Session: {session}"
    else:
        state = f"dir: {os.path.basename(os.getcwd()) or '/'}"
    return details, state, small_image, small_text


def is_ghostty() -> bool:
    """Return True if we appear to be running under Ghostty.

    The GHOSTTY_* vars are the robust signal: they persist through tmux/screen,
    which clobber TERM_PROGRAM. TERM_PROGRAM=ghostty is a confirming secondary.
    """
    return (
        os.environ.get("TERM_PROGRAM") == "ghostty"
        or bool(os.environ.get("GHOSTTY_BIN_DIR"))
        or bool(os.environ.get("GHOSTTY_RESOURCES_DIR"))
    )


def ghostty_version() -> str:
    """Best-effort Ghostty version string, e.g. "Ghostty 1.3.1".

    Tries TERM_PROGRAM_VERSION first, then ``ghostty +version`` (preferring the
    binary in $GHOSTTY_BIN_DIR, else whatever is on PATH). Falls back to the
    bare product name if neither works.
    """
    ver = os.environ.get("TERM_PROGRAM_VERSION")
    if ver:
        return f"Ghostty {ver}"

    bin_dir = os.environ.get("GHOSTTY_BIN_DIR")
    candidate = os.path.join(bin_dir, "ghostty") if bin_dir else "ghostty"
    try:
        out = subprocess.run(
            [candidate, "+version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "Ghostty"

    for line in out.stdout.splitlines():
        line = line.strip()
        # Machine-friendly form: "version: 1.3.1"
        if line.lower().startswith("version:"):
            num = line.split(":", 1)[1].strip()
            if num:
                return f"Ghostty {num}"
        # Human form: "Ghostty 1.3.1"
        if line.lower().startswith("ghostty"):
            return line
    return "Ghostty"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Set a Discord Rich Presence while using Ghostty.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="skip the Ghostty detection check and run anyway",
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="override the Discord application client id "
        "(defaults to config.GHOSTTY_CLIENT_ID)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not is_ghostty():
        if not args.force:
            print(
                "ghostty_presence: this does not look like a Ghostty terminal "
                "(no GHOSTTY_* env vars and TERM_PROGRAM != ghostty).\n"
                "Re-run with --force to set the presence anyway.",
                file=sys.stderr,
            )
            return 0
        print(
            "ghostty_presence: Ghostty not detected; continuing due to --force.",
            file=sys.stderr,
        )

    client_id = args.client_id or config.GHOSTTY_CLIENT_ID

    # Gather presence data once at startup.
    version = ghostty_version()
    start = int(time.time())  # captured once so the elapsed timer ticks up

    tmux = _tmux_query()

    # Only send a large_image if one is configured: Discord fails to render the
    # whole card when given an asset key that hasn't been uploaded to the app.
    large_image = config.GHOSTTY_LARGE_IMAGE or None

    def build(fields):
        """Turn _presence_fields output into an activity dict, or None to clear."""
        if fields is None:  # yielding to the Neovim presence plugin
            return None
        details, state, small_image, small_text = fields
        return discord_rpc.build_activity(
            details=details,
            state=state,
            large_image=large_image,
            large_text="Ghostty Terminal" if large_image else None,
            small_image=small_image,
            small_text=small_text,
            start=start,
            type=0,
        )

    rpc = discord_rpc.DiscordRPC(client_id)
    rpc.connect()

    # Clear and close cleanly on signals so detaching tidies the presence.
    def _shutdown(signum, frame):  # noqa: ANN001 - signal handler signature
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _shutdown)

    try:
        last_fields = _presence_fields(tmux)
        activity = build(last_fields)
        rpc.set_activity(activity)  # activity=None clears (yields to Neovim)
        if activity is None:
            print(f"ghostty_presence: Neovim running; yielding the card to it.")
        else:
            print(
                f"ghostty_presence: presence set ({version}, {last_fields[1]}). "
                "Press Ctrl-C to stop.",
            )
        while True:
            rpc.pump(REFRESH_SECONDS)
            # Refresh when the focused program / tmux session (or cwd) changes,
            # or when Neovim starts/stops (which toggles the yield). The elapsed
            # timer advances on its own from `start`.
            fields = _presence_fields(tmux)
            if fields != last_fields:
                rpc.set_activity(build(fields))
                last_fields = fields
    except KeyboardInterrupt:
        pass
    finally:
        try:
            rpc.clear()
        except Exception:
            pass
        rpc.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
