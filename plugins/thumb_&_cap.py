from pyrogram import Client, filters
from PIL import Image
import asyncio
import os
from helper.database import codeflixbots


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
    thumb = await codeflixbots.get_thumbnail(message.from_user.id)
    if thumb and os.path.exists(thumb):
        await client.send_photo(chat_id=message.chat.id, photo=thumb)
    elif thumb:
        # File lost after restart
        await codeflixbots.set_thumbnail(message.from_user.id, file_id=None)
        await message.reply_text("**Thumbnail was lost after bot restart ♻️\nPlease send your photo again to re-set it.**")
    else:
        await message.reply_text("**You Don't Have Any Thumbnail ❌**")


@Client.on_message(filters.private & filters.command(['del_thumb', 'delthumb']))
async def removethumb(client, message):
    thumb = await codeflixbots.get_thumbnail(message.from_user.id)
    if thumb and os.path.exists(thumb):
        os.remove(thumb)
    await codeflixbots.set_thumbnail(message.from_user.id, file_id=None)
    await message.reply_text("**Thumbnail Deleted Successfully 🗑️**")


@Client.on_message(filters.private & filters.photo)
async def addthumbs(client, message):
    from plugins.channel_admin import admin_state
    if message.from_user.id in admin_state:
        return  # handled by plugins/channel_admin.py's conversation flow instead

    mkn = await message.reply_text("Please Wait ...")
    os.makedirs("downloads", exist_ok=True)

    thumb_path = await client.download_media(
        message,
        file_name=f"downloads/thumb_{message.from_user.id}.jpg"
    )

    # Wait for .temp file to finish
    temp_path = f"{thumb_path}.temp" if thumb_path else f"downloads/thumb_{message.from_user.id}.jpg.temp"
    wait_count = 0
    while os.path.exists(temp_path) and wait_count < 30:
        await asyncio.sleep(1)
        wait_count += 1

    await asyncio.sleep(1)

    # Verify file exists and is valid
    if not thumb_path or not os.path.exists(thumb_path):
        await mkn.edit("**❌ Thumbnail download failed. Please try again.**")
        return

    if os.path.getsize(thumb_path) == 0:
        await mkn.edit("**❌ Thumbnail download failed (empty file). Please try again.**")
        return

    # Crop to 1:1 square and resize to 320x320
    try:
        thumb_path = crop_to_square(thumb_path)
    except Exception as e:
        await mkn.edit(f"**❌ Failed to process thumbnail: {e}**")
        return

    # Save the local file path to DB
    await codeflixbots.set_thumbnail(message.from_user.id, file_id=thumb_path)
    await mkn.edit("**Thumbnail Saved Successfully ✅️ (Cropped to 1:1)**")
