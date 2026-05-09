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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global dictionary to track ongoing operations
renaming_operations = {}

# Pending manual input store
pending_manual_input = {}

# Create required directories on startup
os.makedirs("downloads", exist_ok=True)
os.makedirs("metadata", exist_ok=True)

# ── Regex patterns ─────────────────────────────────────────────────────────────

SEASON_EPISODE_PATTERNS = [
    # [E06 - Title] style — episode first before dash
    (re.compile(r'\[E(\d+)\s*-', re.IGNORECASE), (None, 'episode')),
    # [S01-04] style
    (re.compile(r'\[S(\d+)[\s-]+(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    # S01E02 or S01EP02
    (re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    # S01 E02 or S01-EP02
    (re.compile(r'S(\d+)[\s-]*(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    # Season 1 Episode 2
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    # [S01][E02] or [S01][E02]
    (re.compile(r'\[S(\d+)\]\s*\[?E(\d+)\]?', re.IGNORECASE), ('season', 'episode')),
    # [S01] alone
    (re.compile(r'\[S(\d+)\]', re.IGNORECASE), ('season', None)),
    # S01 alone
    (re.compile(r'\bS(\d+)\b', re.IGNORECASE), ('season', None)),
    # E06 or EP06 alone
    (re.compile(r'(?:^|[\s\[\-_])(?:E|EP)(\d+)(?:$|[\s\]\-_])', re.IGNORECASE), (None, 'episode')),
    # Episode 06
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

# ── Helper functions ───────────────────────────────────────────────────────────

def extract_season_episode(text):
    """Extract season and episode from combined filename + caption.
    Runs all patterns to find both season and episode separately."""
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

    logger.info(f"Detected season={season_found}, episode={episode_found} from: {text[:80]}")
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
    """Remove special characters that cause filesystem issues"""
    sanitized = re.sub(r'[<>:"/\\|?*@#$%^&]', '_', filename)
    sanitized = re.sub(r'\s+', ' ', sanitized)
    sanitized = sanitized.strip()
    return sanitized

async def cleanup_files(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.error(f"Error removing {path}: {e}")

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

    metadata = {
        'title': await codeflixbots.get_title(user_id),
        'artist': await codeflixbots.get_artist(user_id),
        'author': await codeflixbots.get_author(user_id),
        'video_title': await codeflixbots.get_video(user_id),
        'audio_title': await codeflixbots.get_audio(user_id),
        'subtitle': await codeflixbots.get_subtitle(user_id)
    }

    cmd = [
        ffmpeg,
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

async def do_rename(client, message, user_id, format_template, file_id, file_name, media_type, season, episode, quality):
    """Core rename + upload logic"""
    download_path = None
    metadata_path = None
    thumb_path = None
    thumb = None
    msg = None

    try:
        replacements = {
            '{season}': season or 'XX',
            '{episode}': episode or 'XX',
            '{quality}': quality or 'Unknown',
            'Season': season or 'XX',
            'Episode': episode or 'XX',
            'QUALITY': quality or 'Unknown'
        }
        for placeholder, value in replacements.items():
            format_template = format_template.replace(placeholder, str(value))

        ext = os.path.splitext(file_name)[1] or ('.mp4' if media_type == 'video' else '.mp3')
        new_filename = f"{format_template}{ext}"

        # Use unique ID for download path to avoid special char issues
        unique_id = f"{user_id}_{int(time.time())}"
        download_path = f"downloads/{unique_id}{ext}"
        metadata_path = f"metadata/{unique_id}{ext}"

        os.makedirs("downloads", exist_ok=True)
        os.makedirs("metadata", exist_ok=True)

        msg = await message.reply_text("**Downloading...**")
        try:
            file_path = await client.download_media(
                message,
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", msg, time.time())
            )

            # Wait for .temp file to finish
            temp_path = f"{file_path}.temp" if file_path else f"{download_path}.temp"
            wait_count = 0
            while os.path.exists(temp_path) and wait_count < 60:
                await asyncio.sleep(1)
                wait_count += 1

            if os.path.exists(temp_path):
                raise Exception("Download timed out — file still incomplete after 60s")

            await asyncio.sleep(1)

            if not file_path or not os.path.exists(file_path):
                raise Exception("Download incomplete — file not found")

            if os.path.getsize(file_path) == 0:
                raise Exception("Download incomplete — file is empty")

        except Exception as e:
            if msg:
                try:
                    await msg.edit(f"Download failed: {e}")
                except:
                    pass
            raise

        try:
            await msg.edit("**Processing metadata...**")
        except:
            pass
        try:
            await add_metadata(file_path, metadata_path, user_id)
            file_path = metadata_path
        except Exception as e:
            if msg:
                try:
                    await msg.edit(f"Metadata processing failed: {e}")
                except:
                    pass
            raise

        try:
            await msg.edit("**Preparing upload...**")
        except:
            pass

        caption = await codeflixbots.get_caption(user_id) or f"**{new_filename}**"
        thumb = await codeflixbots.get_thumbnail(user_id)

        if thumb and os.path.exists(thumb):
            thumb_path = thumb
        elif media_type == "video" and message.video and message.video.thumbs:
            thumb_path = await client.download_media(message.video.thumbs[0].file_id)
            thumb_path = await process_thumbnail(thumb_path)

        try:
            await msg.edit("**Uploading...**")
        except:
            pass

        try:
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
            if msg:
                try:
                    await msg.edit(f"Upload failed: {e}")
                except:
                    pass
            raise

    except Exception as e:
        logger.error(f"Processing error: {e}")
        if msg:
            try:
                await msg.edit(f"Error: {str(e)}")
            except:
                await message.reply_text(f"Error: {str(e)}")
    finally:
        await cleanup_files(download_path, metadata_path)
        if thumb_path and thumb_path != thumb:
            await cleanup_files(thumb_path)


# ── Manual input handler ───────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.text & ~filters.command(
    ['start', 'autorename', 'set_caption', 'del_caption', 'see_caption',
     'view_thumb', 'viewthumb', 'del_thumb', 'delthumb', 'bot_mode',
     'sequence_mode', 'start_sequence', 'end_sequence', 'metadata',
     'settitle', 'setauthor', 'setartist', 'setaudio', 'setsubtitle',
     'setvideo', 'help', 'start', 'commands', 'donate', 'premium', 'plan']
))
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
            await message.reply_text(
                "**Could not detect Season number.**\n"
                "Please type the season number (or type `skip`):"
            )
            return
        if not data.get('quality'):
            pending_manual_input[user_id] = {'field': 'quality', 'data': data}
            await message.reply_text(
                "**Could not detect Quality.**\n"
                "Please type quality e.g. `720p`, `1080p` (or type `skip`):"
            )
            return

    elif field == 'season':
        if user_input.lower() != 'skip':
            data['season'] = user_input
        if not data.get('quality'):
            pending_manual_input[user_id] = {'field': 'quality', 'data': data}
            await message.reply_text(
                "**Could not detect Quality.**\n"
                "Please type quality e.g. `720p`, `1080p` (or type `skip`):"
            )
            return

    elif field == 'quality':
        if user_input.lower() != 'skip':
            data['quality'] = user_input

    del pending_manual_input[user_id]

    await do_rename(
        client,
        data['message'],
        user_id,
        data['format_template'],
        data['file_id'],
        data['file_name'],
        data['media_type'],
        data.get('season'),
        data.get('episode'),
        data.get('quality')
    )


# ── Main file handler ──────────────────────────────────────────────────────────

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def auto_rename_files(client, message):
    user_id = message.from_user.id

    # If sequence mode let sequence.py handle it
    bot_mode = await codeflixbots.get_bot_mode(user_id)
    if bot_mode == 'sequence':
        return

    format_template = await codeflixbots.get_format_template(user_id)
    if not format_template:
        return await message.reply_text("Please set a rename format using /autorename")

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
        return await message.reply_text("Unsupported file type")

    if await check_anti_nsfw(file_name, message):
        return await message.reply_text("NSFW content detected")

    if file_id in renaming_operations:
        if (datetime.now() - renaming_operations[file_id]).seconds < 10:
            return
    renaming_operations[file_id] = datetime.now()

    # Combine filename + caption for better detection
    caption_text = message.caption or ""
    combined = f"{file_name} {caption_text}"

    season, episode = extract_season_episode(combined)
    quality = extract_quality(combined)

    # Ask user to fill in missing fields
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
            f"Please type it manually (or type `skip` to skip):"
        )
        renaming_operations.pop(file_id, None)
        return

    await do_rename(
        client, message, user_id, format_template,
        file_id, file_name, media_type,
        season, episode, quality
    )
    renaming_operations.pop(file_id, None)
