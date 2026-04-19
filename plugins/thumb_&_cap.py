from pyrogram import Client, filters
from PIL import Image
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
    caption = await codeflixbots.get_caption(message.from_user.id)  # Fixed typo: was madflixbotz
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
    if thumb:
        await client.send_photo(chat_id=message.chat.id, photo=thumb)
    else:
        await message.reply_text("**You Don't Have Any Thumbnail ❌**")


@Client.on_message(filters.private & filters.command(['del_thumb', 'delthumb']))
async def removethumb(client, message):
    thumb = await codeflixbots.get_thumbnail(message.from_user.id)
    if thumb and os.path.exists(thumb):
        os.remove(thumb)  # Delete the local file from disk too
    await codeflixbots.set_thumbnail(message.from_user.id, file_id=None)
    await message.reply_text("**Thumbnail Deleted Successfully 🗑️**")


@Client.on_message(filters.private & filters.photo)
async def addthumbs(client, message):
    mkn = await message.reply_text("Please Wait ...")
    # Download the photo to disk
    thumb_path = await client.download_media(
        message,
        file_name=f"thumb_{message.from_user.id}.jpg"
    )
    # Crop to 1:1 square and resize to 320x320
    thumb_path = crop_to_square(thumb_path)
    # Save the local file path to DB
    await codeflixbots.set_thumbnail(message.from_user.id, file_id=thumb_path)
    await mkn.edit("**Thumbnail Saved Successfully ✅️ (Cropped to 1:1)**")
