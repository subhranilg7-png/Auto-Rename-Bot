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
from config import Config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ── Queue system ───────────────────────────────────────────────────────────────
user_queues = {}
user_processing = {}
user_cancel = {}

# Pending manual input store
pending_manual_input = {}

# Create required directories on startup
os.makedirs("downloads", exist_ok=True)
os.makedirs("metadata", exist_ok=True)

# ── Regex patterns ─────────────────────────────────────────────────────────────

SEASON_EPISODE_PATTERNS = [
    (re.compile(r'S(\d+)\s*-\s*(\d+)', re.IGNORECASE), ('season', 'episode')),               # S1 - 01
    (re.compile(r'\[(\d+)\s*-', re.IGNORECASE), (None, 'episode')),                           # [04 - Title]
    (re.compile(r'\[E(\d+)\s*-', re.IGNORECASE), (None, 'episode')),                          # [E04 - Title]
    (re.compile(r'\[S(\d+)[\s-]+(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)', re.IGNORECASE), ('season', None)),                         # Season 2 (standalone)
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

# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_season_episode(text):
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

def extract_quality(text):
    if not text:
        return None
    for pattern, extractor in QUALITY_PATTERNS:
        match = pattern.search(text)
        if match:
            return extractor(match)
    return None

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
    await asyncio.sleep(1)
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
            img = img.convert("RGB").resize((320, 320))
            img.save(thumb_path, "JPEG")
        return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail processing failed: {e}")
        await cleanup_files(thumb_path)
        return None

def escape_metadata(text):
    return str(text).replace('"', '\\"').replace("'", "\\'")

# ── Stream probing helper ───────────────────────────────────────────────────

async def probe_streams(input_path):
    """Returns dict {'video': [idx,...], 'audio': [idx,...], 'subtitle': [idx,...]}
    where idx is the stream's index *within its own type* (0-based),
    matching how ffmpeg's -metadata:s:TYPE:N option addresses streams."""
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
            result[key].append(len(result[key]))  # 0-based index within its type

    return result

# ── FFmpeg metadata (single path for all containers) ───────────────────────

async def add_metadata_ffmpeg(input_path, user_id):
    """3-level FFmpeg fallback. Applies title metadata to every audio and
    subtitle stream individually, not just the first one of each type."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return input_path, False

    if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
        raise RuntimeError("Input file missing or empty")

    ext = os.path.splitext(input_path)[1]
    output_path = input_path.replace(ext, f"_meta{ext}")

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

    # Level 1 — full stream copy, per-track metadata on every track
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
        p = await asyncio.wait_for(
            asyncio.create_subprocess_exec(*cmd1, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE),
            timeout=180
        )
        await p.communicate()
        if p.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            await cleanup_files(input_path)
            return output_path, True
    except Exception as e:
        logger.warning(f"FFmpeg metadata level 1 failed: {e}")

    # Level 2 — no subtitle stream copy (some containers choke on -c:s copy)
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
        p2 = await asyncio.wait_for(
            asyncio.create_subprocess_exec(*cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE),
            timeout=180
        )
        await p2.communicate()
        if p2.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            await cleanup_files(input_path)
            return output_path, True
    except Exception as e:
        logger.warning(f"FFmpeg metadata level 2 failed: {e}")

    # Level 3 — no metadata
    if os.path.exists(output_path):
        await cleanup_files(output_path)
    return input_path, False

# ── Smart metadata router ──────────────────────────────────────────────────────

async def add_metadata_smart(file_path, user_id):
    return await add_metadata_ffmpeg(file_path, user_id)

# ── Core rename + upload logic ─────────────────────────────────────────────────

async def do_rename(client, message, user_id, format_template, file_id, file_name, media_type, season, episode, quality):
    download_path = None
    thumb_path = None
    thumb = None
    msg = None

    try:
        replacements = {
            '{season}': str(season) if season else 'XX',
            '{episode}': str(episode) if episode else 'XX',
            '{quality}': str(quality) if quality else 'Unknown',
            'Season': str(season) if season else 'XX',
            'Episode': str(episode) if episode else 'XX',
            'QUALITY': str(quality) if quality else 'Unknown'
        }
        for placeholder, value in replacements.items():
            format_template = format_template.replace(placeholder, value)

        ext = os.path.splitext(file_name)[1] or '.mkv'
        new_filename = f"{format_template}{ext}"

        unique_id = f"{user_id}_{int(time.time())}"
        download_path = f"downloads/{unique_id}{ext}"

        os.makedirs("downloads", exist_ok=True)
        os.makedirs("metadata", exist_ok=True)

        msg = await message.reply_text("**Downloading... ⬇️**")

        # Use message.download() — more reliable for forwarded files
        try:
            file_path = await message.download(
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", msg, time.time())
            )
        except TypeError:
            # Fallback if progress args not supported
            file_path = await message.download(file_name=download_path)

        await safe_edit(msg, "**Waiting for download to complete... ⏳**")
        file_path = await wait_for_download(file_path, download_path)

        # Metadata
        metadata_enabled = await codeflixbots.get_metadata(user_id)
        if metadata_enabled == "On":
            await safe_edit(msg, "**Adding metadata... 🔧**")
            try:
                file_path, metadata_added = await add_metadata_smart(file_path, user_id)
                if not metadata_added:
                    await message.reply_text(
                        "⚠️ **Metadata Notice:**\n"
                        "Could not embed metadata into this file.\n"
                        "File uploaded **without metadata** but fully intact ✅"
                    )
            except Exception as e:
                logger.error(f"Metadata error: {e}")
                await message.reply_text(
                    f"⚠️ **Metadata failed:** `{str(e)}`\n"
                    "Uploading original file without metadata."
                )

        await safe_edit(msg, "**Preparing upload... 📤**")
        caption = await codeflixbots.get_caption(user_id) or f"**{new_filename}**"
        thumb = await codeflixbots.get_thumbnail(user_id)

        if thumb and os.path.exists(thumb):
            thumb_path = thumb
        elif media_type == "video" and message.video and message.video.thumbs:
            try:
                thumb_path = await client.download_media(message.video.thumbs[0].file_id)
                thumb_path = await process_thumbnail(thumb_path)
            except:
                thumb_path = None

        await safe_edit(msg, "**Uploading... ⬆️**")

        upload_params = {
            'chat_id': message.chat.id,
            'caption': caption,
            'thumb': thumb_path,
            'progress': progress_for_pyrogram,
            'progress_args': ("Uploading...", msg, time.time())
        }

        if media_type == "document":
            await client.send_document(document=file_path, file_name=new_filename, **upload_params)
        elif media_type == "video":
            await client.send_video(video=file_path, **upload_params)
        elif media_type == "audio":
            await client.send_audio(audio=file_path, file_name=new_filename, **upload_params)

        try:
            await msg.delete()
        except:
            pass

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
        if download_path and download_path != (locals().get('file_path') or ''):
            await cleanup_files(download_path)
        if thumb_path and thumb_path != thumb:
            await cleanup_files(thumb_path)

# ── Queue processor ────────────────────────────────────────────────────────────

async def process_queue(client, user_id):
    if user_processing.get(user_id, False):
        return
    user_processing[user_id] = True
    try:
        while user_queues.get(user_id) and not user_cancel.get(user_id, False):
            task = user_queues[user_id].pop(0)
            remaining = len(user_queues.get(user_id, []))
            total_done = task['total'] - remaining
            try:
                await task['queue_msg'].edit(
                    f"**⚙️ Processing file {total_done}/{task['total']}**\n"
                    f"`{task['file_name'][:50]}`"
                )
            except:
                pass
            await do_rename(
                client, task['message'], user_id,
                task['format_template'], task['file_id'],
                task['file_name'], task['media_type'],
                task['season'], task['episode'], task['quality']
            )
        if user_cancel.get(user_id, False):
            remaining = len(user_queues.get(user_id, []))
            user_queues[user_id] = []
            user_cancel[user_id] = False
            try:
                await client.send_message(user_id, f"**✅ Queue cancelled. {remaining} file(s) removed.**")
            except:
                pass
        else:
            if not user_queues.get(user_id):
                try:
                    await client.send_message(user_id, "**✅ All files in queue processed!**")
                except:
                    pass
    finally:
        user_processing[user_id] = False

# ── Queue commands ─────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('queue'))
async def queue_status(client, message):
    user_id = message.from_user.id
    queue = user_queues.get(user_id, [])
    is_proc = user_processing.get(user_id, False)
    if not queue and not is_proc:
        return await message.reply_text("**📋 Your queue is empty.**")
    text = "**📋 Queue Status**\n\n"
    text += f"**Processing:** {'Yes ⚙️' if is_proc else 'No'}\n"
    text += f"**Pending:** {len(queue)} file(s)\n\n"
    if queue:
        text += "**Pending files:**\n"
        for i, task in enumerate(queue[:10], 1):
            text += f"`{i}.` {task['file_name'][:45]}\n"
        if len(queue) > 10:
            text += f"_...and {len(queue) - 10} more_"
    await message.reply_text(text)


@Client.on_message(filters.private & filters.command('cancel_queue'))
async def cancel_queue(client, message):
    user_id = message.from_user.id
    queue = user_queues.get(user_id, [])
    count = len(queue)
    if not queue and not user_processing.get(user_id, False):
        return await message.reply_text("**📋 Your queue is already empty.**")
    user_cancel[user_id] = True
    user_queues[user_id] = []
    await message.reply_text(f"**✅ Queue cancelled!**\n{count} pending file(s) removed.")

# ── Add to queue helper ────────────────────────────────────────────────────────

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
    user_queues[user_id].append(task)
    if not user_processing.get(user_id, False):
        asyncio.create_task(process_queue(client, user_id))

# ── Manual input handler ───────────────────────────────────────────────────────

@Client.on_message(
    filters.private & filters.text & ~filters.command(
        ['start', 'autorename', 'set_caption', 'del_caption', 'see_caption',
         'view_thumb', 'viewthumb', 'del_thumb', 'delthumb', 'metadata',
         'settitle', 'setauthor', 'setartist', 'setaudio', 'setsubtitle',
         'setvideo', 'help', 'commands', 'donate', 'premium', 'plan',
         'queue', 'cancel_queue', 'setmedia', 'restart', 'stats',
         'broadcast', 'tutorial']
    )
)
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
 
# ── Main file handler ──────────────────────────────────────────────────────────

 @Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    user_id = message.from_user.id
 
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
 
    # If [SO] tag is present and no season detected, default to season 1
    if not season and re.search(r'\[SO\]', combined, re.IGNORECASE):
        season = "1"
 
    missing = []
    if not episode:
        missing.append('episode')
    if not season:
        missing.append('season')
    if not quality:
        missing.append('quality')
 
    if missing:
        pending_manual_input[user_id] = {
            'field': missing[0],
            'data': {
                'message': message, 'user_id': user_id,
                'format_template': format_template,
                'file_id': file_id, 'file_name': file_name,
                'media_type': media_type, 'season': season,
                'episode': episode, 'quality': quality
            }
        }
        field_names = {
            'episode': 'Episode number',
            'season': 'Season number',
            'quality': 'Quality (e.g. 720p)'
        }
        await message.reply_text(
            f"**⚠️ Could not detect {field_names[missing[0]]}.**\n"
            f"Please type it (or type `skip`):"
        )
        return
 
    await add_to_queue(
        client, message, user_id, format_template,
        file_id, file_name, media_type,
        season, episode, quality
    )
 
