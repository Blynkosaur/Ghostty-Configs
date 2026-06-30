# discord-presence

A dependency-free (Python 3 standard library only) **Discord Rich Presence**
for the [Ghostty](https://ghostty.org) terminal — with tmux and Neovim folded
into a single activity card.

Discord only renders **one** rich-presence card at a time, so rather than run
separate integrations that fight over the slot, this shows everything in one
card:

It reflects **whatever program is running in your focused tmux pane**, with the
shell as the fallback:

| Focused program | Card shows |
|---|---|
| Neovim (file open) | **Editing `<file>`** · `TMUX Session: <s>` · overlay `Neovim · <filetype>` |
| Neovim (no file) | **In Neovim** · `TMUX Session: <s>` |
| Another editor (vim/nano/helix…) | **Editing in `<editor>`** |
| Any other tool (claude, htop, lazygit, python…) | **Running `<tool>`** |
| Plain shell | **In the command line** |
| Not in tmux | state falls back to `dir: <basename>` |

The Neovim file/filetype is read live from Neovim's own RPC socket
(`nvim --server <sock> --remote-expr ...`), so no Neovim plugin is required.
The focused program comes from tmux's `pane_current_command`.

### Prettifying program names

tmux reports the raw process name, which is sometimes ugly (the Claude Code CLI,
for example, reports its version string like `2.1.196`). Map raw names to
friendly labels with `GHOSTTY_PROGRAM_ALIASES` in `config.py`:

```python
GHOSTTY_PROGRAM_ALIASES = {
    "2.1.196": "Claude Code",
    "node": "Node",
    "python3": "Python",
}
```

## Requirements

- macOS (the auto-start path targets zsh + Ghostty)
- `python3` (no pip packages needed)
- The **Discord desktop app** running (the browser version does not expose the
  local IPC socket)
- Optional: `tmux`, `nvim` on `PATH` for those parts of the card

## Install

```bash
cd ~/discord-presence
./install.sh
```

The installer:
1. Verifies `python3`.
2. Creates `config.py` from `config.example.py` if missing.
3. Prompts for your Discord Application ID if it isn't set yet.
4. Marks the scripts executable.
5. Adds a managed auto-start block to `~/.zshrc` so the presence launches once
   per Ghostty session.

> **Why not launchd?** A launchd agent wouldn't inherit `$TMUX`, the `GHOSTTY_*`
> vars, or the right `$TMPDIR` — all of which the tmux/Neovim/Discord-socket
> detection depends on. Launching from the shell is what makes detection work.

### Get a Discord Application ID

**Shortcut:** you don't have to create your own app — you can just use mine,
which already has the `ghostty` art uploaded:

```python
GHOSTTY_CLIENT_ID = "1521511782592548864"
```

The activity will then read **"Ghostty"** with my app's icons. Create your own
(below) only if you want a different name or your own art assets.

1. Open <https://discord.com/developers/applications>.
2. **New Application** → name it **Ghostty** (this name shows in Discord).
3. Copy the **Application ID** from *General Information* — that's your client ID.
4. *(Optional)* **Rich Presence → Art Assets**: upload images named `ghostty`
   (large icon), and optionally `tmux` / `neovim` for the small corner overlay.

Then enable **Discord → Settings → Activity Privacy → "Share your detected
activities with others."**

## Configuration (`config.py`)

| Key | Purpose |
|---|---|
| `GHOSTTY_CLIENT_ID` | **Required.** Your Discord Application ID. |
| `GHOSTTY_LARGE_IMAGE` | Art-asset key for the large icon (default `"ghostty"`). |
| `GHOSTTY_TMUX_SMALL_IMAGE` | Optional overlay icon key when in tmux. Empty = text only. |
| `GHOSTTY_NEOVIM_SMALL_IMAGE` | Optional overlay icon key when in Neovim. Empty = text only. |
| `TMUX_CLIENT_ID`, `TMUX_LARGE_IMAGE`, `POLL_INTERVAL` | Only used by the standalone `tmux_presence.py`. |

Asset keys must exactly match the asset names you uploaded in the Developer
Portal, or no image appears.

## Usage

Auto-starts in any new Ghostty window after install. To run manually:

```bash
python3 ghostty_presence.py            # detects Ghostty via env vars
python3 ghostty_presence.py --force    # skip the Ghostty detection check
```

- **Logs:** `tail -f /tmp/ghostty-presence.log`
- **Stop:** `pkill -f ghostty_presence.py`
- **Uninstall auto-start:** `./install.sh --uninstall` (leaves `config.py` alone)

## Files

| File | Role |
|---|---|
| `ghostty_presence.py` | Main entry point; the combined Ghostty + tmux + Neovim presence. |
| `tmux_presence.py` | Standalone tmux-only presence; also provides `TmuxQuery`, reused above. |
| `discord_rpc.py` | Pure-Python Discord IPC client (socket discovery, handshake, `SET_ACTIVITY`). |
| `config.py` | Your local config (gitignored-style; created from the example). |
| `config.example.py` | Committed template. |
| `install.sh` | macOS installer / uninstaller. |

## Troubleshooting

- **"Discord IPC socket not found"** — the Discord *desktop* app isn't running.
  On macOS the socket lives under `$TMPDIR` (a `/var/folders/.../T/` path), not
  `/tmp`; `discord_rpc.py` already probes the correct locations.
- **Nothing shows on your profile** — check the *full profile popout* (click your
  avatar), not the one-line status; and confirm Activity Privacy sharing is on.
- **Neovim part missing** — make sure `nvim` is on `PATH` and you have a file
  open (an empty dashboard buffer shows "In Neovim" instead of a filename).
