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
# state = {
#   'action': 'add_channel' | 'add_format',
#   'step': 'awaiting_channel' | 'awaiting_thumb' | 'awaiting_format' |
#           'awaiting_main_post' | 'awaiting_sub_post' | 'awaiting_label',
#   'data': {...}
# }
admin_state = {}

STEP_PROMPTS = {
    'awaiting_thumb': "**Step: Thumbnail**\nSend the thumbnail image to use for this format.",
    'awaiting_format': (
        "**Step: Auto-rename format**\n"
        "Send the rename format. Use `{season}`, `{episode}`, `{quality}` as placeholders.\n\n"
        "Example: `Anime Title S{season}E{episode} [{quality}]`"
    ),
    'awaiting_main_post': (
        "**Step: Main channel post**\n"
        "Send the post text/caption for the **Main channel**. Use `{season}` and `{episode}` as placeholders.\n\n"
        "This will be posted plain (not bold)."
    ),
    'awaiting_sub_post': (
        "**Step: Sub channel post**\n"
        "Send the post text/caption for the **Sub channel**. Use `{season}` and `{episode}` as placeholders.\n\n"
        "Tip: wrap them like `<b>{season}</b>` / `<b>{episode}</b>` if you want them bold — HTML formatting is supported."
    ),
    'awaiting_label': (
        "**Step: Label**\n"
        "Give this format a short label (e.g. the anime title) so you can identify it later in "
        "`/add_format` and `/delete_format` lists."
    ),
}

STEP_ORDER = ['awaiting_thumb', 'awaiting_format', 'awaiting_main_post', 'awaiting_sub_post', 'awaiting_label']


def _next_step(current):
    idx = STEP_ORDER.index(current)
    if idx + 1 < len(STEP_ORDER):
        return STEP_ORDER[idx + 1]
    return None


async def _backup_to_save_channel(client, channel_id, channel_title, format_doc):
    save_channel = await codeflixbots.get_save_channel()
    if not save_channel:
        return  # no save channel configured — skip silently, Mongo already has it

    backup_text = (
        f"**🗄 Format backup**\n\n"
        f"**Sub channel:** {channel_title}\n"
        f"**Channel ID:** `{channel_id}`\n"
        f"**Format ID:** `{format_doc['format_id']}`\n"
        f"**Label:** `{format_doc['label']}`\n\n"
        f"**Rename format:**\n`{format_doc['rename_format']}`\n\n"
        f"**Main channel post:**\n`{format_doc['main_post']}`\n\n"
        f"**Sub channel post:**\n`{format_doc['sub_post']}`"
    )
    try:
        await client.send_photo(save_channel, format_doc['thumbnail'], caption=backup_text[:1024])
        if len(backup_text) > 1024:
            await client.send_message(save_channel, backup_text)
    except Exception as e:
        logger.error(f"Could not back up format {format_doc['format_id']} to save channel: {e}")


async def _finalize_format(client, message, user_id):
    state = admin_state[user_id]
    data = state['data']

    format_doc = {
        'format_id': uuid.uuid4().hex[:8],
        'label': data['label'],
        'thumbnail': data['thumbnail'],
        'rename_format': data['rename_format'],
        'main_post': data['main_post'],
        'sub_post': data['sub_post'],
    }

    if state['action'] == 'add_channel':
        invite_link = None
        try:
            link_obj = await client.create_chat_invite_link(data['channel_id'])
            invite_link = link_obj.invite_link
        except RPCError as e:
            logger.error(f"Could not create invite link for {data['channel_id']}: {e}")

        await codeflixbots.add_subchannel(
            data['channel_id'], data['channel_title'], invite_link, user_id
        )
        await codeflixbots.add_format(data['channel_id'], format_doc)
        await _backup_to_save_channel(client, data['channel_id'], data['channel_title'], format_doc)

        await message.reply_text(
            f"**✅ Sub channel added!**\n\n"
            f"**Channel:** {data['channel_title']}\n"
            f"**Format label:** `{format_doc['label']}`\n"
            f"**Primary link:** {invite_link or 'Could not generate — check bot admin rights'}\n\n"
            "Use `/auto_post` to start posting to it."
        )
    else:  # add_format
        await codeflixbots.add_format(data['channel_id'], format_doc)
        await _backup_to_save_channel(client, data['channel_id'], data['channel_title'], format_doc)
        await message.reply_text(
            f"**✅ Format added!**\n\n"
            f"**Channel:** {data['channel_title']}\n"
            f"**Format label:** `{format_doc['label']}`"
        )

    del admin_state[user_id]


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


# ── /add_channel ────────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('add_channel') & admin_filter)
async def add_channel_cmd(client, message):
    admin_state[message.from_user.id] = {'action': 'add_channel', 'step': 'awaiting_channel', 'data': {}}
    await message.reply_text(
        "**Let's add a new Sub channel.**\n\n"
        "Forward a message from that channel, or send its `@username` / `-100...` chat ID.\n"
        "Make sure the bot is already an admin there (with invite-link permission)."
    )


# ── /add_format ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('add_format') & admin_filter)
async def add_format_cmd(client, message):
    channels = await codeflixbots.get_all_subchannels()
    if not channels:
        return await message.reply_text("**No sub channels yet.** Use `/add_channel` first.")

    buttons = [
        [InlineKeyboardButton(ch.get('title', str(ch['_id'])), callback_data=f"chsel_addfmt_{ch['_id']}")]
        for ch in channels
    ]
    await message.reply_text(
        "**Pick a sub channel to add a new format to:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@Client.on_callback_query(filters.regex(r"^chsel_addfmt_(-?\d+)$"))
async def add_format_channel_selected(client, callback_query: CallbackQuery):
    if not await codeflixbots.is_admin(callback_query.from_user.id):
        return await callback_query.answer("Admins only.", show_alert=True)

    channel_id = int(callback_query.matches[0].group(1))
    channel = await codeflixbots.get_subchannel(channel_id)
    if not channel:
        return await callback_query.answer("Channel not found.", show_alert=True)

    user_id = callback_query.from_user.id
    admin_state[user_id] = {
        'action': 'add_format',
        'step': 'awaiting_thumb',
        'data': {'channel_id': channel_id, 'channel_title': channel.get('title', str(channel_id))}
    }
    await callback_query.answer()
    await callback_query.message.edit_text(
        f"**Adding a new format to:** {channel.get('title', channel_id)}\n\n{STEP_PROMPTS['awaiting_thumb']}"
    )


# ── /delete_format ──────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('delete_format') & admin_filter)
async def delete_format_cmd(client, message):
    channels = await codeflixbots.get_all_subchannels()
    channels = [ch for ch in channels if ch.get('formats')]
    if not channels:
        return await message.reply_text("**No sub channels with formats yet.**")

    buttons = [
        [InlineKeyboardButton(ch.get('title', str(ch['_id'])), callback_data=f"chsel_delfmt_{ch['_id']}")]
        for ch in channels
    ]
    await message.reply_text(
        "**Pick a sub channel to delete a format from:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@Client.on_callback_query(filters.regex(r"^chsel_delfmt_(-?\d+)$"))
async def delete_format_channel_selected(client, callback_query: CallbackQuery):
    if not await codeflixbots.is_admin(callback_query.from_user.id):
        return await callback_query.answer("Admins only.", show_alert=True)

    channel_id = int(callback_query.matches[0].group(1))
    channel = await codeflixbots.get_subchannel(channel_id)
    if not channel or not channel.get('formats'):
        return await callback_query.answer("No formats found.", show_alert=True)

    buttons = [
        [InlineKeyboardButton(fmt['label'], callback_data=f"fmtdel_{channel_id}_{fmt['format_id']}")]
        for fmt in channel['formats']
    ]
    await callback_query.answer()
    await callback_query.message.edit_text(
        f"**Pick a format to delete from {channel.get('title', channel_id)}:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@Client.on_callback_query(filters.regex(r"^fmtdel_(-?\d+)_([a-f0-9]+)$"))
async def delete_format_confirmed(client, callback_query: CallbackQuery):
    if not await codeflixbots.is_admin(callback_query.from_user.id):
        return await callback_query.answer("Admins only.", show_alert=True)

    channel_id = int(callback_query.matches[0].group(1))
    format_id = callback_query.matches[0].group(2)
    channel = await codeflixbots.get_subchannel(channel_id)
    fmt = await codeflixbots.get_format(channel_id, format_id) if channel else None

    deleted = await codeflixbots.delete_format(channel_id, format_id)
    await callback_query.answer("Deleted ✅" if deleted else "Could not delete.")
    if deleted:
        await callback_query.message.edit_text("**✅ Format deleted.**")
        save_channel = await codeflixbots.get_save_channel()
        if save_channel and fmt:
            try:
                await client.send_message(
                    save_channel,
                    f"**🗑 Format deleted**\n\n"
                    f"**Sub channel:** {channel.get('title', channel_id)}\n"
                    f"**Format ID:** `{format_id}`\n"
                    f"**Label was:** `{fmt.get('label')}`"
                )
            except Exception as e:
                logger.error(f"Could not log deletion to save channel: {e}")
    else:
        await callback_query.message.edit_text("**❌ Could not delete that format.**")


# ── /list_channels ──────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('list_channels') & admin_filter)
async def list_channels_cmd(client, message):
    channels = await codeflixbots.get_all_subchannels()
    if not channels:
        return await message.reply_text("**No sub channels added yet.** Use `/add_channel`.")

    text = "**📡 Sub channels**\n\n"
    for ch in channels:
        text += f"**{ch.get('title', ch['_id'])}** (`{ch['_id']}`)\n"
        formats = ch.get('formats', [])
        if formats:
            for fmt in formats:
                text += f"  • `{fmt['label']}`\n"
        else:
            text += "  _no formats yet_\n"
        text += "\n"
    await message.reply_text(text)


# ── Conversation step handler (text/photo while a state is active) ─────────────

@Client.on_message(
    filters.private & (filters.text | filters.photo | filters.sticker) & admin_filter & ~filters.command([
        'add_channel', 'add_format', 'delete_format', 'list_channels', 'add_admin',
        'remove_admin', 'admins', 'set_main_channel', 'set_save_channel', 'set_stickers',
        'auto_post', 'stop_auto_post'
    ]),
    group=1
)
async def channel_conversation_handler(client, message):
    user_id = message.from_user.id
    if user_id not in admin_state:
        return  # not in a conversation — let other handlers process this message

    state = admin_state[user_id]
    step = state['step']
    data = state['data']

    # ── Step: awaiting_channel (shared by add_channel / set_main_channel) ──────
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
            return await message.reply_text(f"**✅ Main channel set to:** {chat.title}")

        if state['action'] == 'set_save_channel':
            await codeflixbots.set_save_channel(chat_id)
            del admin_state[user_id]
            return await message.reply_text(f"**✅ Save channel set to:** {chat.title}")

        # add_channel
        data['channel_id'] = chat_id
        data['channel_title'] = chat.title
        state['step'] = 'awaiting_thumb'
        return await message.reply_text(
            f"**Channel confirmed:** {chat.title}\n\n{STEP_PROMPTS['awaiting_thumb']}"
        )

    # ── Step: awaiting_thumb ─────────────────────────────────────────────────
    if step == 'awaiting_thumb':
        if not message.photo:
            return await message.reply_text("**Please send a photo to use as the thumbnail.**")
        data['thumbnail'] = message.photo.file_id
        state['step'] = _next_step(step)
        return await message.reply_text(STEP_PROMPTS[state['step']])

    # ── Step: awaiting_format ────────────────────────────────────────────────
    if step == 'awaiting_format':
        if not message.text:
            return await message.reply_text("**Please send the rename format as text.**")
        data['rename_format'] = message.text.strip()
        state['step'] = _next_step(step)
        return await message.reply_text(STEP_PROMPTS[state['step']])

    # ── Step: awaiting_main_post ─────────────────────────────────────────────
    if step == 'awaiting_main_post':
        if not message.text:
            return await message.reply_text("**Please send the Main channel post text.**")
        data['main_post'] = message.text
        state['step'] = _next_step(step)
        return await message.reply_text(STEP_PROMPTS[state['step']])

    # ── Step: awaiting_sub_post ──────────────────────────────────────────────
    if step == 'awaiting_sub_post':
        if not message.text:
            return await message.reply_text("**Please send the Sub channel post text.**")
        data['sub_post'] = message.text
        state['step'] = _next_step(step)
        return await message.reply_text(STEP_PROMPTS[state['step']])

    # ── Step: awaiting_label ─────────────────────────────────────────────────
    if step == 'awaiting_label':
        if not message.text:
            return await message.reply_text("**Please send a short label.**")
        data['label'] = message.text.strip()
        return await _finalize_format(client, message, user_id)

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
        return await message.reply_text("**✅ Both stickers saved.**")
