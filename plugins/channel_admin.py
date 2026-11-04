import uuid
import logging
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from pyrogram.errors import RPCError
from helper.database import codeflixbots
from config import Config

logger = logging.getLogger(__name__)

# ── Admin filter ─────────────────────────────────────────────────────────────

async def _is_admin_func(_, __, message):
    if not message.from_user:
        return False
    return await codeflixbots.is_admin(message.from_user.id)

admin_filter = filters.create(_is_admin_func)

async def _is_owner_func(_, __, message):
    if not message.from_user:
        return False
    return message.from_user.id in Config.ADMIN

owner_filter = filters.create(_is_owner_func)

# ── Conversation state (per admin user_id) ───────────────────────────────────
# state = {'action': 'panel' | 'set_main_channel' | 'set_save_channel' | 'set_stickers', 'step': ..., 'data': {...}}
# action 'panel' is handled by plugins/panel.py (channels, formats, patterns ...).
admin_state = {}

# ── /set_stickers ────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('set_stickers') & admin_filter)
async def set_stickers_cmd(client, message):
    admin_state[message.from_user.id] = {
        'action': 'set_stickers', 'step': 'awaiting_main_sticker', 'data': {}
    }
    await message.reply_text(
        "**Send the sticker to use after every Main channel post** (sticker 1)."
    )


# ── /add_admin, /remove_admin ─────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('add_admin') & owner_filter)
async def add_admin_cmd(client, message):
    args = message.text.split(maxsplit=1)
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif len(args) > 1 and args[1].strip().lstrip('-').isdigit():
        target_id = int(args[1].strip())

    if not target_id:
        return await message.reply_text(
            "**Usage:** Reply to a user's message with `/add_admin`, "
            "or send `/add_admin <user_id>`."
        )

    await codeflixbots.add_admin(target_id, message.from_user.id)
    await message.reply_text(f"**✅ Added `{target_id}` as an admin.**")


@Client.on_message(filters.private & filters.command('remove_admin') & owner_filter)
async def remove_admin_cmd(client, message):
    args = message.text.split(maxsplit=1)
    target_id = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif len(args) > 1 and args[1].strip().lstrip('-').isdigit():
        target_id = int(args[1].strip())

    if not target_id:
        return await message.reply_text(
            "**Usage:** Reply to a user's message with `/remove_admin`, "
            "or send `/remove_admin <user_id>`."
        )

    removed = await codeflixbots.remove_admin(target_id)
    if removed:
        await message.reply_text(f"**✅ Removed `{target_id}` from admins.**")
    else:
        await message.reply_text(f"**`{target_id}` wasn't a dynamically-added admin.**")


@Client.on_message(filters.private & filters.command('admins') & admin_filter)
async def list_admins_cmd(client, message):
    dynamic_admins = await codeflixbots.get_admins()
    text = "**👮 Admins**\n\n**Owners (fixed):**\n"
    text += "\n".join(f"`{a}`" for a in Config.ADMIN) or "_none_"
    text += "\n\n**Added admins:**\n"
    text += "\n".join(f"`{a}`" for a in dynamic_admins) or "_none_"
    await message.reply_text(text)


# ── /set_main_channel ──────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('set_main_channel') & admin_filter)
async def set_main_channel_cmd(client, message):
    admin_state[message.from_user.id] = {'action': 'set_main_channel', 'step': 'awaiting_channel', 'data': {}}
    await message.reply_text(
        "**Forward a message from the Main channel**, or send its `@username` / `-100...` chat ID.\n"
        "Make sure the bot is already an admin there."
    )


# ── /set_save_channel ───────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('set_save_channel') & admin_filter)
async def set_save_channel_cmd(client, message):
    admin_state[message.from_user.id] = {'action': 'set_save_channel', 'step': 'awaiting_channel', 'data': {}}
    await message.reply_text(
        "**Forward a message from the Save channel**, or send its `@username` / `-100...` chat ID.\n\n"
        "This channel is only used as a backup log of thumbnails/formats — MongoDB stays "
        "the real source of truth, this is just so you can manually recover things by "
        "scrolling the channel if the database is ever lost.\n"
        "Make sure the bot is already an admin there."
    )


# ── A command always ends any half-finished prompt ─────────────────────────────

@Client.on_message(filters.private & filters.regex(r"^/"), group=-2)
async def commands_end_prompts(client, message):
    if message.from_user:
        admin_state.pop(message.from_user.id, None)


async def _back_to_settings(client, state):
    """If the prompt was opened from the panel's Settings screen, return to it."""
    panel_msg = state.get('msg')
    if panel_msg:
        try:
            from plugins.panel import view_settings
            await view_settings(client, panel_msg, note="✅ Saved.")
        except Exception as e:
            logger.error(f"Could not return to settings: {e}")


# ── Conversation step handler (text/photo/sticker while a state is active) ──────

@Client.on_message(
    filters.private & (filters.text | filters.photo | filters.sticker) & admin_filter & ~filters.regex(r"^/"),
    group=1
)
async def channel_conversation_handler(client, message):
    user_id = message.from_user.id
    if user_id not in admin_state:
        return  # not in a conversation — let other handlers process this message

    state = admin_state[user_id]
    if state['action'] == 'panel':
        from plugins.panel import handle_input
        return await handle_input(client, message, state)

    step = state['step']
    data = state['data']

    # ── Step: awaiting_channel (set_main_channel / set_save_channel) ───────────
    if step == 'awaiting_channel':
        chat_id = None
        if message.forward_from_chat:
            chat_id = message.forward_from_chat.id
        elif message.text:
            identifier = message.text.strip()
            try:
                chat = await client.get_chat(identifier)
                chat_id = chat.id
            except RPCError as e:
                return await message.reply_text(f"**❌ Couldn't resolve that channel:** `{e}`")
        else:
            return await message.reply_text("**Forward a message from the channel, or send its ID/@username.**")

        try:
            chat = await client.get_chat(chat_id)
            member = await client.get_chat_member(chat_id, "me")
            if not member.privileges:
                return await message.reply_text(
                    "**❌ The bot is a member but not an admin there.** "
                    "Please make the bot an admin and try again."
                )
        except RPCError as e:
            return await message.reply_text(
                f"**❌ Couldn't verify the bot's access to that channel:** `{e}`\n"
                "Make sure the bot has already been added there as an admin."
            )

        if state['action'] == 'set_main_channel':
            await codeflixbots.set_main_channel(chat_id)
            del admin_state[user_id]
            if state.get('msg'):
                return await _back_to_settings(client, state)
            return await message.reply_text(f"**✅ Main channel set to:** {chat.title}")

        if state['action'] == 'set_save_channel':
            await codeflixbots.set_save_channel(chat_id)
            del admin_state[user_id]
            if state.get('msg'):
                return await _back_to_settings(client, state)
            return await message.reply_text(f"**✅ Save channel set to:** {chat.title}")
        return

    # ── Steps: set_stickers wizard ───────────────────────────────────────────
    if step == 'awaiting_main_sticker':
        if not message.sticker:
            return await message.reply_text("**Please send a sticker.**")
        data['main_sticker'] = message.sticker.file_id
        state['step'] = 'awaiting_sub_sticker'
        return await message.reply_text(
            "**Got it. Now send the sticker to use after every Sub channel post/files** (sticker 2)."
        )

    if step == 'awaiting_sub_sticker':
        if not message.sticker:
            return await message.reply_text("**Please send a sticker.**")
        data['sub_sticker'] = message.sticker.file_id
        await codeflixbots.set_main_sticker(data['main_sticker'])
        await codeflixbots.set_sub_sticker(data['sub_sticker'])
        del admin_state[user_id]
        if state.get('msg'):
            return await _back_to_settings(client, state)
        return await message.reply_text("**✅ Both stickers saved.**")
