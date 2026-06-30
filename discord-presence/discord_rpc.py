"""Pure-Python Discord Rich Presence (RPC) client.

A dependency-free (Python 3 standard library only) implementation of the
Discord IPC protocol used to set local "Rich Presence" / activity status.

Discord exposes a local IPC server as a Unix domain socket named
``discord-ipc-N`` where ``N`` is 0..9. This module locates that socket,
performs the opcode-0 handshake with an application (OAuth2) client id, and
sends ``SET_ACTIVITY`` frames (opcode 1) consisting of a little-endian
``(opcode, length)`` header followed by a UTF-8 JSON body.

Socket discovery follows the same environment order Discord itself uses
(``XDG_RUNTIME_DIR``, ``TMPDIR``, ``TMP``, ``TEMP``, then ``/tmp``). On macOS
``XDG_RUNTIME_DIR`` is normally unset, so the socket is typically found under
``$TMPDIR`` (a ``/var/folders/.../T/`` path). On Linux the Flatpak/Snap nested
subdirectories are also probed for portability.

Typical use::

    from discord_rpc import DiscordRPC, build_activity

    rpc = DiscordRPC("000000000000000000")
    rpc.connect()
    with rpc:
        rpc.set_activity(build_activity(details="Working", state="On a task"))
        rpc.pump(60)  # keep the socket (and thus the presence) alive

Note: Discord clears the presence as soon as the IPC socket closes, so a
presence setter must keep the connection open (e.g. via :meth:`DiscordRPC.pump`)
for as long as the status should remain visible.
"""

from __future__ import annotations

import itertools
import json
import os
import socket
import struct
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

__all__ = ["DiscordRPC", "build_activity"]

# IPC opcodes.
OP_HANDSHAKE: int = 0
OP_FRAME: int = 1
OP_CLOSE: int = 2
OP_PING: int = 3
OP_PONG: int = 4

RPC_VERSION: int = 1

# Field length limit for textual activity fields (details/state/*_text).
_MAX_FIELD_LEN: int = 128

# Linux Flatpak/Snap nested subdirectories that may hold the socket. On macOS
# these simply don't exist and are skipped during probing.
_NESTED_SUBDIRS = ("app/com.discordapp.Discord", "snap.discord")


def _candidate_dirs() -> List[str]:
    """Return candidate directories that may contain the IPC socket.

    Probes the same environment order Discord uses: ``XDG_RUNTIME_DIR``,
    ``TMPDIR``, ``TMP``, ``TEMP``, then ``/tmp`` as a last resort. Empty values
    are dropped and duplicates removed while preserving order. For each base
    directory the Linux Flatpak/Snap subdirectories are also appended.
    """
    bases: List[str] = []
    for var in ("XDG_RUNTIME_DIR", "TMPDIR", "TMP", "TEMP"):
        value = os.environ.get(var)
        if value:
            bases.append(value)
    bases.append("/tmp")

    dirs: List[str] = []
    seen = set()
    for base in bases:
        base = base.rstrip("/") or "/"
        for d in (base, *(os.path.join(base, sub) for sub in _NESTED_SUBDIRS)):
            if d not in seen:
                seen.add(d)
                dirs.append(d)
    return dirs


def _candidate_paths() -> Iterator[str]:
    """Yield full socket paths in first-connect-wins order."""
    for d, n in itertools.product(_candidate_dirs(), range(10)):
        yield os.path.join(d, f"discord-ipc-{n}")


def _truncate(value: Optional[str]) -> Optional[str]:
    """Truncate a textual field to Discord's ~128 char limit (None passes)."""
    if value is None:
        return None
    return value[:_MAX_FIELD_LEN]


def build_activity(
    details: Optional[str] = None,
    state: Optional[str] = None,
    large_image: Optional[str] = None,
    large_text: Optional[str] = None,
    small_image: Optional[str] = None,
    small_text: Optional[str] = None,
    start: Optional[int] = None,
    end: Optional[int] = None,
    buttons: Optional[List[Dict[str, str]]] = None,
    type: int = 0,
) -> Dict[str, Any]:
    """Assemble a Discord activity dict, omitting empty keys.

    ``details``, ``state`` and the ``*_text`` tooltips are truncated to 128
    characters. ``start``/``end`` are UNIX timestamps (seconds). ``buttons`` is
    a list of ``{"label": ..., "url": ...}`` dicts (max 2).
    """
    activity: Dict[str, Any] = {"type": type}

    details = _truncate(details)
    if details is not None:
        activity["details"] = details
    state = _truncate(state)
    if state is not None:
        activity["state"] = state

    timestamps: Dict[str, int] = {}
    if start is not None:
        timestamps["start"] = int(start)
    if end is not None:
        timestamps["end"] = int(end)
    if timestamps:
        activity["timestamps"] = timestamps

    assets: Dict[str, str] = {}
    if large_image is not None:
        assets["large_image"] = large_image
    if large_text is not None:
        assets["large_text"] = _truncate(large_text)  # type: ignore[assignment]
    if small_image is not None:
        assets["small_image"] = small_image
    if small_text is not None:
        assets["small_text"] = _truncate(small_text)  # type: ignore[assignment]
    if assets:
        activity["assets"] = assets

    if buttons:
        activity["buttons"] = buttons[:2]

    return activity


class DiscordRPC:
    """A minimal Discord IPC Rich Presence client.

    Usage::

        rpc = DiscordRPC(client_id)
        rpc.connect()
        with rpc:
            rpc.set_activity(build_activity(details="Hi"))
            rpc.pump(30)
    """

    def __init__(self, client_id: str) -> None:
        self.client_id: str = str(client_id)
        self.sock: Optional[socket.socket] = None

    # -- connection ---------------------------------------------------------

    def connect(self, timeout: float = 2.0) -> "DiscordRPC":
        """Locate the IPC socket, connect, and complete the handshake.

        Raises:
            RuntimeError: if no Discord IPC socket can be reached.
        """
        if self.sock is not None:
            return self

        last_err: Optional[OSError] = None
        for path in _candidate_paths():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            except (AttributeError, OSError) as exc:  # AF_UNIX missing (Windows)
                last_err = exc if isinstance(exc, OSError) else None
                break
            sock.settimeout(timeout)
            try:
                sock.connect(path)
            except OSError as exc:
                last_err = exc
                sock.close()
                continue
            self.sock = sock
            break

        if self.sock is None:
            msg = "Discord IPC socket not found; is Discord running?"
            if last_err is not None:
                raise RuntimeError(msg) from last_err
            raise RuntimeError(msg)

        try:
            self._handshake()
        except Exception:
            self.close()
            raise
        return self

    def reconnect(self, timeout: float = 2.0) -> "DiscordRPC":
        """Drop any existing socket and connect again from scratch."""
        self.close()
        return self.connect(timeout=timeout)

    # -- low-level framing --------------------------------------------------

    def _require_sock(self) -> socket.socket:
        if self.sock is None:
            raise RuntimeError("Not connected; call connect() first.")
        return self.sock

    def _send(self, opcode: int, payload: Dict[str, Any]) -> None:
        """Encode and send a single frame (header + body in one write)."""
        sock = self._require_sock()
        body = json.dumps(payload).encode("utf-8")
        frame = struct.pack("<II", opcode, len(body)) + body
        sock.sendall(frame)

    def _recv_exact(self, n: int) -> bytes:
        """Read exactly ``n`` bytes from the socket, raising on EOF."""
        sock = self._require_sock()
        chunks: List[bytes] = []
        remaining = n
        while remaining > 0:
            chunk = sock.recv(remaining)
            if not chunk:
                raise RuntimeError("Discord IPC connection closed unexpectedly.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _recv(self) -> tuple[int, Dict[str, Any]]:
        """Read one frame; return ``(opcode, payload_dict)``."""
        header = self._recv_exact(8)
        opcode, length = struct.unpack("<II", header)
        if length == 0:
            return opcode, {}
        body = self._recv_exact(length)
        return opcode, json.loads(body.decode("utf-8"))

    # -- protocol -----------------------------------------------------------

    def _handshake(self) -> None:
        """Send opcode-0 handshake and wait for the READY dispatch."""
        self._send(OP_HANDSHAKE, {"v": RPC_VERSION, "client_id": self.client_id})
        while True:
            opcode, payload = self._recv()
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
                continue
            if opcode == OP_CLOSE:
                raise RuntimeError(
                    "Discord closed the connection during handshake: "
                    f"{payload.get('message') or payload}"
                )
            if opcode != OP_FRAME:
                continue
            if payload.get("evt") == "ERROR":
                data = payload.get("data") or {}
                raise RuntimeError(
                    f"Discord handshake error: {data.get('message') or data}"
                )
            if payload.get("cmd") == "DISPATCH" and payload.get("evt") == "READY":
                return

    def set_activity(
        self,
        activity: Optional[Dict[str, Any]],
        pid: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Send a ``SET_ACTIVITY`` frame and return Discord's response data.

        Pass ``activity=None`` to clear the presence without disconnecting.

        Raises:
            RuntimeError: if Discord responds with an ERROR frame.
        """
        pid = pid if pid is not None else os.getpid()
        nonce = str(uuid.uuid4())
        self._send(
            OP_FRAME,
            {
                "cmd": "SET_ACTIVITY",
                "args": {"pid": pid, "activity": activity},
                "nonce": nonce,
            },
        )
        # Read until we get the response for our nonce (answering PINGs).
        while True:
            opcode, payload = self._recv()
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
                continue
            if opcode == OP_CLOSE:
                raise RuntimeError(
                    f"Discord closed the connection: "
                    f"{payload.get('message') or payload}"
                )
            if opcode != OP_FRAME:
                continue
            if payload.get("evt") == "ERROR":
                data = payload.get("data") or {}
                raise RuntimeError(
                    f"SET_ACTIVITY error: {data.get('message') or data}"
                )
            # The matching response echoes our nonce.
            if payload.get("nonce") == nonce:
                return payload.get("data") or {}
            # Some events arrive without a nonce; keep reading.

    def clear(self) -> Dict[str, Any]:
        """Clear the current presence (keeps the connection open)."""
        return self.set_activity(None)

    def pump(self, seconds: float) -> None:
        """Keep the connection alive for ``seconds``, answering PINGs.

        Discord clears the presence when the socket closes, so call this
        between updates (or after a single update) to keep the status visible.
        """
        sock = self._require_sock()
        prev_timeout = sock.gettimeout()
        sock.settimeout(1.0)
        deadline = time.monotonic() + seconds
        try:
            while time.monotonic() < deadline:
                try:
                    opcode, payload = self._recv()
                except socket.timeout:
                    continue
                if opcode == OP_PING:
                    self._send(OP_PONG, payload)
                elif opcode == OP_CLOSE:
                    raise RuntimeError(
                        f"Discord closed the connection: "
                        f"{payload.get('message') or payload}"
                    )
        finally:
            if self.sock is not None:
                self.sock.settimeout(prev_timeout)

    def close(self) -> None:
        """Best-effort close: send opcode-2 CLOSE then close the socket."""
        if self.sock is None:
            return
        try:
            self._send(OP_CLOSE, {})
        except OSError:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "DiscordRPC":
        # Connect if the caller hasn't already.
        if self.sock is None:
            self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
