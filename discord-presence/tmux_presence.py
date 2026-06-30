#!/usr/bin/env python3
"""Discord Rich Presence for tmux.

Shows the currently attached tmux session as a Discord activity:

    In tmux
    Session: <name>

The session name is read from the running tmux server via the ``tmux`` CLI.
When the script itself runs inside a tmux pane (``$TMUX`` is set) it asks the
client directly with ``display-message -p "#S"``. Otherwise (the realistic
daemon case) it queries the most-recently-active *attached* client, which is
the authoritative source for "what session is the user actually looking at".

To respect Discord's ~15s SET_ACTIVITY rate limit, the presence is only
re-sent when the session name or window count changes; in between, the IPC
socket is kept alive so the presence stays visible.

Behaviour:
  * No tmux server / no attached session -> presence is cleared (the socket is
    kept open if already connected, so it recovers without reconnecting).
  * Discord not running -> connection is retried lazily on the next poll.
  * Ctrl-C / SIGTERM -> clears the presence and exits cleanly.

Usage:
    python3 tmux_presence.py [--interval N] [--socket PATH] [--client-id ID]
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from typing import List, Optional, Tuple

import config
from discord_rpc import DiscordRPC, build_activity

# Discord enforces roughly one SET_ACTIVITY per 15 seconds; never poll/push
# faster than this regardless of what the user requests.
MIN_INTERVAL: int = 15

# Sentinel distinct from None (which means "no attached session").
_UNSET = object()


class TmuxQuery:
    """Wraps ``tmux`` CLI calls, optionally against an explicit socket."""

    def __init__(self, tmux_path: str, socket_path: Optional[str] = None) -> None:
        self.tmux_path = tmux_path
        self.socket_path = socket_path

    def _base(self) -> List[str]:
        cmd = [self.tmux_path]
        if self.socket_path:
            cmd += ["-S", self.socket_path]
        return cmd

    def _run(self, args: List[str]) -> Optional[str]:
        """Run a tmux subcommand; return stripped stdout or None on failure.

        Returns None when no server is running, the command errors, or the
        binary cannot be executed. Empty (but successful) output yields "".
        """
        try:
            proc = subprocess.run(
                self._base() + args,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()

    def current_session(self) -> Optional[Tuple[str, int]]:
        """Return ``(session_name, window_count)`` for the active session.

        The "active" session is, in order of preference:
          1. The script's own session, when running inside tmux ($TMUX set).
          2. The most-recently-active *attached* client's session.

        Returns None if no tmux server is running or nothing is attached.
        """
        name: Optional[str] = None

        # Case 1: we are ourselves inside a tmux pane -> ask directly.
        if os.environ.get("TMUX"):
            out = self._run(["display-message", "-p", "#S"])
            if out:
                name = out

        # Case 2 (daemon): pick the most-recently-active attached client.
        if name is None:
            out = self._run(
                ["list-clients", "-F", "#{client_activity} #{client_session}"]
            )
            if out is None:
                # No server running (or tmux errored) -> nothing to show.
                return None
            name = _most_recent(out)

        if name is None:
            # Server is up but no client is attached.
            return None

        windows = self._session_windows(name)
        return name, windows

    def active_command(self, session: str) -> Optional[str]:
        """Return the foreground command of the focused pane in ``session``.

        This is the command running in the active pane of the active window —
        i.e. whatever the user is currently looking at (an editor, a REPL,
        a tool, or just their shell). Returns None if it can't be read.
        """
        out = self._run(
            [
                "list-panes",
                "-t",
                session,
                "-F",
                "#{window_active} #{pane_active} #{pane_current_command}",
            ]
        )
        if not out:
            return None
        for line in out.splitlines():
            parts = line.split(" ", 2)
            if len(parts) == 3 and parts[0] == "1" and parts[1] == "1":
                return parts[2].strip() or None
        return None

    def _session_windows(self, name: str) -> int:
        """Return the window count for ``name`` (0 if it can't be read)."""
        out = self._run(
            [
                "display-message",
                "-p",
                "-t",
                name,
                "#{session_windows}",
            ]
        )
        if out and out.isdigit():
            return int(out)
        return 0


def _most_recent(list_clients_output: str) -> Optional[str]:
    """Pick the session of the most-recently-active client.

    Each line is ``"<activity_unix_ts> <session_name>"``. Session names may
    contain spaces, so only the first space is treated as the delimiter
    (matching ``cut -d' ' -f2-`` semantics). Returns None for empty input.
    """
    best_activity = -1
    best_session: Optional[str] = None
    for line in list_clients_output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        activity_str, session = parts
        try:
            activity = int(activity_str)
        except ValueError:
            continue
        if activity > best_activity:
            best_activity = activity
            best_session = session
    return best_session


def _build(session: str, windows: int, start: int) -> dict:
    """Construct the tmux activity payload."""
    win_word = "window" if windows == 1 else "windows"
    small_text = f"{windows} {win_word}" if windows else None
    return build_activity(
        details="In tmux",
        state=f"Session: {session}",
        large_image=config.TMUX_LARGE_IMAGE,
        large_text="tmux",
        small_text=small_text,
        start=start,
        type=0,
    )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show the active tmux session as Discord Rich Presence."
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=config.POLL_INTERVAL,
        help=(
            "Seconds between tmux polls "
            f"(clamped to a minimum of {MIN_INTERVAL}s; "
            f"default {config.POLL_INTERVAL})."
        ),
    )
    parser.add_argument(
        "--socket",
        default=None,
        help=(
            "Path to the tmux server socket (passed as 'tmux -S PATH'). "
            "Useful under launchd where $TMPDIR differs from the user's."
        ),
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Override config.TMUX_CLIENT_ID (the Discord application ID).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    interval = max(MIN_INTERVAL, args.interval)
    client_id = args.client_id or config.TMUX_CLIENT_ID
    if not client_id:
        print(
            "error: no Discord client id; set config.TMUX_CLIENT_ID or pass "
            "--client-id.",
            file=sys.stderr,
        )
        return 2

    tmux_path = shutil.which("tmux")
    if tmux_path is None:
        print("error: tmux not found on PATH; is it installed?", file=sys.stderr)
        return 2

    tmux = TmuxQuery(tmux_path, socket_path=args.socket)

    rpc: Optional[DiscordRPC] = None
    # last_state holds the most recently *pushed* (session, windows) tuple, or
    # None when presence is cleared, or _UNSET before the first poll.
    last_state: object = _UNSET
    start = int(time.time())

    # Translate signals into KeyboardInterrupt-equivalent clean shutdown.
    def _terminate(signum, frame):  # noqa: ANN001 - signal handler signature
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _terminate)

    print(f"tmux-presence: polling every {interval}s (Ctrl-C to stop).")

    try:
        while True:
            current = tmux.current_session()  # (name, windows) or None

            if current != last_state:
                if current is None:
                    # tmux gone or detached: clear, keep the socket open.
                    if rpc is not None:
                        try:
                            rpc.clear()
                            print("tmux-presence: no attached session; cleared.")
                        except (OSError, RuntimeError):
                            rpc = _drop(rpc)
                    last_state = None
                else:
                    session, windows = current
                    # Reset the elapsed timer when (re)attaching from nothing.
                    if last_state is None or last_state is _UNSET:
                        start = int(time.time())
                    try:
                        if rpc is None:
                            rpc = DiscordRPC(client_id)
                            rpc.connect()
                        rpc.set_activity(_build(session, windows, start))
                        print(
                            f"tmux-presence: Session: {session} "
                            f"({windows} window{'' if windows == 1 else 's'})."
                        )
                        last_state = current
                    except (OSError, RuntimeError) as exc:
                        # Discord not up / socket died: retry next poll.
                        print(f"tmux-presence: discord unavailable ({exc}).")
                        rpc = _drop(rpc)
                        # Leave last_state unchanged so we retry on next loop.

            # Keepalive between polls (answers PINGs) or plain sleep.
            if rpc is not None:
                try:
                    rpc.pump(interval)
                except (OSError, RuntimeError):
                    rpc = _drop(rpc)
                    time.sleep(interval)
            else:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        if rpc is not None:
            try:
                rpc.clear()
            except (OSError, RuntimeError):
                pass
            rpc.close()
        print("\ntmux-presence: stopped.")
    return 0


def _drop(rpc: Optional[DiscordRPC]) -> None:
    """Best-effort close a (possibly dead) RPC connection; return None."""
    if rpc is not None:
        try:
            rpc.close()
        except (OSError, RuntimeError):
            pass
    return None


if __name__ == "__main__":
    sys.exit(main())
