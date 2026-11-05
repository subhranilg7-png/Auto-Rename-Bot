import os
import re
import time
import html
import shutil
import uuid
import asyncio
import logging
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

from helper.database import codeflixbots
from helper.utils import progress_for_pyrogram
from helper.session_state import auto_post_sessions
from helper.post_render import render_post, render_bold, fill
from helper.cancel import (
    TaskCancelled, new_task, drop_task, raise_if_cancelled, request_cancel
)
from plugins.channel_admin import admin_filter
from plugins.file_rename import stored_name_mismatch
from plugins.file_rename import (
    extract_season_episode, extract_quality, wait_for_download,
    process_thumbnail, cleanup_files, safe_edit, add_metadata_smart
)

logger = logging.getLogger(__name__)

os.makedirs("downloads", exist_ok=True)
os.makedirs("downloads/thumbs", exist_ok=True)

DEFAULT_WINDOW_SECONDS = 15   # how long to wait after the last file of an episode (change with /autopost_window)
QUALITY_ORDER = {'480p': 0, '720p': 1, '1080p': 2, '2k': 3, '4k': 4}

pending_groups = {}
_name_warned = []   # the 'Telegram renamed the file' notice is sent once per run
user_jobs = {}            # user_id -> [(key, group)] waiting to be posted
user_worker_running = {}
_running_group = {}       # user_id -> group_id currently being posted
_running_info = {}        # user_id -> {'gid','season','episode','channel','group'} for /queue


def _norm(value):
    """'01' and '1' are the same season/episode."""
    if value is None:
        return None
    value = str(value).strip()
    return str(int(value)) if value.isdigit() else value.lower()


def _find_group_key(user_id, channel_id, season, episode):
    """
    Same episode => same post, even when only some filenames carry a season.
    A file without a season joins the group (and takes its season); two files
    with *different* explicit seasons stay separate (S1E05 vs S2E05).
    """
    for key, group in pending_groups.items():
        if key[0] != user_id or key[1] != channel_id or _norm(key[3]) != _norm(episode):
            continue
        group_season = group.get('season')
        if group_season is None or season is None or _norm(group_season) == _norm(season):
            return key
    return None


def _quality_sort_key(entry):
    return QUALITY_ORDER.get((entry.get('quality') or '').lower(), 99)


async def _get_cached_images(client, format_doc):
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
            await process_thumbnail(cropped_path)
        except Exception as e:
            logger.error(f"Could not crop thumbnail for format {format_id}: {e}")
            cropped_path = None

    return (raw_path if os.path.exists(raw_path) else None), cropped_path


async def _send_post(send, fmt, which, season, episode):
    """
    Send a Main/Sub post using the shared renderer (helper/post_render.py), so posting and
    👁 Preview always look the same. If Telegram rejects the formatting, retry once with the
    safe escaped version instead of failing the whole post.
    """
    text = render_post(fmt, which, season, episode)
    try:
        return await send(text)
    except Exception as e:
        if not any(w in str(e).upper() for w in ('ENTIT', 'PARSE', 'TAG')):
            raise
        logger.warning(f"Telegram rejected the {which} post formatting ({e}); sending the escaped version")
        raw = fmt['main_post'] if which == 'main' else fmt['sub_post']
        return await send(render_bold(fill(raw, season, episode)))


async def _channel_picker_view():
    """Returns (text, markup) for the inline sub-channel picker, or (error_text, None)."""
    channels = await codeflixbots.get_all_subchannels()
    channels = [ch for ch in channels if ch.get('formats')]
    if not channels:
        return "**No sub channels with a format set up yet.** Use `/add_channel` first.", None

    if not await codeflixbots.get_main_channel():
        return "**No Main channel set yet.** Use `/set_main_channel` first.", None

    buttons = [
        [InlineKeyboardButton(ch.get('title', str(ch['_id'])), callback_data=f"apch_{ch['_id']}")]
        for ch in channels
    ]
    buttons.append([InlineKeyboardButton("✖ Cancel", callback_data="apcancel")])
    return "**📡 Choose a sub channel to auto-post to:**", InlineKeyboardMarkup(buttons)


async def _find_targets(arg):
    """Formats matching '/auto_post <channel id> [label]' or '/auto_post <label or channel title>'."""
    tokens = arg.strip().split(maxsplit=1)
    channels = [c for c in await codeflixbots.get_all_subchannels() if c.get('formats')]
    cid_filter, query = None, arg.strip().lower()
    if tokens and re.fullmatch(r'-?\d+', tokens[0]):
        cid_filter = int(tokens[0])
        query = tokens[1].strip().lower() if len(tokens) > 1 else ''
    cands = [(ch, f) for ch in channels if cid_filter is None or ch['_id'] == cid_filter for f in ch['formats']]
    if not query:
        return cands
    exact = [(c, f) for c, f in cands if f['label'].strip().lower() == query]
    if exact:
        return exact
    return [(c, f) for c, f in cands if query in f['label'].lower() or query in c.get('title', '').lower()]


@Client.on_message(filters.private & filters.command('auto_post') & admin_filter)
async def auto_post_cmd(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip():
        if not await codeflixbots.get_main_channel():
            return await message.reply_text("**No Main channel set yet.** Use the Admin panel → Settings first.")
        targets = await _find_targets(parts[1])
        if len(targets) == 1:
            ch, fmt = targets[0]
            return await _start_session(client, message, message.from_user.id, ch, fmt)
        if len(targets) > 1:
            buttons = [[InlineKeyboardButton(f"{c.get('title', c['_id'])} · {f['label']}"[:60],
                                             callback_data=f"apfmt_{c['_id']}_{f['format_id']}")]
                       for c, f in targets[:20]]
            return await message.reply_text("**Several formats match — pick one:**",
                                            reply_markup=InlineKeyboardMarkup(buttons))
        await message.reply_text(f"**No channel or format matches** `{parts[1].strip()[:40]}`. Pick one below:")
    text, markup = await _channel_picker_view()
    await message.reply_text(text, reply_markup=markup)


async def stop_session(client, user_id):
    """End the session; groups still collecting are posted right away. Returns True if one was active."""
    had_session = auto_post_sessions.pop(user_id, None)
    await codeflixbots.ap_session_del(user_id)
    for key in [k for k in pending_groups if k[0] == user_id]:
        group = pending_groups.pop(key)
        if group.get('timer_task'):
            group['timer_task'].cancel()
        await _enqueue_job(client, key, group)
    return bool(had_session)


@Client.on_message(filters.private & filters.command('stop_auto_post') & admin_filter)
async def stop_auto_post_cmd(client, message):
    user_id = message.from_user.id
    had_session = await stop_session(client, user_id)

    await message.reply_text(
        "**🛑 Auto-post session ended.**" if had_session else "**No active auto-post session.**"
    )


@Client.on_callback_query(filters.regex(r"^apcancel$"))
async def channel_picker_cancel(client, callback_query: CallbackQuery):
    await callback_query.answer()
    try:
        await callback_query.message.edit_text("**Cancelled.**")
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^apback$"))
async def channel_picker_back(client, callback_query: CallbackQuery):
    if not await codeflixbots.is_admin(callback_query.from_user.id):
        return await callback_query.answer("Admins only.", show_alert=True)
    text, markup = await _channel_picker_view()
    await callback_query.answer()
    await callback_query.message.edit_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^apch_(-?\d+)$"))
async def channel_selected(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if not await codeflixbots.is_admin(user_id):
        return await callback_query.answer("Admins only.", show_alert=True)

    channel_id = int(callback_query.matches[0].group(1))
    channel = await codeflixbots.get_subchannel(channel_id)
    formats = channel.get('formats', []) if channel else []
    if not channel or not formats:
        return await callback_query.answer("That channel no longer has a format.", show_alert=True)

    await callback_query.answer()
    if len(formats) == 1:
        await callback_query.message.edit_text(
            f"**Selected:** {channel.get('title')} — `{formats[0]['label']}`"
        )
        return await _start_session(client, callback_query.message, user_id, channel, formats[0])

    buttons = [
        [InlineKeyboardButton(fmt['label'], callback_data=f"apfmt_{channel_id}_{fmt['format_id']}")]
        for fmt in formats
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="apback")])
    await callback_query.message.edit_text(
        f"**{channel.get('title')}** has multiple formats — pick one:",
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


def _job_sort_key(job):
    key, group = job
    season = group.get('season')
    ep = key[3]
    return (int(season) if season and str(season).isdigit() else 0,
            int(ep) if ep and str(ep).isdigit() else 99999)


async def _start_session(client, message, user_id, channel, fmt):
    auto_post_sessions[user_id] = {
        'channel_id': channel['_id'],
        'channel_title': channel.get('title', str(channel['_id'])),
        'format': fmt,
    }
    await codeflixbots.ap_session_set(user_id, channel['_id'], fmt['format_id'])
    await codeflixbots.ap_recent_add(user_id, channel['_id'], fmt['format_id'])
    window = await codeflixbots.get_autopost_window(DEFAULT_WINDOW_SECONDS)
    await client.send_message(
        user_id,
        f"**✅ Auto-post ready.**\n\n"
        f"**Sub channel:** {channel.get('title')}\n"
        f"**Format:** `{fmt['label']}`\n\n"
        "Now send the file(s). Files for the same episode (different qualities) can be sent one after another — "
        f"I'll wait {window}s after the last one before posting "
        "(change it with `/autopost_window <seconds>`).\n"
        "Send `/stop_auto_post` when you're done."
    )


@Client.on_message(filters.private & filters.command('autopost_window') & admin_filter)
async def autopost_window_cmd(client, message):
    parts = message.text.split()
    current = await codeflixbots.get_autopost_window(DEFAULT_WINDOW_SECONDS)
    if len(parts) < 2:
        return await message.reply_text(
            f"**⏱ Grouping window:** `{current}` seconds.\n"
            "Files of the same episode must arrive within this time of each other to share one post.\n"
            "Change it: `/autopost_window 30` (3–300)."
        )
    if not parts[1].isdigit() or not 3 <= int(parts[1]) <= 300:
        return await message.reply_text("**Please send a number of seconds between 3 and 300.**")
    await codeflixbots.set_autopost_window(int(parts[1]))
    await message.reply_text(f"**✅ Grouping window set to {int(parts[1])} seconds.**")


@Client.on_message(
    filters.private & (filters.document | filters.video | filters.audio) & admin_filter,
    group=2
)
async def auto_post_file_handler(client, message):
    user_id = message.from_user.id
    session = auto_post_sessions.get(user_id)
    if not session:
        return

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

    entry = {
        'message': message, 'file_id': file_id, 'file_name': file_name,
        'media_type': media_type, 'quality': quality, 'done': False,
    }

    # No await between the lookup and the insert, so concurrent handlers can't create twins.
    new_group = False
    key = _find_group_key(user_id, session['channel_id'], season, episode)
    if key is None:
        key = (user_id, session['channel_id'], season, episode)
        pending_groups[key] = {
            'files': [], 'timer_task': None, 'season': season,
            'group_id': uuid.uuid4().hex[:10], 'stages': {},
            'channel_id': session['channel_id'],
            'channel_title': session['channel_title'],
            'format': session['format'],
            'format_id': session['format']['format_id'],
        }
        new_group = True
    group = pending_groups[key]
    season_revealed = group.get('season') is None and season is not None
    if season_revealed:
        group['season'] = season   # a later file revealed the season for the whole episode
    group['files'].append(entry)

    if group['timer_task']:
        group['timer_task'].cancel()
    group['timer_task'] = asyncio.create_task(_debounce_and_flush(client, key))

    # Save to MongoDB so a restart doesn't lose it
    if new_group:
        await codeflixbots.ap_group_create({
            '_id': group['group_id'], 'user_id': user_id,
            'channel_id': session['channel_id'], 'format_id': group['format_id'],
            'season': season, 'key_season': key[2], 'episode': episode,
            'status': 'collecting', 'stages': {}, 'created': datetime.utcnow(),
        })
    elif season_revealed:
        await codeflixbots.ap_group_set(group['group_id'], {'season': season})
    entry['db_id'] = await codeflixbots.ap_file_add({
        'group_id': group['group_id'], 'user_id': user_id,
        'chat_id': message.chat.id, 'message_id': message.id,
        'file_id': file_id, 'file_name': file_name, 'media_type': media_type,
        'quality': quality, 'seq': time.time_ns(), 'done': False,
    })

    await message.reply_text(
        f"**📥 Queued** `{file_name[:50]}`\n"
        f"Season `{group.get('season') or 'XX'}` Episode `{episode}` Quality `{quality or 'Unknown'}`"
    )


async def _debounce_and_flush(client, key):
    try:
        window = await codeflixbots.get_autopost_window(DEFAULT_WINDOW_SECONDS)
        await asyncio.sleep(window)
    except asyncio.CancelledError:
        return
    group = pending_groups.pop(key, None)
    if group:
        await _enqueue_job(client, key, group)


async def _enqueue_job(client, key, group, notify=True):
    user_id = key[0]
    jobs = user_jobs.setdefault(user_id, [])

    should_notify = notify and (len(jobs) > 0 or user_worker_running.get(user_id, False))
    need_worker = not user_worker_running.get(user_id, False)
    if need_worker:
        user_worker_running[user_id] = True

    jobs.append((key, group))
    await codeflixbots.ap_group_set(group['group_id'], {'status': 'queued'})

    if should_notify:
        season, episode = group.get('season'), key[3]
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
    try:
        while user_jobs.get(user_id):
            # Start posting only once you've stopped sending files for the grouping window,
            # so the queued episodes can be posted in episode order, not arrival order.
            while any(k[0] == user_id for k in pending_groups):
                await asyncio.sleep(1)
            jobs = user_jobs.get(user_id)
            if not jobs:
                break
            jobs.sort(key=_job_sort_key)
            key, group = jobs.pop(0)
            await _flush_group(client, key, group)
    finally:
        user_worker_running[user_id] = False


def _summ(key, group):
    files = group.get('files', [])
    return {'gid': group['group_id'], 'season': group.get('season'), 'episode': key[3],
            'channel': group.get('channel_title', ''), 'files': len(files),
            'done': sum(1 for f in files if f.get('done'))}


def autopost_snapshot(user_id):
    """What /queue shows for auto-post: the post in progress, posts waiting, episodes still collecting."""
    running = None
    info = _running_info.get(user_id)
    if info:
        g = info['group']
        running = {'gid': info['gid'], 'season': info['season'], 'episode': info['episode'],
                   'channel': info['channel'], 'files': len(g.get('files', [])),
                   'done': sum(1 for f in g.get('files', []) if f.get('done'))}
    waiting = [_summ(k, g) for k, g in sorted(user_jobs.get(user_id, []), key=_job_sort_key)]
    collecting = [_summ(k, g) for k, g in pending_groups.items() if k[0] == user_id]
    session = auto_post_sessions.get(user_id)
    return {'running': running, 'waiting': waiting, 'collecting': collecting,
            'session': (f"{session['channel_title']} — {session['format']['label']}" if session else None)}


async def remove_group(user_id, gid):
    """Drop one episode post that hasn't started (collecting or waiting). Returns True if found."""
    for key in [k for k, g in pending_groups.items() if k[0] == user_id and g['group_id'] == gid]:
        group = pending_groups.pop(key)
        if group.get('timer_task'):
            group['timer_task'].cancel()
        await codeflixbots.ap_group_delete(gid)
        return True
    jobs = user_jobs.get(user_id, [])
    for job in jobs:
        if job[1]['group_id'] == gid:
            jobs.remove(job)
            await codeflixbots.ap_group_delete(gid)
            return True
    return False


async def cancel_all_posts(user_id):
    """Used by /cancel_queue: drop collecting groups, queued posts, and stop the one in progress."""
    cancelled = 0
    for key in [k for k in pending_groups if k[0] == user_id]:
        group = pending_groups.pop(key)
        if group.get('timer_task'):
            group['timer_task'].cancel()
        cancelled += 1
    cancelled += len(user_jobs.pop(user_id, []))
    running = _running_group.get(user_id)
    if running and request_cancel(running):
        cancelled += 1
    await codeflixbots.ap_groups_delete_for_user(user_id)
    return cancelled


async def _flush_group(client, key, group):
    user_id, channel_id, _key_season, episode = key
    season = group.get('season')
    group_id = group['group_id']
    stages = group.setdefault('stages', {})
    files = sorted(group['files'], key=_quality_sort_key)
    new_task(user_id, group_id)          # one cancel id for the whole episode post
    _running_group[user_id] = group_id
    _running_info[user_id] = {'gid': group_id, 'season': season, 'episode': episode,
                              'channel': group['channel_title'], 'group': group}

    async def mark(stage):
        stages[stage] = True
        await codeflixbots.ap_group_set(group_id, {f"stages.{stage}": True})

    # NOTE: the MongoDB records are deleted only when the post finishes, is cancelled, or fails
    # with a handled error. A crash or restart leaves them in place, so it resumes from the
    # first unfinished step instead of posting twice.
    try:
        await codeflixbots.ap_group_set(group_id, {'status': 'posting'})
        if not await codeflixbots.get_subchannel(channel_id):
            raise RuntimeError("This sub channel was deleted — skipped (nothing was posted).")
        main_channel_id = await codeflixbots.get_main_channel()
        if not main_channel_id:
            raise RuntimeError("Main channel is not set — use /set_main_channel (nothing was posted).")

        # Read the format fresh so edits made while the post was waiting are used
        fmt = await codeflixbots.get_format(channel_id, group['format_id']) or group['format']

        verb = "Resuming" if group.get('resumed') else "Posting"
        await client.send_message(user_id, f"**⚙️ {verb} S{season or 'XX'}E{episode}...**")

        raw_image, cropped_thumb = await _get_cached_images(client, fmt)

        if not stages.get('sub_intro'):
            raise_if_cancelled(group_id)
            async def send_sub(text):
                if raw_image:
                    return await client.send_photo(channel_id, photo=raw_image, caption=text, parse_mode=ParseMode.HTML)
                return await client.send_message(channel_id, text, parse_mode=ParseMode.HTML)
            await _send_post(send_sub, fmt, 'sub', season, episode)
            await mark('sub_intro')

        uploaded = sum(1 for e in files if e.get('done'))
        for entry in files:
            if entry.get('done'):
                continue
            raise_if_cancelled(group_id)
            ok = await _rename_and_upload(
                client, entry, fmt, channel_id, season, episode, cropped_thumb, user_id, group_id
            )
            if ok:
                entry['done'] = True
                uploaded += 1
                await codeflixbots.ap_file_done(entry.get('db_id'))

        raise_if_cancelled(group_id)
        if uploaded == 0:
            raise RuntimeError("None of the files could be uploaded, so the Main channel post was not sent.")
        if not stages.get('sub_sticker'):
            sub_sticker = await codeflixbots.get_sub_sticker()
            if sub_sticker:
                try:
                    await client.send_sticker(channel_id, sub_sticker)
                except Exception as e:
                    logger.error(f"Could not send sub sticker to {channel_id}: {e}")
            await mark('sub_sticker')

        if not stages.get('main_post'):
            raise_if_cancelled(group_id)
            channel = await codeflixbots.get_subchannel(channel_id)
            invite_link = channel.get('invite_link') if channel else None
            reply_markup = None
            if invite_link:
                reply_markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("DOWNLOAD", url=invite_link)]]
                )

            async def send_main(text):
                if raw_image:
                    return await client.send_photo(
                        main_channel_id, photo=raw_image, caption=text,
                        parse_mode=ParseMode.HTML, reply_markup=reply_markup
                    )
                return await client.send_message(
                    main_channel_id, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
                )
            await _send_post(send_main, fmt, 'main', season, episode)
            await mark('main_post')

        if not stages.get('main_sticker'):
            main_sticker = await codeflixbots.get_main_sticker()
            if main_sticker:
                try:
                    await client.send_sticker(main_channel_id, main_sticker)
                except Exception as e:
                    logger.error(f"Could not send main sticker to {main_channel_id}: {e}")
            await mark('main_sticker')

        await codeflixbots.ap_group_delete(group_id)
        await client.send_message(
            user_id,
            f"**✅ Done — S{season or 'XX'}E{episode} posted to {group['channel_title']} "
            f"({uploaded} file(s)) and the Main channel.**"
        )
    except TaskCancelled:
        await codeflixbots.ap_group_delete(group_id)
        main_note = "was already sent" if stages.get('main_post') else "was not sent"
        try:
            await client.send_message(
                user_id,
                f"**❌ Cancelled S{season or 'XX'}E{episode}.**\n"
                f"{sum(1 for e in files if e.get('done'))} of {len(files)} file(s) were already uploaded to "
                f"{group['channel_title']}; the Main channel post {main_note}."
            )
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Error flushing group {key}: {e}")
        await codeflixbots.ap_group_delete(group_id)
        try:
            await client.send_message(user_id, f"**❌ Error posting S{season or 'XX'}E{episode}:** `{e}`")
        except Exception:
            pass
    finally:
        _running_group.pop(user_id, None)
        _running_info.pop(user_id, None)
        drop_task(group_id)


async def _rename_and_upload(client, entry, fmt, channel_id, season, episode, thumb_path, user_id, task_id=None):
    """Returns True when the file was uploaded, False if it failed. Raises TaskCancelled on Cancel."""
    message = entry['message']
    file_name = entry['file_name']
    quality = entry['quality']
    media_type = entry['media_type']
    download_path = None
    file_path = None
    progress_msg = None

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
        unique_id = f"{user_id}_{time.time_ns()}_{quality or 'na'}"
        download_path = f"downloads/{unique_id}{ext}"

        cancel_markup = (
            InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄᴀɴᴄᴇʟ •", callback_data=f"cancel_{task_id}")]])
            if task_id else None
        )
        progress_msg = await client.send_message(
            user_id, f"**⬇️ Downloading** `{file_name[:50]}`...", reply_markup=cancel_markup
        )

        try:
            file_path = await message.download(
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", progress_msg, time.time(), client, task_id)
            )
        except TypeError:
            file_path = await message.download(file_name=download_path)

        raise_if_cancelled(task_id)   # a stopped download returns None
        file_path = await wait_for_download(file_path, download_path)

        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            await safe_edit(progress_msg, "**🔧 Adding metadata...**")
            try:
                file_path, metadata_added = await add_metadata_smart(file_path, user_id, task_id)
                if not metadata_added:
                    logger.warning(f"Metadata not embedded for {new_filename}, uploading without it.")
            except TaskCancelled:
                raise
            except Exception as e:
                logger.error(f"Metadata error for {new_filename}: {e}")

        await safe_edit(progress_msg, f"**⬆️ Uploading** `{new_filename[:50]}`...")
        upload_params = {
            'chat_id': channel_id,
            'caption': f"**{new_filename}**",
            'thumb': thumb_path,
            'progress': progress_for_pyrogram,
            'progress_args': ("Uploading...", progress_msg, time.time(), client, task_id)
        }

        raise_if_cancelled(task_id)
        if media_type == "document":
            sent = await client.send_document(document=file_path, file_name=new_filename, **upload_params)
        elif media_type == "video":
            sent = await client.send_video(video=file_path, file_name=new_filename, **upload_params)
        elif media_type == "audio":
            sent = await client.send_audio(audio=file_path, file_name=new_filename, **upload_params)
        else:
            sent = True
        if sent is None:
            raise_if_cancelled(task_id)   # a stopped upload returns None
        stored = stored_name_mismatch(sent, media_type, new_filename)
        if stored and not _name_warned:
            _name_warned.append(True)
            try:
                await client.send_message(
                    user_id,
                    f"⚠️ **Telegram saved the file name as** `{stored}`\n**instead of** `{new_filename}`\n"
                    "(shown once per run)"
                )
            except Exception:
                pass

        try:
            await progress_msg.delete()
        except Exception:
            pass
        return True

    except TaskCancelled:
        if progress_msg:
            await safe_edit(progress_msg, f"**❌ Cancelled** `{file_name[:50]}`")
        raise
    except Exception as e:
        logger.error(f"Error renaming/uploading {file_name}: {e}")
        try:
            await client.send_message(user_id, f"**❌ Failed to process** `{file_name[:50]}`: `{e}`")
        except Exception:
            pass
        return False
    finally:
        # also remove the metadata-processed copy (it was left behind before)
        await cleanup_files(download_path, file_path)


# ── Restore after a restart ────────────────────────────────────────────────────

async def _fetch_messages(client, chat_id, message_ids):
    """Fetch messages in batches; returns {message_id: Message} for the ones that still exist."""
    found = {}
    for start in range(0, len(message_ids), 100):
        chunk = message_ids[start:start + 100]
        try:
            msgs = await client.get_messages(chat_id, chunk)
        except Exception as e:
            logger.error(f"Could not fetch queued messages {chunk[:3]}...: {e}")
            continue
        if not isinstance(msgs, list):
            msgs = [msgs]
        for m in msgs:
            if m and not getattr(m, 'empty', False) and (m.document or m.video or m.audio):
                found[m.id] = m
    return found


async def restore_autopost(client):
    """Called once at startup: restore sessions and resume unfinished posts."""
    try:
        sessions = await codeflixbots.ap_sessions_all()
        groups = await codeflixbots.ap_groups_load()
    except Exception as e:
        logger.error(f"Could not load auto-post state: {e}")
        return

    for doc in sessions:
        user_id = doc['_id']
        channel = await codeflixbots.get_subchannel(doc['channel_id'])
        fmt = await codeflixbots.get_format(doc['channel_id'], doc['format_id']) if channel else None
        if not channel or not fmt:
            await codeflixbots.ap_session_del(user_id)
            continue
        auto_post_sessions[user_id] = {
            'channel_id': channel['_id'],
            'channel_title': channel.get('title', str(channel['_id'])),
            'format': fmt,
        }
        try:
            await client.send_message(
                user_id,
                f"**♻️ Auto-post session restored:** {channel.get('title')} — `{fmt['label']}`\n"
                "Send `/stop_auto_post` when you're done."
            )
        except Exception:
            pass

    per_user = {}
    for g, files in groups:
        user_id = g['user_id']
        channel = await codeflixbots.get_subchannel(g['channel_id'])
        fmt = await codeflixbots.get_format(g['channel_id'], g['format_id']) if channel else None
        if not channel or not fmt:
            await codeflixbots.ap_group_delete(g['_id'])
            continue

        todo_ids = [f['message_id'] for f in files if not f.get('done')]
        chat_id = files[0]['chat_id'] if files else user_id
        messages = await _fetch_messages(client, chat_id, todo_ids) if todo_ids else {}

        entries = []
        for f in files:
            if f.get('done'):
                entries.append({'message': None, 'file_id': f['file_id'], 'file_name': f['file_name'],
                                'media_type': f['media_type'], 'quality': f.get('quality'),
                                'done': True, 'db_id': f['_id']})
            elif f['message_id'] in messages:
                entries.append({'message': messages[f['message_id']], 'file_id': f['file_id'],
                                'file_name': f['file_name'], 'media_type': f['media_type'],
                                'quality': f.get('quality'), 'done': False, 'db_id': f['_id']})
        if not any(not e['done'] for e in entries) and not g.get('stages', {}).get('sub_intro'):
            await codeflixbots.ap_group_delete(g['_id'])   # nothing left to post
            continue

        group = {
            'files': entries, 'timer_task': None, 'season': g.get('season'),
            'group_id': g['_id'], 'stages': g.get('stages', {}), 'resumed': True,
            'channel_id': channel['_id'],
            'channel_title': channel.get('title', str(channel['_id'])),
            'format': fmt, 'format_id': g['format_id'],
        }
        key = (user_id, g['channel_id'], g.get('key_season'), g['episode'])
        per_user.setdefault(user_id, []).append((key, group))

    for user_id, jobs in per_user.items():
        try:
            await client.send_message(
                user_id,
                f"**♻️ Bot restarted — resuming {len(jobs)} unfinished auto-post(s).**"
            )
        except Exception:
            pass
        for key, group in jobs:
            await _enqueue_job(client, key, group, notify=False)
