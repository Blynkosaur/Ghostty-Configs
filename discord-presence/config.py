# Configuration for discord-presence
#
# Copy this file to config.py and fill in the values below.
# (config.py is your real config; config.example.py is the committed template.)

# --- Discord Application (Client) IDs ---
#
# Each integration needs its own Discord application so the activity shows the
# correct name and art.
#
# To get a client ID:
#   1. Go to https://discord.com/developers/applications
#   2. Click "New Application", give it a name (e.g. "Ghostty" or "tmux").
#      The application NAME is what appears as the activity title in Discord.
#   3. Open the application and copy the "Application ID" from the
#      "General Information" page.
#   4. Paste that ID (as a string) into the matching constant below.
#
# These MUST be filled in by you; the empty strings below are placeholders.

GHOSTTY_CLIENT_ID = (
    "1521511782592548864"  # Discord Application ID for the Ghostty presence app
)
TMUX_CLIENT_ID = ""  # Discord Application ID for the tmux presence app

# --- Asset keys ---
#
# These are the names of the art assets uploaded in the Developer Portal under
# "Rich Presence" -> "Art Assets" for each application.
#
# Upload your images there and name them exactly 'ghostty' and 'tmux' so the
# keys below match. The key string here MUST match the asset name in the portal,
# or no image will appear.

# IMPORTANT: leave this empty until you have actually uploaded an art asset
# with this exact name to the Ghostty app. Discord fails to render the whole
# presence card if it references an image key that doesn't exist.
GHOSTTY_LARGE_IMAGE = ""  # e.g. "ghostty" once uploaded under Rich Presence art
TMUX_LARGE_IMAGE = "tmux"  # Art asset key uploaded for the tmux app

# Optional small overlay icon shown on the Ghostty presence when running inside
# tmux. Upload a 'tmux' art asset to the *Ghostty* application and set this to
# its key (e.g. "tmux"). Leave empty to show no overlay icon (the tmux session
# name and window count still appear as text).
GHOSTTY_TMUX_SMALL_IMAGE = ""

# Optional small overlay icon shown when Neovim is running (the presence then
# reports the file being edited). Upload a 'neovim' art asset to the *Ghostty*
# application and set this to its key (e.g. "neovim"). Leave empty for text
# only.
GHOSTTY_NEOVIM_SMALL_IMAGE = ""

# --- Program display names ---
#
# The presence shows whatever program is running in your focused tmux pane
# (e.g. "Running htop"). tmux reports the raw process name, which is sometimes
# ugly or unhelpful — notably the Claude Code CLI reports its version string.
# Map those raw names to friendly labels here. Keys are matched exactly against
# the raw command name.
GHOSTTY_PROGRAM_ALIASES = {
    "2.1.196": "Claude Code",  # claude reports its version as the process name
    "node": "Node",
    "python3": "Python",
    "lazygit": "LazyGit",
}

# --- tmux polling ---
#
# How often (in seconds) to poll tmux for the current session/window state and
# refresh the Discord presence.

POLL_INTERVAL = 15
