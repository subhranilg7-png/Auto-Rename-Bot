from pyrogram import Client, filters
import os
from helper.database import codeflixbots
from helper.thumbs import (
    build_thumb_from_file_id, get_user_thumb_path,
    clear_user_thumb_cache, is_legacy_path,
)


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
    user_id = message.from_user.id
    thumb = await codeflixbots.get_thumbnail(user_id)
    if not thumb:
        return await message.reply_text("**You Don't Have Any Thumbnail ❌**")

    path = await get_user_thumb_path(client, user_id)
    if path:
        return await client.send_photo(chat_id=message.chat.id, photo=path)

    if is_legacy_path(thumb):
        # Old-style thumbnail: only a local file path was saved and the file is gone
        await codeflixbots.set_thumbnail(user_id, file_id=None)
        await message.reply_text("**Thumbnail was lost after bot restart ♻️\nPlease send your photo again to re-set it.**")
    else:
        await message.reply_text("**Could not load your thumbnail right now. Please try again, or send your photo again to re-set it.**")


@Client.on_message(filters.private & filters.command(['del_thumb', 'delthumb']))
async def removethumb(client, message):
    user_id = message.from_user.id
    thumb = await codeflixbots.get_thumbnail(user_id)
    if is_legacy_path(thumb) and os.path.exists(thumb):
        os.remove(thumb)
    clear_user_thumb_cache(user_id)
    await codeflixbots.set_thumbnail(user_id, file_id=None)
    await message.reply_text("**Thumbnail Deleted Successfully 🗑️**")


async def _save_thumbnail(client, message, file_id):
    """Save the image's Telegram file_id in MongoDB and build the 1:1 thumbnail from it."""
    user_id = message.from_user.id
    mkn = await message.reply_text("Please Wait ...")

    # Build first: if the image can't be processed, the previous thumbnail is left untouched
    path = await build_thumb_from_file_id(client, user_id, file_id)
    if not path:
        return await mkn.edit("**❌ Failed to process thumbnail. Please try again.**")

    await codeflixbots.set_thumbnail(user_id, file_id=file_id)
    clear_user_thumb_cache(user_id, keep=path)   # drop caches of any older thumbnail
    await mkn.edit("**Thumbnail Saved Successfully ✅️ (Cropped 1:1 from the centre)**")


@Client.on_message(filters.private & filters.photo)
async def addthumbs(client, message):
    await _save_thumbnail(client, message, message.photo.file_id)


@Client.on_message(filters.private & filters.command('setthumb'))
async def setthumb_from_reply(client, message):
    """Reply to a photo, or to an image sent as a file (keeps the original quality)."""
    target = message.reply_to_message
    file_id = None
    if target:
        if target.photo:
            file_id = target.photo.file_id
        elif target.document and (target.document.mime_type or "").startswith("image/"):
            file_id = target.document.file_id
    if not file_id:
        return await message.reply_text(
            "**Reply to a photo or an image file with /setthumb to use it as your thumbnail.**"
        )
    await _save_thumbnail(client, message, file_id)
