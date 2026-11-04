from pyrogram import Client, filters
from PIL import Image
import asyncio
import os
from helper.database import codeflixbots
from plugins.file_rename import clear_thumb_cache


def crop_to_square(image_path: str) -> str:
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top  = (h - side) // 2
    img  = img.crop((left, top, left + side, top + side))
    img  = img.resize((320, 320), Image.LANCZOS)
    img.save(image_path, "JPEG")
    return image_path


@Client.on_message(filters.private & filters.command('set_caption'))
async def add_caption(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Give The Caption\n\nExample :- `/set_caption 📕Name ➠ : {filename} \n\n🔗 Size ➠ : {filesize} \n\n⏰ Duration ➠ : {duration}`**")
    caption = message.text.split(" ", 1)[1]
    await codeflixbots.set_caption(message.from_user.id, caption=caption)
    await message.reply_text("**Your Caption Successfully Added ✅**")


@Client.on_message(filters.private & filters.command('del_caption'))
async def delete_caption(client, message):
    caption = await codeflixbots.get_caption(message.from_user.id)
    if not caption:
        return await message.reply_text("**You Don't Have Any Caption ❌**")
    await codeflixbots.set_caption(message.from_user.id, caption=None)
    await message.reply_text("**Your Caption Successfully Deleted 🗑️**")


@Client.on_message(filters.private & filters.command(['see_caption', 'view_caption']))
async def see_caption(client, message):
    caption = await codeflixbots.get_caption(message.from_user.id)
    if caption:
        await message.reply_text(f"**Your Caption :**\n\n`{caption}`")
    else:
        await message.reply_text("**You Don't Have Any Caption ❌**")


@Client.on_message(filters.private & filters.command(['view_thumb', 'viewthumb']))
async def viewthumb(client, message):
    file_id = await codeflixbots.get_thumbnail(message.from_user.id)
    if not file_id:
        return await message.reply_text("**You Don't Have Any Thumbnail ❌**")
    try:
        await client.send_photo(chat_id=message.chat.id, photo=file_id)
    except Exception:
        # Saved value is unusable (e.g. legacy local path) — reset it
        await codeflixbots.set_thumbnail(message.from_user.id, file_id=None)
        clear_thumb_cache(message.from_user.id)
        await message.reply_text("**Your saved thumbnail is no longer valid.\nPlease send your photo again to re-set it.**")


@Client.on_message(filters.private & filters.command(['del_thumb', 'delthumb']))
async def removethumb(client, message):
    await codeflixbots.set_thumbnail(message.from_user.id, file_id=None)
    clear_thumb_cache(message.from_user.id)
    await message.reply_text("**Thumbnail Deleted Successfully 🗑️**")


@Client.on_message(filters.private & filters.photo)
async def addthumbs(client, message):
    from plugins.channel_admin import admin_state
    if message.from_user.id in admin_state:
        return  # handled by plugins/channel_admin.py's conversation flow instead

    from helper.session_state import auto_post_sessions
    if message.from_user.id in auto_post_sessions:
        return await message.reply_text(
            "**📌 An auto-post session is active, so I ignored this photo** "
            "(it would have replaced your personal thumbnail).\n"
            "Send /stop_auto_post first if you want to set a thumbnail."
        )

    # Same as the auto-post bot: store only the Telegram file_id in MongoDB.
    # The image is downloaded + cropped 1:1 (centre) on first use and cached.
    await codeflixbots.set_thumbnail(message.from_user.id, file_id=message.photo.file_id)
    clear_thumb_cache(message.from_user.id)  # force re-download of the new image
    await message.reply_text("**Thumbnail Saved Successfully ✅️ (will be cropped 1:1 when used)**")
