import os
import re
import time
import shutil
import asyncio
import logging
from datetime import datetime
from PIL import Image
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from plugins.antinsfw import check_anti_nsfw
from helper.utils import progress_for_pyrogram, humanbytes, convert
from helper.database import codeflixbots
from helper import patterns as custom_patterns
from helper.cancel import (
    TaskCancelled, new_task, drop_task, is_cancelled, raise_if_cancelled,
    set_proc, request_cancel, set_current, current_for, get_task
)
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

user_queues = {}
user_processing = {}
user_cancel = {}

pending_manual_input = {}
pending_backlog = {}   # user_id -> files waiting for their own season/episode/quality prompt

FIELD_NAMES = {
    'episode': 'Episode number',
    'season': 'Season number',
    'quality': 'Quality (e.g. 720p)',
}

os.makedirs("downloads", exist_ok=True)
os.makedirs("downloads/thumbs", exist_ok=True)
os.makedirs("metadata", exist_ok=True)

SEASON_EPISODE_PATTERNS = [
    (re.compile(r'S(\d+)\s*-\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'\[(\d+)\s*-', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'\[E(\d+)\s*-', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'\[S(\d+)[\s-]+(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)', re.IGNORECASE), ('season', None)),
    (re.compile(r'\[S(\d+)\]\s*\[?E(\d+)\]?', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'\[S(\d+)\]', re.IGNORECASE), ('season', None)),
    (re.compile(r'\bS(\d+)\b', re.IGNORECASE), ('season', None)),
    (re.compile(r'(?:^|[\s\[\-_])(?:E|EP)(\d+)(?:$|[\s\]\-_])', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'Episode\s*(\d+)', re.IGNORECASE), (None, 'episode')),
]

QUALITY_PATTERNS = [
    (re.compile(r'\b(4k|2160p)\b', re.IGNORECASE), lambda m: "4k"),
    (re.compile(r'\b(2k|1440p)\b', re.IGNORECASE), lambda m: "2k"),
    (re.compile(r'\b(1080p)\b', re.IGNORECASE), lambda m: "1080p"),
    (re.compile(r'\b(720p)\b', re.IGNORECASE), lambda m: "720p"),
    (re.compile(r'\b(576p)\b', re.IGNORECASE), lambda m: "576p"),
    (re.compile(r'\b(480p)\b', re.IGNORECASE), lambda m: "480p"),
    (re.compile(r'\b(HDRip|HDTV)\b', re.IGNORECASE), lambda m: m.group(1)),
    (re.compile(r'\[(4k|2160p|2k|1440p|1080p|720p|576p|480p)\]', re.IGNORECASE), lambda m: m.group(1)),
]

def _builtin_season_episode(text):
    if not text:
        return None, None
    season_found = None
    episode_found = None
    for pattern, (season_group, episode_group) in SEASON_EPISODE_PATTERNS:
        if season_found and episode_found:
            break
        match = pattern.search(text)
        if not match:
            continue
        if season_group and not season_found:
            try:
                season_found = match.group(1)
            except:
                pass
        if episode_group and not episode_found:
            try:
                ep_idx = 2 if season_group else 1
                episode_found = match.group(ep_idx)
            except:
                try:
                    episode_found = match.group(1)
                except:
                    pass
    logger.info(f"Detected season={season_found}, episode={episode_found}")
    return season_found, episode_found

def _builtin_quality(text):
    if not text:
        return None
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(text)
        if match:
            return extractor(match)
    return None

def extract_season_episode(text):
    """Your custom patterns (Admin panel -> Patterns) are tried first, then the built-in rules."""
    custom = custom_patterns.match_custom(text)
    if custom and custom.get('episode'):
        season = custom.get('season')
        if not season:
            season, _ = _builtin_season_episode(text)   # pattern has no {season}: fall back for the season
        return season, custom['episode']
    return _builtin_season_episode(text)


def extract_quality(text):
    custom = custom_patterns.match_custom(text)
    if custom and custom.get('quality'):
        return custom['quality']
    return _builtin_quality(text)


BUILTIN_EXAMPLES = [
    "S2 - 05", "[05 -", "[E05 -", "[S2 05]", "S2E05  /  S2EP05", "S2 E05",
    "Season 2 Episode 5", "Season 2  (season only)", "[S2][E05]", "[S2]  (season only)",
    "S2  (season only)", "E05  /  EP05", "Episode 5",
]


def fill_template(template, season, episode, quality):
    """
    Build the new name from the rename format. {season} {episode} {quality} are the
    variables. The legacy plain words Season / Episode / QUALITY are only replaced when the
    format uses no braces at all (before, a title containing the word "Season" was mangled).
    """
    s_val = str(season) if season else 'XX'
    e_val = str(episode) if episode else 'XX'
    q_val = str(quality) if quality else 'Unknown'
    if any(ph in template for ph in ('{season}', '{episode}', '{quality}')):
        return (template.replace('{season}', s_val)
                        .replace('{episode}', e_val)
                        .replace('{quality}', q_val))
    return (template.replace('Season', s_val)
                    .replace('Episode', e_val)
                    .replace('QUALITY', q_val))


def explain_detection(text):
    """What would be detected for this filename, and which rule decided it."""
    custom = custom_patterns.match_custom(text)
    season, episode = extract_season_episode(text)
    quality = extract_quality(text)
    source = "built-in rules"
    if custom and custom.get('episode'):
        source = f"your pattern: {custom['template']}"
    else:
        for i, (pattern, (_sg, eg)) in enumerate(SEASON_EPISODE_PATTERNS, start=1):
            if eg and pattern.search(text or ''):
                source = f"built-in #{i} ({BUILTIN_EXAMPLES[i - 1]})"
                break
    return {'season': season, 'episode': episode, 'quality': quality, 'source': source}


async def safe_edit(msg, text):
    try:
        await msg.edit(text)
    except Exception:
        pass

async def cleanup_files(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Error removing {path}: {e}")

async def wait_for_download(file_path, download_path, timeout=120):
    temp_path = f"{file_path}.temp" if file_path else f"{download_path}.temp"
    waited = 0
    while waited < timeout:
        if not os.path.exists(temp_path):
            break
        await asyncio.sleep(2)
        waited += 2
    if os.path.exists(temp_path):
        raise Exception(f"Download timed out after {timeout}s")
    if not file_path or not os.path.exists(file_path):
        raise Exception("Download failed — file not found after completion")
    size = os.path.getsize(file_path)
    if size == 0:
        raise Exception("Download failed — file is empty")
    logger.info(f"Download complete: {file_path} ({size} bytes)")
    return file_path

async def process_thumbnail(thumb_path):
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    try:
        with Image.open(thumb_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
            img = img.resize((320, 320), Image.LANCZOS)
            img.save(thumb_path, "JPEG", quality=95, subsampling=0, optimize=True)
        return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail processing failed: {e}")
        await cleanup_files(thumb_path)
        return None

def _user_thumb_paths(user_id):
    return (f"downloads/thumbs/user_{user_id}_raw.jpg",
            f"downloads/thumbs/user_{user_id}_crop.jpg")

def clear_thumb_cache(user_id):
    for path in _user_thumb_paths(user_id):
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Error removing cached thumb {path}: {e}")

async def get_user_thumb(client, user_id):
    """
    Same logic as the auto-post bot: MongoDB only holds the Telegram file_id.
    The image is downloaded once, cropped 1:1 from the centre, and cached on
    disk. After a restart / wiped filesystem it is simply re-downloaded.
    Returns the cropped file path, or None if no thumbnail is set.
    """
    file_id = await codeflixbots.get_thumbnail(user_id)
    if not file_id:
        return None

    # Old versions stored a local path here; that is useless after a restart.
    if isinstance(file_id, str) and (file_id.startswith("downloads/") or os.path.sep in file_id):
        await codeflixbots.set_thumbnail(user_id, file_id=None)
        return None

    raw_path, cropped_path = _user_thumb_paths(user_id)

    if not os.path.exists(raw_path):
        try:
            await client.download_media(file_id, file_name=raw_path)
        except Exception as e:
            logger.error(f"Could not download thumbnail for user {user_id}: {e}")
            return None

    if not os.path.exists(cropped_path):
        try:
            shutil.copyfile(raw_path, cropped_path)
            if not await process_thumbnail(cropped_path):
                return None
        except Exception as e:
            logger.error(f"Could not crop thumbnail for user {user_id}: {e}")
            return None

    return cropped_path if os.path.exists(cropped_path) else None

def build_caption(template, new_filename, file_path):
    """Fill {filename} {filesize} {duration} in /set_caption text (they were sent literally before)."""
    if not template:
        return f"**{new_filename}**"
    try:
        size = humanbytes(os.path.getsize(file_path)) if file_path and os.path.exists(file_path) else ""
    except Exception:
        size = ""
    duration = ""
    try:
        parser = createParser(file_path)
        if parser:
            with parser:
                meta = extractMetadata(parser)
            if meta and meta.has("duration"):
                duration = convert(int(meta.get("duration").total_seconds()))
    except Exception as e:
        logger.warning(f"Could not read duration: {e}")
    try:
        return template.format(filename=new_filename, filesize=size, duration=duration)
    except Exception:
        # caption contains stray { } — fall back to simple replacement
        return (template.replace("{filename}", new_filename)
                        .replace("{filesize}", size)
                        .replace("{duration}", duration))

def escape_metadata(text):
    return str(text).replace('"', '\\"').replace("'", "\\'")

async def probe_streams(input_path):
    ffprobe = shutil.which('ffprobe')
    result = {'video': [], 'audio': [], 'subtitle': []}
    if not ffprobe:
        return result

    cmd = [
        ffprobe, '-v', 'error', '-show_entries', 'stream=index,codec_type',
        '-of', 'csv=p=0', input_path
    ]
    try:
        process = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            ),
            timeout=30
        )
        stdout, _ = await process.communicate()
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
        return result

    type_map = {'video': 'video', 'audio': 'audio', 'subtitle': 'subtitle'}
    for line in stdout.decode(errors='ignore').splitlines():
        line = line.strip()
        if not line or ',' not in line:
            continue
        _, codec_type = line.split(',', 1)
        codec_type = codec_type.strip()
        if codec_type in type_map:
            key = type_map[codec_type]
            result[key].append(len(result[key]))

    return result

FFMPEG_TIMEOUT = 1800  # seconds; a stream-copy remux of a few hundred MB takes seconds


async def _run_ffmpeg(cmd, task_id=None):
    """Run ffmpeg; the process can be killed by Cancel, and the timeout really applies now
    (before, wait_for only covered *starting* the process, so a stuck ffmpeg hung forever)."""
    p = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    set_proc(task_id, p)
    try:
        await asyncio.wait_for(p.communicate(), timeout=FFMPEG_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            p.kill()
        except ProcessLookupError:
            pass
        await p.wait()
        raise RuntimeError("ffmpeg timed out")
    finally:
        set_proc(task_id, None)
    return p.returncode


async def add_metadata_ffmpeg(input_path, user_id, task_id=None):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return input_path, False

    if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
        raise RuntimeError("Input file missing or empty")

    ext = os.path.splitext(input_path)[1]
    output_path = f"{os.path.splitext(input_path)[0]}_meta{ext}"

    title = await codeflixbots.get_title(user_id)
    artist = await codeflixbots.get_artist(user_id)
    author = await codeflixbots.get_author(user_id)
    video_title = await codeflixbots.get_video(user_id)
    audio_title = await codeflixbots.get_audio(user_id)
    subtitle_title = await codeflixbots.get_subtitle(user_id)

    streams = await probe_streams(input_path)

    per_stream_args = []
    for idx in streams['video']:
        per_stream_args += ['-metadata:s:v:' + str(idx), f'title={escape_metadata(video_title)}']
    for idx in streams['audio']:
        per_stream_args += ['-metadata:s:a:' + str(idx), f'title={escape_metadata(audio_title)}']
    for idx in streams['subtitle']:
        per_stream_args += ['-metadata:s:s:' + str(idx), f'title={escape_metadata(subtitle_title)}']

    cmd1 = [
        ffmpeg, '-y', '-i', input_path,
        '-map', '0', '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy',
        '-metadata', f'title={escape_metadata(title)}',
        '-metadata', f'artist={escape_metadata(artist)}',
        '-metadata', f'author={escape_metadata(author)}',
        *per_stream_args,
        output_path
    ]
    try:
        rc = await _run_ffmpeg(cmd1, task_id)
        raise_if_cancelled(task_id)
        if rc == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            await cleanup_files(input_path)
            return output_path, True
    except TaskCancelled:
        await cleanup_files(output_path)
        raise
    except Exception as e:
        logger.warning(f"FFmpeg metadata level 1 failed: {e}")

    if os.path.exists(output_path):
        await cleanup_files(output_path)
    cmd2 = [
        ffmpeg, '-y', '-i', input_path,
        '-map', '0', '-c:v', 'copy', '-c:a', 'copy',
        '-metadata', f'title={escape_metadata(title)}',
        '-metadata', f'artist={escape_metadata(artist)}',
        '-metadata', f'author={escape_metadata(author)}',
    ]
    for idx in streams['video']:
        cmd2 += ['-metadata:s:v:' + str(idx), f'title={escape_metadata(video_title)}']
    for idx in streams['audio']:
        cmd2 += ['-metadata:s:a:' + str(idx), f'title={escape_metadata(audio_title)}']
    cmd2 += [output_path]
    try:
        rc2 = await _run_ffmpeg(cmd2, task_id)
        raise_if_cancelled(task_id)
        if rc2 == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            await cleanup_files(input_path)
            return output_path, True
    except TaskCancelled:
        await cleanup_files(output_path)
        raise
    except Exception as e:
        logger.warning(f"FFmpeg metadata level 2 failed: {e}")

    if os.path.exists(output_path):
        await cleanup_files(output_path)
    return input_path, False

async def add_metadata_smart(file_path, user_id, task_id=None):
    return await add_metadata_ffmpeg(file_path, user_id, task_id)

async def do_rename(client, message, user_id, format_template, file_id, file_name, media_type, season, episode, quality):
    download_path = None
    file_path = None
    thumb_path = None
    fallback_thumb = None
    msg = None
    task_id = new_task(user_id)
    set_current(user_id, task_id)
    status = 'failed'

    try:
        format_template = fill_template(format_template, season, episode, quality)

        ext = os.path.splitext(file_name)[1] or '.mkv'
        new_filename = f"{format_template}{ext}"

        unique_id = f"{user_id}_{time.time_ns()}"
        download_path = f"downloads/{unique_id}{ext}"

        os.makedirs("downloads", exist_ok=True)
        os.makedirs("metadata", exist_ok=True)

        msg = await message.reply_text(
            "**Downloading... ⬇️**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄᴀɴᴄᴇʟ •", callback_data=f"cancel_{task_id}")]])
        )

        try:
            file_path = await message.download(
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", msg, time.time(), client, task_id)
            )
        except TypeError:
            file_path = await message.download(file_name=download_path)

        raise_if_cancelled(task_id)   # a stopped download returns None
        await safe_edit(msg, "**Waiting for download to complete... ⏳**")
        file_path = await wait_for_download(file_path, download_path)

        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            await safe_edit(msg, "**Adding metadata... 🔧**")
            try:
                file_path, metadata_added = await add_metadata_smart(file_path, user_id, task_id)
                if not metadata_added:
                    await message.reply_text(
                        "⚠️ **Metadata Notice:**\n"
                        "Could not embed metadata into this file.\n"
                        "File uploaded **without metadata** but fully intact ✅"
                    )
            except TaskCancelled:
                raise
            except Exception as e:
                logger.error(f"Metadata error: {e}")
                await message.reply_text(
                    f"⚠️ **Metadata failed:** `{str(e)}`\n"
                    "Uploading original file without metadata."
                )

        await safe_edit(msg, "**Preparing upload... 📤**")
        caption = build_caption(await codeflixbots.get_caption(user_id), new_filename, file_path)
        thumb_path = await get_user_thumb(client, user_id)  # cached, never deleted here

        if not thumb_path and media_type == "video" and message.video and message.video.thumbs:
            try:
                temp_thumb = await client.download_media(message.video.thumbs[0].file_id)
                thumb_path = await process_thumbnail(temp_thumb)
                fallback_thumb = thumb_path
            except:
                thumb_path = None

        await safe_edit(msg, "**Uploading... ⬆️**")

        upload_params = {
            'chat_id': message.chat.id,
            'caption': caption,
            'thumb': thumb_path,
            'progress': progress_for_pyrogram,
            'progress_args': ("Uploading...", msg, time.time(), client, task_id)
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
        status = 'ok'

        try:
            await msg.delete()
        except:
            pass

    except TaskCancelled:
        status = 'cancelled'
        logger.info(f"Rename cancelled by user {user_id}: {file_name}")
        if msg:
            await safe_edit(msg, f"**❌ Cancelled** `{file_name[:50]}`")
    except Exception as e:
        logger.error(f"Processing error: {e}")
        if msg:
            await safe_edit(msg, f"**❌ Error:** `{str(e)}`")
        else:
            try:
                await message.reply_text(f"**❌ Error:** `{str(e)}`")
            except:
                pass
    finally:
        # Delete BOTH the downloaded file and the metadata-processed copy. Before, the
        # final file was never removed, so downloads/ kept growing until the disk filled.
        await cleanup_files(download_path, file_path)
        set_current(user_id, None)
        drop_task(task_id)
        if fallback_thumb:
            await cleanup_files(fallback_thumb)
    return status

async def process_queue(client, user_id):
    if user_processing.get(user_id, False):
        return
    user_processing[user_id] = True
    stats = {'ok': 0, 'failed': 0, 'cancelled': 0}
    try:
        while user_queues.get(user_id) and not user_cancel.get(user_id, False):
            task = user_queues[user_id].pop(0)
            remaining = len(user_queues.get(user_id, []))
            total_done = task['total'] - remaining
            if task.get('queue_msg'):
                try:
                    await task['queue_msg'].edit(
                        f"**⚙️ Processing file {total_done}/{task['total']}**\n"
                        f"`{task['file_name'][:50]}`"
                    )
                except:
                    pass
            status = await do_rename(
                client, task['message'], user_id,
                task['format_template'], task['file_id'],
                task['file_name'], task['media_type'],
                task['season'], task['episode'], task['quality']
            )
            stats[status if status in stats else 'failed'] += 1
            # Only removed from MongoDB once finished, so a crash/restart while
            # this file is in progress re-runs it instead of losing it.
            await codeflixbots.queue_remove(task.get('db_id'))
        if user_cancel.get(user_id, False):
            remaining = len(user_queues.get(user_id, []))
            user_queues[user_id] = []
            user_cancel[user_id] = False
            await codeflixbots.queue_clear_user(user_id)
            if remaining:
                try:
                    await client.send_message(user_id, f"**✅ Queue cancelled. {remaining} file(s) removed.**")
                except:
                    pass
        else:
            if not user_queues.get(user_id):
                total = sum(stats.values())
                if total == 1 and stats['ok'] == 1:
                    summary = "**✅ All files in queue processed!**"
                else:
                    parts = [f"{stats['ok']} renamed"]
                    if stats['failed']:
                        parts.append(f"{stats['failed']} failed")
                    if stats['cancelled']:
                        parts.append(f"{stats['cancelled']} cancelled")
                    summary = "**✅ Batch finished:** " + ", ".join(parts) + "."
                try:
                    await client.send_message(user_id, summary)
                except:
                    pass
    finally:
        user_processing[user_id] = False

async def restore_queues(client):
    """Called once at startup: reload every pending file from MongoDB and resume."""
    try:
        user_ids = await codeflixbots.queue_users()
    except Exception as e:
        logger.error(f"Could not load persistent queue: {e}")
        return

    for user_id in user_ids:
        if user_queues.get(user_id):
            continue
        docs = await codeflixbots.queue_get_user(user_id)
        tasks = []
        for doc in docs:
            try:
                msg = await client.get_messages(doc['chat_id'], doc['message_id'])
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    msg = await client.get_messages(doc['chat_id'], doc['message_id'])
                except Exception:
                    msg = None
            except Exception as e:
                logger.error(f"Could not fetch queued message {doc['message_id']}: {e}")
                msg = None

            if not msg or getattr(msg, 'empty', False) or not (msg.document or msg.video or msg.audio):
                await codeflixbots.queue_remove(doc['_id'])  # original message is gone
                continue

            tasks.append({
                'message': msg, 'user_id': user_id,
                'format_template': doc['format_template'], 'file_id': doc['file_id'],
                'file_name': doc['file_name'], 'media_type': doc['media_type'],
                'season': doc.get('season'), 'episode': doc.get('episode'),
                'quality': doc.get('quality'), 'queue_msg': None,
                'db_id': doc['_id'],
            })

        if not tasks:
            continue
        for t in tasks:
            t['total'] = len(tasks)
        user_queues[user_id] = tasks
        try:
            await client.send_message(
                user_id,
                f"**♻️ Bot restarted — resuming {len(tasks)} pending file(s) from your queue.**"
            )
        except Exception:
            pass
        asyncio.create_task(process_queue(client, user_id))


async def cancel_everything(user_id):
    """Stop the file in progress, drop everything waiting (rename + auto-post + prompts)."""
    try:
        from plugins.auto_post import cancel_all_posts
        posts = await cancel_all_posts(user_id)
    except Exception as e:
        logger.error(f"Could not cancel auto-post work: {e}")
        posts = 0
    queued = len(user_queues.get(user_id, []))
    processing = user_processing.get(user_id, False)
    prompts = len(pending_backlog.get(user_id, [])) + (1 if user_id in pending_manual_input else 0)

    if queued or processing:
        user_cancel[user_id] = True
    user_queues[user_id] = []
    pending_manual_input.pop(user_id, None)
    pending_backlog.pop(user_id, None)
    await codeflixbots.queue_clear_user(user_id)

    current = False
    tid = current_for(user_id)
    if tid and processing:
        current = request_cancel(tid)   # stops the download/upload/ffmpeg in progress
    return {'queued': queued, 'current': current, 'prompts': prompts, 'posts': posts}


def _queue_view(user_id):
    queue = user_queues.get(user_id, [])
    is_proc = user_processing.get(user_id, False)
    if not queue and not is_proc:
        return "**📋 Your queue is empty.**", None
    text = "**📋 Queue**\n\n"
    text += f"**Working on a file:** {'yes ⚙️' if is_proc else 'no'}\n"
    text += f"**Waiting:** {len(queue)} file(s)\n"
    rows = []
    for i, task in enumerate(queue[:8], 1):
        text += f"`{i}.` {task['file_name'][:45]}\n"
        if task.get('db_id') is not None:
            rows.append([InlineKeyboardButton(f"❌ {i}. {task['file_name'][:35]}", callback_data=f"qc:{task['db_id']}")])
    if len(queue) > 8:
        text += f"_...and {len(queue) - 8} more_\n"
    tid = current_for(user_id)
    controls = []
    if tid and is_proc:
        controls.append(InlineKeyboardButton("⏹ Stop current", callback_data=f"cancel_{tid}"))
    controls.append(InlineKeyboardButton("🗑 Cancel all", callback_data="qca"))
    rows.append(controls)
    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data="qrf")])
    return text, InlineKeyboardMarkup(rows)


@Client.on_message(filters.private & filters.command('queue'))
async def queue_status(client, message):
    text, markup = _queue_view(message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^(qrf|qca|qc:[0-9a-f]{24})$"), group=-1)
async def queue_buttons(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    if data == 'qca':
        await cancel_everything(user_id)
        await callback_query.answer("Queue cancelled")
    elif data.startswith('qc:'):
        db_id = data[3:]
        queue = user_queues.get(user_id, [])
        match = next((t for t in queue if str(t.get('db_id')) == db_id), None)
        if match:
            queue.remove(match)
            await codeflixbots.queue_remove(match['db_id'])
            await callback_query.answer("Removed from the queue")
        else:
            await callback_query.answer("It already started or finished.")
    else:
        await callback_query.answer("Refreshed")
    text, markup = _queue_view(user_id)
    try:
        await callback_query.message.edit_text(text, reply_markup=markup)
    except Exception:
        pass


@Client.on_message(filters.private & filters.command('cancel_queue'))
async def cancel_queue(client, message):
    user_id = message.from_user.id
    r = await cancel_everything(user_id)
    if not (r['queued'] or r['current'] or r['prompts'] or r['posts']):
        return await message.reply_text("**📋 Your queue is already empty.**")
    lines = ["**✅ Queue cancelled!**"]
    if r['queued']:
        lines.append(f"{r['queued']} pending file(s) removed.")
    if r['current']:
        lines.append("The file in progress was stopped.")
    if r['prompts']:
        lines.append(f"{r['prompts']} file(s) waiting for season/episode answers were dropped.")
    if r['posts']:
        lines.append("Auto-post work was cancelled too.")
    await message.reply_text("\n".join(lines))


@Client.on_callback_query(filters.regex(r"^cancel_([0-9a-f]{10})$"), group=-1)
async def cancel_button(client, callback_query):
    task_id = callback_query.matches[0].group(1)
    task = get_task(task_id)
    if not task:
        return await callback_query.answer("That job already finished.", show_alert=False)
    if callback_query.from_user.id != task['user_id'] and not await codeflixbots.is_admin(callback_query.from_user.id):
        return await callback_query.answer("This isn't your job.", show_alert=True)
    request_cancel(task_id)
    await callback_query.answer("Cancelling…")
    try:
        await callback_query.message.edit_text("**❌ Cancelling…**")
    except Exception:
        pass


async def add_to_queue(client, message, user_id, format_template, file_id, file_name, media_type, season, episode, quality):
    if user_id not in user_queues:
        user_queues[user_id] = []
    total = len(user_queues[user_id]) + 1
    for task in user_queues[user_id]:
        task['total'] = total
    queue_msg = await message.reply_text(
        f"**📋 Added to queue!**\n"
        f"Position: `{total}`\n"
        f"File: `{file_name[:50]}`"
    )
    task = {
        'message': message, 'user_id': user_id,
        'format_template': format_template, 'file_id': file_id,
        'file_name': file_name, 'media_type': media_type,
        'season': season, 'episode': episode, 'quality': quality,
        'total': total, 'queue_msg': queue_msg
    }
    task['db_id'] = await codeflixbots.queue_add({
        'user_id': user_id, 'chat_id': message.chat.id,
        'message_id': message.id, 'file_id': file_id,
        'file_name': file_name, 'media_type': media_type,
        'format_template': format_template, 'season': season,
        'episode': episode, 'quality': quality,
    })
    user_queues[user_id].append(task)
    if not user_processing.get(user_id, False):
        asyncio.create_task(process_queue(client, user_id))

@Client.on_message(filters.private & filters.text & ~filters.regex(r"^/"))
async def handle_manual_input(client, message):
    user_id = message.from_user.id
    if user_id not in pending_manual_input:
        return
    pending = pending_manual_input[user_id]
    field = pending['field']
    data = pending['data']
    user_input = message.text.strip()

    if field == 'episode':
        if user_input.lower() != 'skip':
            data['episode'] = user_input
        if not data.get('season'):
            pending_manual_input[user_id] = {'field': 'season', 'data': data}
            return await message.reply_text(
                "**Could not detect Season.**\nType season number or `skip`:"
            )
        if not data.get('quality'):
            pending_manual_input[user_id] = {'field': 'quality', 'data': data}
            return await message.reply_text(
                "**Could not detect Quality.**\nType quality e.g. `720p` or `skip`:"
            )
    elif field == 'season':
        if user_input.lower() != 'skip':
            data['season'] = user_input
        if not data.get('quality'):
            pending_manual_input[user_id] = {'field': 'quality', 'data': data}
            return await message.reply_text(
                "**Could not detect Quality.**\nType quality e.g. `720p` or `skip`:"
            )
    elif field == 'quality':
        if user_input.lower() != 'skip':
            data['quality'] = user_input

    del pending_manual_input[user_id]
    await add_to_queue(
        client, data['message'], data['user_id'],
        data['format_template'], data['file_id'],
        data['file_name'], data['media_type'],
        data.get('season'), data.get('episode'), data.get('quality')
    )
    await _prompt_next(user_id)


async def _ask_missing(user_id, data):
    missing = [f for f in ('episode', 'season', 'quality') if not data.get(f)]
    pending_manual_input[user_id] = {'field': missing[0], 'data': data}
    await data['message'].reply_text(
        f"**⚠️ Could not detect {FIELD_NAMES[missing[0]]}** for\n"
        f"`{data['file_name'][:60]}`\n"
        f"Please type it (or type `skip`):"
    )


async def _prompt_next(user_id):
    backlog = pending_backlog.get(user_id)
    if not backlog:
        pending_backlog.pop(user_id, None)
        return
    data = backlog.pop(0)
    if not backlog:
        pending_backlog.pop(user_id, None)
    await _ask_missing(user_id, data)

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    user_id = message.from_user.id

    from helper.session_state import auto_post_sessions
    if user_id in auto_post_sessions:
        return

    format_template = await codeflixbots.get_format_template(user_id)
    if not format_template:
        return await message.reply_text(
            "**Please set a rename format using /autorename**"
        )

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

    if await check_anti_nsfw(file_name, message):
        return

    caption_text = message.caption or ""
    combined = f"{file_name} {caption_text}"

    season, episode = extract_season_episode(combined)
    quality = extract_quality(combined)

    if not season and re.search(r'\[SO\]', combined, re.IGNORECASE):
        season = "1"

    if not (episode and season and quality):
        data = {
            'message': message, 'user_id': user_id,
            'format_template': format_template,
            'file_id': file_id, 'file_name': file_name,
            'media_type': media_type, 'season': season,
            'episode': episode, 'quality': quality
        }
        if user_id in pending_manual_input:
            # Previously this overwrote the pending prompt and the earlier file vanished silently.
            pending_backlog.setdefault(user_id, []).append(data)
            await message.reply_text(
                f"**⏳ Waiting list:** `{file_name[:50]}`\n"
                "I'll ask about this one after the current prompt."
            )
        else:
            await _ask_missing(user_id, data)
        return

    await add_to_queue(
        client, message, user_id, format_template,
        file_id, file_name, media_type,
        season, episode, quality
    )
