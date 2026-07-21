import os
import time
import html
import shutil
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup,
    InlineKeyboardButton, CallbackQuery
)

from helper.database import codeflixbots
from helper.utils import progress_for_pyrogram
from helper.session_state import auto_post_sessions
from plugins.channel_admin import admin_filter
from plugins.file_rename import (
    extract_season_episode, extract_quality, wait_for_download,
    process_thumbnail, cleanup_files, safe_edit, add_metadata_smart
)

logger = logging.getLogger(__name__)

os.makedirs("downloads", exist_ok=True)
os.makedirs("downloads/thumbs", exist_ok=True)

DEBOUNCE_SECONDS = 8
QUALITY_ORDER = {'480p': 0, '720p': 1, '1080p': 2, '2k': 3, '4k': 4}

# ── Session state ──────────────────────────────────────────────────────────────
# auto_post_sessions lives in helper/session_state.py (shared with file_rename.py
# so the personal /autorename handler can skip files while a session is active)
# awaiting_channel_selection[user_id] = True while the reply keyboard is shown
awaiting_channel_selection = {}
# pending_groups[(user_id, channel_id, season, episode)] = {'files': [...], 'timer_task': Task, 'channel_id':..., 'format':...}
pending_groups = {}
# user_job_queues[user_id] = asyncio.Queue() — completed groups wait here so only
# one channel's post+files+main-post job runs at a time per admin
user_job_queues = {}
user_worker_running = {}


def _quality_sort_key(entry):
    return QUALITY_ORDER.get((entry.get('quality') or '').lower(), 99)


async def _get_cached_images(client, format_doc):
    """Returns (raw_path, cropped_path). raw_path is the original, uncropped
    image — used as the photo attached to Main/Sub channel posts. cropped_path
    is a 1:1 square version — used as the video/document thumbnail on uploads."""
    format_id = format_doc['format_id']
    raw_path = f"downloads/thumbs/{format_id}_raw.jpg"
    cropped_path = f"downloads/thumbs/{format_id}_crop.jpg"

    if not os.path.exists(raw_path):
        try:
            await client.download_media(format_doc['thumbnail'], file_name=raw_path)
        except Exception as e:
            logger.error(f"Could not download raw image for format {format_id}: {e}")
            return None, None

    if not os.path.exists(cropped_path):
        try:
            shutil.copyfile(raw_path, cropped_path)
            await process_thumbnail(cropped_path)  # crops in place to 320x320
        except Exception as e:
            logger.error(f"Could not crop thumbnail for format {format_id}: {e}")
            cropped_path = None

    return (raw_path if os.path.exists(raw_path) else None), cropped_path


def _render(template, season, episode):
    return (template
            .replace('{season}', str(season) if season else 'XX')
            .replace('{episode}', str(episode) if episode else 'XX'))


def _render_bold(text):
    """Wraps the whole text in bold, except segments delimited by R<>R...R<>R
    pairs, which stay normal weight. Escapes HTML special chars throughout
    since this is sent with parse_mode=HTML."""
    parts = text.split('R<>R')
    rendered = ''
    for i, part in enumerate(parts):
        if not part:
            continue
        escaped = html.escape(part)
        if i % 2 == 0:
            rendered += f'<b>{escaped}</b>'
        else:
            rendered += escaped
    return rendered


# ── /auto_post ───────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('auto_post') & admin_filter)
async def auto_post_cmd(client, message):
    user_id = message.from_user.id
    channels = await codeflixbots.get_all_subchannels()
    channels = [ch for ch in channels if ch.get('formats')]
    if not channels:
        return await message.reply_text(
            "**No sub channels with a format set up yet.** Use `/add_channel` first."
        )

    main_channel = await codeflixbots.get_main_channel()
    if not main_channel:
        return await message.reply_text(
            "**No Main channel set yet.** Use `/set_main_channel` first."
        )

    titles = [ch.get('title', str(ch['_id'])) for ch in channels]
    keyboard = [titles[i:i + 2] for i in range(0, len(titles), 2)]
    awaiting_channel_selection[user_id] = True

    await message.reply_text(
        "**📡 Choose a sub channel to auto-post to:**",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )


@Client.on_message(filters.private & filters.command('stop_auto_post') & admin_filter)
async def stop_auto_post_cmd(client, message):
    user_id = message.from_user.id
    awaiting_channel_selection.pop(user_id, None)
    had_session = auto_post_sessions.pop(user_id, None)

    # Flush any pending groups belonging to this user right away (queued, so
    # it still waits its turn behind any job already running)
    keys = [k for k in pending_groups if k[0] == user_id]
    for key in keys:
        group = pending_groups.pop(key)
        if group.get('timer_task'):
            group['timer_task'].cancel()
        await _enqueue_job(client, key, group)

    await message.reply_text(
        "**🛑 Auto-post session ended.**" if had_session else "**No active auto-post session.**",
        reply_markup=ReplyKeyboardRemove()
    )


# ── Channel selection (text reply from the keyboard) ────────────────────────

@Client.on_message(filters.private & filters.text & admin_filter, group=2)
async def channel_selection_handler(client, message):
    user_id = message.from_user.id
    if not awaiting_channel_selection.get(user_id):
        return

    title = message.text.strip()
    channels = await codeflixbots.get_all_subchannels()
    match = next((ch for ch in channels if ch.get('title', '') == title), None)
    if not match:
        return await message.reply_text("**Please tap one of the channel buttons below.**")

    awaiting_channel_selection.pop(user_id, None)
    formats = match.get('formats', [])

    if len(formats) == 1:
        return await _start_session(client, message, user_id, match, formats[0])

    buttons = [
        [InlineKeyboardButton(fmt['label'], callback_data=f"apfmt_{match['_id']}_{fmt['format_id']}")]
        for fmt in formats
    ]
    await message.reply_text(
        f"**{match.get('title')}** has multiple formats — pick one:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@Client.on_callback_query(filters.regex(r"^apfmt_(-?\d+)_([a-f0-9]+)$"))
async def channel_format_selected(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await codeflixbots.is_admin(user_id):
        return await callback_query.answer("Admins only.", show_alert=True)

    channel_id = int(callback_query.matches[0].group(1))
    format_id = callback_query.matches[0].group(2)
    channel = await codeflixbots.get_subchannel(channel_id)
    fmt = await codeflixbots.get_format(channel_id, format_id)
    if not channel or not fmt:
        return await callback_query.answer("Not found.", show_alert=True)

    await callback_query.answer()
    await callback_query.message.edit_text(f"**Selected format:** `{fmt['label']}`")
    await _start_session(client, callback_query.message, user_id, channel, fmt)


async def _start_session(client, message, user_id, channel, fmt):
    auto_post_sessions[user_id] = {
        'channel_id': channel['_id'],
        'channel_title': channel.get('title', str(channel['_id'])),
        'format': fmt,
    }
    await client.send_message(
        user_id,
        f"**✅ Auto-post ready.**\n\n"
        f"**Sub channel:** {channel.get('title')}\n"
        f"**Format:** `{fmt['label']}`\n\n"
        "Now send the file(s). Files for the same episode (different qualities) can be sent one after another — "
        "I'll wait a few seconds after the last one before posting.\n"
        "Send `/stop_auto_post` when you're done.",
        reply_markup=ReplyKeyboardRemove()
    )


# ── Incoming files while a session is active ────────────────────────────────

@Client.on_message(
    filters.private & (filters.document | filters.video | filters.audio) & admin_filter,
    group=2
)
async def auto_post_file_handler(client, message):
    user_id = message.from_user.id
    session = auto_post_sessions.get(user_id)
    if not session:
        return  # not in an auto-post session — let other handlers process it

    if message.document:
        file_id = message.document.file_id
        file_name = message.document.file_name or "file"
        media_type = "document"
    elif message.video:
        file_id = message.video.file_id
        file_name = message.video.file_name or "video"
        media_type = "video"
    elif message.audio:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or "audio"
        media_type = "audio"
    else:
        return

    caption_text = message.caption or ""
    combined = f"{file_name} {caption_text}"
    season, episode = extract_season_episode(combined)
    quality = extract_quality(combined)

    if not episode:
        return await message.reply_text(
            "**⚠️ Couldn't detect the episode number for this file — skipped.**\n"
            f"`{file_name[:60]}`"
        )

    key = (user_id, session['channel_id'], season, episode)
    entry = {
        'message': message, 'file_id': file_id, 'file_name': file_name,
        'media_type': media_type, 'quality': quality,
    }

    if key not in pending_groups:
        pending_groups[key] = {
            'files': [], 'timer_task': None,
            'channel_id': session['channel_id'],
            'channel_title': session['channel_title'],
            'format': session['format'],
        }
    group = pending_groups[key]
    group['files'].append(entry)

    if group['timer_task']:
        group['timer_task'].cancel()
    group['timer_task'] = asyncio.create_task(_debounce_and_flush(client, key))

    await message.reply_text(
        f"**📥 Queued** `{file_name[:50]}`\n"
        f"Season `{season or 'XX'}` Episode `{episode}` Quality `{quality or 'Unknown'}`"
    )


async def _debounce_and_flush(client, key):
    try:
        await asyncio.sleep(DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        return
    group = pending_groups.pop(key, None)
    if group:
        await _enqueue_job(client, key, group)


async def _enqueue_job(client, key, group):
    user_id = key[0]
    if user_id not in user_job_queues:
        user_job_queues[user_id] = asyncio.Queue()

    should_notify = user_job_queues[user_id].qsize() > 0 or user_worker_running.get(user_id, False)
    need_worker = not user_worker_running.get(user_id, False)
    if need_worker:
        user_worker_running[user_id] = True  # claim synchronously, before any await below

    await user_job_queues[user_id].put((key, group))

    if should_notify:
        season, episode = key[2], key[3]
        try:
            await client.send_message(
                user_id,
                f"**⏳ Queued** — S{season or 'XX'}E{episode} for {group['channel_title']} "
                f"will start once the current channel's post finishes."
            )
        except Exception:
            pass

    if need_worker:
        asyncio.create_task(_user_queue_worker(client, user_id))


async def _user_queue_worker(client, user_id):
    user_worker_running[user_id] = True
    queue = user_job_queues[user_id]
    try:
        while not queue.empty():
            key, group = await queue.get()
            await _flush_group(client, key, group)
            queue.task_done()
    finally:
        user_worker_running[user_id] = False


async def _flush_group(client, key, group):
    user_id, channel_id, season, episode = key
    fmt = group['format']
    files = sorted(group['files'], key=_quality_sort_key)

    try:
        await client.send_message(user_id, f"**⚙️ Posting S{season or 'XX'}E{episode}...**")

        raw_image, cropped_thumb = await _get_cached_images(client, fmt)

        # 1. Sub channel post (photo = original uncropped image, caption = bold-rendered text)
        sub_text = _render_bold(_render(fmt['sub_post'], season, episode))
        if raw_image:
            await client.send_photo(channel_id, photo=raw_image, caption=sub_text, parse_mode=ParseMode.HTML)
        else:
            await client.send_message(channel_id, sub_text, parse_mode=ParseMode.HTML)

        # 2. Files in quality order (renamed + metadata embedded, same as /autorename)
        for entry in files:
            await _rename_and_upload(client, entry, fmt, channel_id, season, episode, cropped_thumb, user_id)

        # 3. Sub channel sticker (sticker 2), after the files
        sub_sticker = await codeflixbots.get_sub_sticker()
        if sub_sticker:
            try:
                await client.send_sticker(channel_id, sub_sticker)
            except Exception as e:
                logger.error(f"Could not send sub sticker to {channel_id}: {e}")

        # 4. Main channel post with DOWNLOAD button (primary/invite link to the sub channel)
        channel = await codeflixbots.get_subchannel(channel_id)
        invite_link = channel.get('invite_link') if channel else None
        main_text = _render_bold(_render(fmt['main_post'], season, episode))

        reply_markup = None
        if invite_link:
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("DOWNLOAD", url=invite_link)]]
            )
        main_channel_id = await codeflixbots.get_main_channel()
        if raw_image:
            await client.send_photo(
                main_channel_id, photo=raw_image, caption=main_text,
                parse_mode=ParseMode.HTML, reply_markup=reply_markup
            )
        else:
            await client.send_message(
                main_channel_id, main_text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
            )

        # 5. Main channel sticker (sticker 1), after the post
        main_sticker = await codeflixbots.get_main_sticker()
        if main_sticker:
            try:
                await client.send_sticker(main_channel_id, main_sticker)
            except Exception as e:
                logger.error(f"Could not send main sticker to {main_channel_id}: {e}")

        await client.send_message(
            user_id,
            f"**✅ Done — S{season or 'XX'}E{episode} posted to {group['channel_title']} "
            f"({len(files)} file(s)) and the Main channel.**"
        )
    except Exception as e:
        logger.error(f"Error flushing group {key}: {e}")
        try:
            await client.send_message(user_id, f"**❌ Error posting S{season or 'XX'}E{episode}:** `{e}`")
        except Exception:
            pass


async def _rename_and_upload(client, entry, fmt, channel_id, season, episode, thumb_path, user_id):
    message = entry['message']
    file_name = entry['file_name']
    quality = entry['quality']
    media_type = entry['media_type']
    download_path = None

    try:
        rename_template = fmt['rename_format']
        replacements = {
            '{season}': str(season) if season else 'XX',
            '{episode}': str(episode) if episode else 'XX',
            '{quality}': str(quality) if quality else 'Unknown',
        }
        for placeholder, value in replacements.items():
            rename_template = rename_template.replace(placeholder, value)

        ext = os.path.splitext(file_name)[1] or '.mkv'
        new_filename = f"{rename_template}{ext}"
        unique_id = f"{user_id}_{int(time.time())}_{quality or 'na'}"
        download_path = f"downloads/{unique_id}{ext}"

        progress_msg = await client.send_message(user_id, f"**⬇️ Downloading** `{file_name[:50]}`...")

        try:
            file_path = await message.download(
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", progress_msg, time.time())
            )
        except TypeError:
            file_path = await message.download(file_name=download_path)

        file_path = await wait_for_download(file_path, download_path)

        # Metadata — same behavior as the personal /autorename flow: only runs
        # if this admin has metadata turned "On" via /metadata
        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            await safe_edit(progress_msg, "**🔧 Adding metadata...**")
            try:
                file_path, metadata_added = await add_metadata_smart(file_path, user_id)
                if not metadata_added:
                    logger.warning(f"Metadata not embedded for {new_filename}, uploading without it.")
            except Exception as e:
                logger.error(f"Metadata error for {new_filename}: {e}")

        await safe_edit(progress_msg, f"**⬆️ Uploading** `{new_filename[:50]}`...")
        upload_params = {
            'chat_id': channel_id,
            'caption': f"**{new_filename}**",
            'thumb': thumb_path,
            'progress': progress_for_pyrogram,
            'progress_args': ("Uploading...", progress_msg, time.time())
        }

        if media_type == "document":
            await client.send_document(document=file_path, file_name=new_filename, **upload_params)
        elif media_type == "video":
            await client.send_video(video=file_path, **upload_params)
        elif media_type == "audio":
            await client.send_audio(audio=file_path, file_name=new_filename, **upload_params)

        try:
            await progress_msg.delete()
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error renaming/uploading {file_name}: {e}")
        try:
            await client.send_message(user_id, f"**❌ Failed to process** `{file_name[:50]}`: `{e}`")
        except Exception:
            pass
    finally:
        if download_path and os.path.exists(download_path):
            await cleanup_files(download_path)
