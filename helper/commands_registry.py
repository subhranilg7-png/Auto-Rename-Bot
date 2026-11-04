"""One list of commands: it feeds the "/" menu, /commands and the help screens, so they can't drift apart."""
import html

USER_COMMANDS = [
    ("start", "Start the bot"),
    ("settings", "Your settings — rename format, caption, thumbnail, metadata (buttons)"),
    ("autorename", "Set the rename format"),
    ("queue", "See your queue and cancel files"),
    ("cancel_queue", "Cancel everything (also stops the file in progress)"),
    ("set_caption", "Set a custom caption"),
    ("see_caption", "View your caption"),
    ("del_caption", "Delete your caption"),
    ("view_thumb", "View your thumbnail"),
    ("del_thumb", "Delete your thumbnail"),
    ("metadata", "Metadata on/off"),
    ("setmedia", "Send files as document / video / audio"),
    ("help", "Help topics"),
    ("commands", "All commands"),
]

ADMIN_COMMANDS = [
    ("panel", "Admin panel — channels, formats, patterns, settings (buttons)"),
    ("auto_post", "Start auto-post: /auto_post <channel id or label>"),
    ("stop_auto_post", "End the auto-post session"),
    ("autopost_window", "How long to wait for more qualities of an episode"),
    ("add_channel", "Add a sub channel"),
    ("list_channels", "Open the channel list"),
    ("restore_formats", "Rebuild formats from the Save channel backups"),
    ("set_main_channel", "Set the Main channel"),
    ("set_save_channel", "Set the Save (backup) channel"),
    ("set_stickers", "Set the Main/Sub stickers"),
    ("admins", "List admins"),
]


def build_commands_text(is_admin=False):
    lines = ["<b>📋 Commands</b>", ""]
    lines += [f"/{c} — {html.escape(d)}" for c, d in USER_COMMANDS]
    if is_admin:
        lines += ["", "<b>🛠 Admin</b>"]
        lines += [f"/{c} — {html.escape(d)}" for c, d in ADMIN_COMMANDS]
    return "\n".join(lines)
