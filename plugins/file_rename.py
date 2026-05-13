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

# Pending manual input
pending_manual_input = {}

# Create required directories on startup
os.makedirs("downloads", exist_ok=True)
os.makedirs("metadata", exist_ok=True)

# ── Regex patterns ─────────────────────────────────────────────────────────────

SEASON_EPISODE_PATTERNS = [
    (re.compile(r'\[E(\d+)\s*-', re.IGNORECASE), (None, 'episode')),
    (re.compile(r'\[S(\d+)[\s-]+(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
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

def sanitize_filename(filename):
    sanitized = re.sub(r'[<>:"/\\|?*@#$%^&]', '_', filename)
    sanitized = re.sub(r'\s+', ' ', sanitized)
    return sanitized.strip()

async def safe_edit(msg, text):
    """Edit message ignoring MESSAGE_NOT_MODIFIED errors"""
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
    """Wait for Pyrogram .temp file to finish downloading"""
    temp_path = f"{file_path}.temp" if file_path else f"{download_path}.temp"
    waited = 0
    while waited < timeout:
        if not os.path.exists(temp_path):
            break
        await asyncio.sleep(2)
        waited += 2

    if os.path.exists(temp_path):
        raise Exception(f"Download timed out after {timeout}s — file still incomplete")

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

async def add_metadata(input_path, output_path, user_id):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError("FFmpeg not found in PATH")

    if not os.path.exists(input_path):
        raise RuntimeError(f"Input file not found: {input_path}")
    if os.path.getsize(input_path) == 0:
        raise RuntimeError("Input file is empty")

    metadata = {
        'title': await codeflixbots.get_title(user_id),
        'artist': await codeflixbots.get_artist(user_id),
        'author': await codeflixbots.get_author(user_id),
        'video_title': await codeflixbots.get_video(user_id),
        'audio_title': await codeflixbots.get_audio(user_id),
        'subtitle': await codeflixbots.get_subtitle(user_id)
    }

    cmd = [
        ffmpeg, '-y',
        '-i', input_path,
        '-metadata', f'title={metadata["title"]}',
        '-metadata', f'artist={metadata["artist"]}',
        '-metadata', f'author={metadata["author"]}',
        '-metadata:s:v', f'title={metadata["video_title"]}',
        '-metadata:s:a', f'title={metadata["audio_title"]}',
        '-metadata:s:s', f'title={metadata["subtitle"]}',
        '-map', '0',
        '-c', 'copy',
        '-loglevel', 'error',
        output_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {stderr.decode()}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("FFmpeg output file is missing or empty")

async def do_rename(client, message, user_id, format_template, file_id, file_name, media_type, season, episode, quality):
    download_path = None
    metadata_path = None
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

        ext = os.path.splitext(file_name)[1] or ('.mp4' if media_type == 'video' else '.mp3')
        new_filename = f"{format_template}{ext}"

        # Use unique ID path — avoids all special char issues
        unique_id = f"{user_id}_{int(time.time())}"
        download_path = f"downloads/{unique_id}{ext}"
        metadata_path = f"metadata/{unique_id}{ext}"

        os.makedirs("downloads", exist_ok=True)
        os.makedirs("metadata", exist_ok=True)

        msg = await message.reply_text("**Downloading... ⬇️**")

        file_path = await client.download_media(
            message,
            file_name=download_path,
            progress=progress_for_pyrogram,
            progress_args=("Downloading...", msg, time.time())
        )

        # Wait for download to fully complete
        await safe_edit(msg, "**Waiting for download to complete... ⏳**")
        file_path = await wait_for_download(file_path, download_path)

        # Process metadata — stops and tells user if it fails
        await safe_edit(msg, "**Processing metadata... 🔧**")
        try:
            await add_metadata(file_path, metadata_path, user_id)
            file_path = metadata_path
        except Exception as e:
            logger.error(f"Metadata failed: {e}")
            await safe_edit(
                msg,
                f"**❌ Metadata processing failed:**\n`{str(e)}`\n\nPlease try again."
            )
            return

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
        await cleanup_files(download_path, metadata_path)
        if thumb_path and thumb_path != thumb:
            await cleanup_files(thumb_path)
        try:
            await codeflixbots.clear_processing(file_id)
        except:
            pass


# ── Manual input handler ───────────────────────────────────────────────────────

@Client.on_message(
    filters.private & filters.text & ~filters.command(
        ['start', 'autorename', 'set_caption', 'del_caption', 'see_caption',
         'view_thumb', 'viewthumb', 'del_thumb', 'delthumb', 'bot_mode',
         'sequence_mode', 'start_sequence', 'end_sequence', 'metadata',
         'settitle', 'setauthor', 'setartist', 'setaudio', 'setsubtitle',
         'setvideo', 'help', 'commands', 'donate', 'premium', 'plan']
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

    await do_rename(
        client, data['message'], user_id,
        data['format_template'], data['file_id'],
        data['file_name'], data['media_type'],
        data.get('season'), data.get('episode'), data.get('quality')
    )


# ── Main file handler (group=0, higher priority than sequence.py group=1) ──────

@Client.on_message(
    filters.private & (filters.document | filters.video | filters.audio),
    group=0
)
async def auto_rename_files(client, message):
    user_id = message.from_user.id

    # If sequence mode — let sequence.py handle it
    bot_mode_val = await codeflixbots.get_bot_mode(user_id)
    if bot_mode_val == 'sequence':
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
        return await message.reply_text("NSFW content detected")

    # DB-backed dedup to survive restarts
    if await codeflixbots.is_processing(file_id):
        logger.info(f"Skipping duplicate: {file_id}")
        return
    await codeflixbots.set_processing(file_id)

    caption_text = message.caption or ""
    combined = f"{file_name} {caption_text}"

    season, episode = extract_season_episode(combined)
    quality = extract_quality(combined)

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
                'message': message,
                'format_template': format_template,
                'file_id': file_id,
                'file_name': file_name,
                'media_type': media_type,
                'season': season,
                'episode': episode,
                'quality': quality
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

    await do_rename(
        client, message, user_id, format_template,
        file_id, file_name, media_type,
        season, episode, quality
)
