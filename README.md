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

## Note on `p10k.zsh`

This repo also includes my [Powerlevel10k](https://github.com/romkavt/powerlevel10k) prompt config (`p10k.zsh`). It doesn't really belong with the Ghostty config, but I didn't want to make a separate repo just for it, so it lives here for now.

It won't load from this directory — zsh expects it at the home level. Move it there to use it:

```bash
cp p10k.zsh ~/.p10k.zsh
```

