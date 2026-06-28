# Ghostty Configs

My personal [Ghostty](https://ghostty.org) terminal configuration.

## Highlights

- **Theme:** Catppuccin Mocha with 0.9 background opacity + blur
- **Font:** size 16, ligatures disabled (`-calt`, `-liga`, `-dlig`)
- **Cursor:** block style, hidden while typing
- **Cmd → Ctrl remap:** `Cmd+<letter>` sends the matching control code, so macOS-style shortcuts work in terminal apps. `Cmd+C/V` (copy/paste) and `Cmd+T` (new tab) are kept native.

## Install

Ghostty looks for its config at `~/.config/ghostty/config`.

```bash
git clone https://github.com/Blynkosaur/Ghostty-Configs.git ~/.config/ghostty
```

If that directory already exists, copy `config` into it instead. Restart Ghostty (or reload config) to apply changes.
