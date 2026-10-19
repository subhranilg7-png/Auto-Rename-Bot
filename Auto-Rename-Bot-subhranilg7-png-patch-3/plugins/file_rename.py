import os
import re
import time
import shutil
import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace
from PIL import Image
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from plugins.antinsfw import check_anti_nsfw
from helper.utils import progress_for_pyrogram, humanbytes, convert
from helper.database import codeflixbots
from helper.thumbs import make_square_thumb, get_user_thumb_path
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
user_last_add = {}      # user_id -> time the last file was queued (used to batch a burst of forwards)

COLLECT_QUIET = 2.5     # seconds without a new file before a batch starts processing
COLLECT_MAX = 12        # never wait longer than this for a batch to settle
MAX_ATTEMPTS = 2        # a file that was started this many times and still didn't finish is dropped

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
    """Exact-centre 1:1 crop (pixel logic) + high quality JPEG, in place."""
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    try:
        make_square_thumb(thumb_path, thumb_path)
        return thumb_path
    except Exception as e:
        logger.error(f"Thumbnail processing failed: {e}")
        await cleanup_files(thumb_path)
        return None

def escape_metadata(text):
    return str(text).replace('"', '\\"').replace("'", "\\'")

# ── MKV metadata using mkvpropedit ────────────────────────────────────────────

async def add_metadata_mkv(file_path, user_id):
    """Uses mkvpropedit for MKV — edits in-place, zero corruption risk"""
    mkvpropedit = shutil.which('mkvpropedit')
    if not mkvpropedit:
        logger.warning("mkvpropedit not found — falling back to FFmpeg")
        return await add_metadata_ffmpeg(file_path, user_id)

    title = await codeflixbots.get_title(user_id)
    video_title = await codeflixbots.get_video(user_id)
    audio_title = await codeflixbots.get_audio(user_id)
    subtitle_title = await codeflixbots.get_subtitle(user_id)

    # Try with subtitle track first
    cmd = [
        mkvpropedit, file_path,
        '--edit', 'info',
        '--set', f'title={title}',
        '--edit', 'track:v1',
        '--set', f'name={video_title}',
        '--edit', 'track:a1',
        '--set', f'name={audio_title}',
        '--edit', 'track:s1',
        '--set', f'name={subtitle_title}',
    ]
    try:
        process = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            ),
            timeout=60
        )
        _, stderr = await process.communicate()
        if process.returncode == 0:
            logger.info("MKV metadata added via mkvpropedit")
            return file_path, True
    except asyncio.TimeoutError:
        logger.warning("mkvpropedit timed out")
    except Exception as e:
        logger.warning(f"mkvpropedit error: {e}")

    # Retry without subtitle track
    cmd_no_sub = [
        mkvpropedit, file_path,
        '--edit', 'info',
        '--set', f'title={title}',
        '--edit', 'track:v1',
        '--set', f'name={video_title}',
        '--edit', 'track:a1',
        '--set', f'name={audio_title}',
    ]
    try:
        process2 = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd_no_sub,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            ),
            timeout=60
        )
        _, stderr2 = await process2.communicate()
        if process2.returncode == 0:
            logger.info("MKV metadata added (no subtitle track)")
            return file_path, True
    except Exception as e:
        logger.warning(f"mkvpropedit retry failed: {e}")

    return file_path, False

# ── FFmpeg fallback for non-MKV ───────────────────────────────────────────────

async def add_metadata_ffmpeg(input_path, user_id):
    """3-level FFmpeg fallback"""
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

    # Level 1
    cmd1 = [
        ffmpeg, '-y', '-i', input_path,
        '-map', '0', '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'copy',
        '-metadata', f'title={escape_metadata(title)}',
        '-metadata', f'artist={escape_metadata(artist)}',
        '-metadata', f'author={escape_metadata(author)}',
        '-metadata:s:v', f'title={escape_metadata(video_title)}',
        '-metadata:s:a', f'title={escape_metadata(audio_title)}',
        '-metadata:s:s', f'title={escape_metadata(subtitle_title)}',
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
    except:
        pass

    # Level 2
    if os.path.exists(output_path):
        await cleanup_files(output_path)
    cmd2 = [
        ffmpeg, '-y', '-i', input_path,
        '-map', '0', '-c', 'copy',
        '-metadata', f'title={escape_metadata(title)}',
        output_path
    ]
    try:
        p2 = await asyncio.wait_for(
            asyncio.create_subprocess_exec(*cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE),
            timeout=180
        )
        await p2.communicate()
        if p2.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            await cleanup_files(input_path)
            return output_path, True
    except:
        pass

    # Level 3 — no metadata
    if os.path.exists(output_path):
        await cleanup_files(output_path)
    return input_path, False

# ── Smart metadata router ──────────────────────────────────────────────────────

async def add_metadata_smart(file_path, user_id):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.mkv':
        return await add_metadata_mkv(file_path, user_id)
    else:
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
        # Cached 1:1 thumbnail; rebuilt from the file_id saved in MongoDB if the disk was wiped
        thumb = await get_user_thumb_path(client, user_id)

        if thumb:
            thumb_path = thumb
        elif media_type == "video" and message.video and message.video.thumbs:
            try:
                best = max(message.video.thumbs, key=lambda t: (t.width or 0) * (t.height or 0))
                thumb_path = await client.download_media(best.file_id)
                thumb_path = await process_thumbnail(thumb_path)
            except Exception:
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

# ── Persistent queue helpers ───────────────────────────────────────────────────
# Every queued file is also stored in MongoDB (collection `rename_queue`) and removed
# again as soon as that file is finished, so a restart can pick up where it stopped.

class ResumedMessage:
    """Stand-in for a Telegram message that can't be re-fetched after a restart."""
    video = None

    def __init__(self, client, chat_id, record):
        self._client = client
        self._file_id = record['file_id']
        self.id = record['message_id']
        self.chat = SimpleNamespace(id=chat_id)
        self.from_user = SimpleNamespace(id=chat_id)

    async def reply_text(self, text, **kwargs):
        return await self._client.send_message(self.chat.id, text, **kwargs)

    async def download(self, file_name=None, progress=None, progress_args=()):
        return await self._client.download_media(
            self._file_id, file_name=file_name, progress=progress, progress_args=progress_args
        )


async def resolve_messages(client, chat_id, records):
    """Re-fetch the original messages (one bulk request per 100 ids); fall back to a stand-in."""
    found = {}
    ids = [r['message_id'] for r in records]
    for i in range(0, len(ids), 100):
        try:
            msgs = await client.get_messages(chat_id, ids[i:i + 100])
            if not isinstance(msgs, list):
                msgs = [msgs]
            for m in msgs:
                if m and not getattr(m, 'empty', False) and (m.document or m.video or m.audio):
                    found[m.id] = m
        except Exception as e:
            logger.warning(f"Could not re-fetch messages for {chat_id}: {e}")
    return [found.get(r['message_id']) or ResumedMessage(client, chat_id, r) for r in records]


def cleanup_stale_downloads():
    """Called once at startup, when nothing is running: partial downloads are leftovers."""
    removed = 0
    try:
        for name in os.listdir("downloads"):
            path = os.path.join("downloads", name)
            if os.path.isfile(path) and re.match(r'^\d+_\d+', name):
                os.remove(path)
                removed += 1
    except Exception as e:
        logger.warning(f"Stale download cleanup failed: {e}")
    if removed:
        logger.info(f"Removed {removed} leftover partial download(s)")


def _task_from_record(record, message, queue_msg):
    return {
        'task_id': record['_id'], 'message': message, 'user_id': record['user_id'],
        'msg_id': record['message_id'],
        'format_template': record['format_template'], 'file_id': record['file_id'],
        'file_name': record['file_name'], 'media_type': record['media_type'],
        'season': record.get('season'), 'episode': record.get('episode'),
        'quality': record.get('quality'), 'queue_msg': queue_msg,
    }


async def resume_queues(client):
    """Run once after the bot has started: reload every unfinished file from MongoDB."""
    cleanup_stale_downloads()
    records = await codeflixbots.get_pending_tasks()
    if not records:
        return
    by_user = {}
    for r in records:
        by_user.setdefault(r['user_id'], []).append(r)
    for user_id, recs in by_user.items():
        try:
            await _resume_user(client, user_id, recs)
        except Exception as e:
            logger.error(f"Could not resume queue of user {user_id}: {e}")


async def _resume_user(client, user_id, recs):
    keep, dropped = [], []
    for r in recs:
        if r.get('attempts', 0) >= MAX_ATTEMPTS:
            dropped.append(r)
            await codeflixbots.delete_task(r['_id'])
        else:
            keep.append(r)

    if keep:
        try:
            notice = await client.send_message(
                user_id, f"**♻️ Bot restarted.** Resuming {len(keep)} unfinished file(s)..."
            )
        except Exception as e:
            # user blocked the bot / chat unreachable: nothing to resume for them
            logger.warning(f"Dropping queue of unreachable user {user_id}: {e}")
            await codeflixbots.delete_user_tasks(user_id)
            return
        msgs = await resolve_messages(client, user_id, keep)
        queue = user_queues.setdefault(user_id, [])
        for r, m in zip(keep, msgs):
            queue.append(_task_from_record(r, m, notice))
        user_last_add[user_id] = time.time()
        asyncio.create_task(process_queue(client, user_id))

    if dropped:
        names = "\n".join(f"`{r['file_name'][:45]}`" for r in dropped[:5])
        more = f"\n_...and {len(dropped) - 5} more_" if len(dropped) > 5 else ""
        try:
            await client.send_message(
                user_id,
                f"**⚠️ {len(dropped)} file(s) were skipped** because the bot stopped "
                f"while processing them {MAX_ATTEMPTS} times:\n{names}{more}\n"
                "Forward them again if you still need them."
            )
        except Exception:
            pass

# ── Queue processor ────────────────────────────────────────────────────────────

async def _wait_for_batch(user_id):
    """Let a burst of forwarded files finish arriving so they can be ordered by message id."""
    started = time.time()
    while time.time() - started < COLLECT_MAX:
        if time.time() - user_last_add.get(user_id, 0) >= COLLECT_QUIET:
            break
        await asyncio.sleep(0.5)


async def process_queue(client, user_id):
    if user_processing.get(user_id, False):
        return
    user_processing[user_id] = True
    try:
        await _wait_for_batch(user_id)
        done = 0
        while user_queues.get(user_id) and not user_cancel.get(user_id, False):
            task = user_queues[user_id].pop(0)
            done += 1
            total = done + len(user_queues.get(user_id, []))
            if task.get('queue_msg'):
                try:
                    await task['queue_msg'].edit(
                        f"**⚙️ Processing file {done}/{total}**\n"
                        f"`{task['file_name'][:50]}`"
                    )
                except:
                    pass
            await codeflixbots.mark_task_started(task['task_id'])
            try:
                await do_rename(
                    client, task['message'], user_id,
                    task['format_template'], task['file_id'],
                    task['file_name'], task['media_type'],
                    task['season'], task['episode'], task['quality']
                )
            except asyncio.CancelledError:
                # Bot is shutting down: keep the record so this file resumes after restart
                raise
            except Exception as e:
                logger.error(f"Unexpected error while processing {task['file_name']}: {e}")
            # Finished (uploaded, or failed and already reported to the user): remove the record
            await codeflixbots.delete_task(task['task_id'])
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
    await codeflixbots.delete_user_tasks(user_id)   # also forget them in MongoDB
    await message.reply_text(f"**✅ Queue cancelled!**\n{count} pending file(s) removed.")

# ── Add to queue helper ────────────────────────────────────────────────────────

async def add_to_queue(client, message, user_id, format_template, file_id, file_name,
                       media_type, season, episode, quality, notify=True, queue_msg=None):
    task_id = f"{user_id}:{message.id}"

    # Save first: if the bot dies right after this line the file is still remembered
    await codeflixbots.add_queue_task(task_id, {
        'user_id': int(user_id), 'chat_id': message.chat.id, 'message_id': message.id,
        'file_id': file_id, 'file_name': file_name, 'media_type': media_type,
        'format_template': format_template, 'season': season, 'episode': episode,
        'quality': quality, 'status': 'pending',
    })

    task = {
        'task_id': task_id, 'message': message, 'user_id': user_id, 'msg_id': message.id,
        'format_template': format_template, 'file_id': file_id,
        'file_name': file_name, 'media_type': media_type,
        'season': season, 'episode': episode, 'quality': quality,
        'queue_msg': queue_msg,
    }

    # Keep Telegram's order: files still waiting are ordered by message id,
    # no matter which one finished its own pre-processing first.
    queue = user_queues.setdefault(user_id, [])
    idx = len(queue)
    while idx > 0 and queue[idx - 1]['msg_id'] > task['msg_id']:
        idx -= 1
    queue.insert(idx, task)
    user_last_add[user_id] = time.time()

    if notify and queue_msg is None:
        try:
            task['queue_msg'] = await message.reply_text(
                f"**📋 Added to queue!**\n"
                f"Position: `{idx + 1}`\n"
                f"File: `{file_name[:50]}`"
            )
        except Exception as e:
            logger.warning(f"Could not send queue notice: {e}")

    if not user_processing.get(user_id, False):
        asyncio.create_task(process_queue(client, user_id))

# ── /sequence: collect files until the user sends "work" ───────────────────────

seq_notice_tasks = {}


async def _announce_collected(client, user_id):
    try:
        await asyncio.sleep(1.5)       # one message per burst of forwards, not one per file
        count = await codeflixbots.count_sequence_files(user_id)
        await client.send_message(
            user_id,
            f"**📥 {count} file(s) collected.**\n"
            "Send `work` to start (or `/clear` to discard them)."
        )
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.warning(f"Could not send collected notice: {e}")


async def collect_for_sequence(client, message, user_id, file_id, file_name, media_type, season, quality):
    await codeflixbots.add_sequence_file({
        '_id': f"{user_id}:{message.id}", 'user_id': int(user_id), 'chat_id': message.chat.id,
        'message_id': message.id, 'file_id': file_id, 'file_name': file_name,
        'media_type': media_type, 'season': season, 'quality': quality,
    })
    previous = seq_notice_tasks.get(user_id)
    if previous and not previous.done():
        previous.cancel()
    seq_notice_tasks[user_id] = asyncio.create_task(_announce_collected(client, user_id))

# ── Manual input handler ───────────────────────────────────────────────────────

@Client.on_message(
    filters.private & filters.text & ~filters.command(
        ['start', 'autorename', 'set_caption', 'del_caption', 'see_caption',
         'view_thumb', 'viewthumb', 'del_thumb', 'delthumb', 'metadata',
         'settitle', 'setauthor', 'setartist', 'setaudio', 'setsubtitle',
         'setvideo', 'help', 'commands', 'donate', 'premium', 'plan',
         'queue', 'cancel_queue', 'setmedia', 'restart', 'stats',
         'broadcast', 'tutorial', 'defaultseason', 'sequence', 'work', 'clear', 'setthumb']
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

    # /sequence is on: hold the file until the user sends "work" (episodes are numbered then)
    seq_enabled, _ = await codeflixbots.get_sequence(user_id)
    if seq_enabled:
        return await collect_for_sequence(
            client, message, user_id, file_id, file_name, media_type, season, quality
        )

    # Default Season (/defaultseason): when on, it overrides both [SO] and any detected season
    ds_enabled, ds_season = await codeflixbots.get_default_season(user_id)
    if ds_enabled and ds_season:
        season = ds_season

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
