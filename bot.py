import os
import re
import time
import shutil
import asyncio
import logging
import json
from datetime import datetime
from PIL import Image
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ==================== CONFIGURATION ====================

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    ADMIN = [int(x) for x in os.environ.get("ADMIN", "").split()] if os.environ.get("ADMIN") else []
    START_PIC = os.environ.get("START_PIC", "https://graph.org/file/29a3acbbab9de5f45a5fe.jpg")
    PORT = int(os.environ.get("PORT", 8080))
    DB_FILE = "database.json"

# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== DATABASE ====================

class Database:
    def __init__(self):
        self.data = self._load()
        self.user_queues = {}
        self.user_processing = {}
        self.user_cancel = {}
    
    def _load(self):
        if os.path.exists(Config.DB_FILE):
            try:
                with open(Config.DB_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def _save(self):
        with open(Config.DB_FILE, 'w') as f:
            json.dump(self.data, f, indent=4)
    
    def get_format(self, user_id):
        return self.data.get(str(user_id), {}).get("format", "{season} - Episode {episode} [{quality}]")
    
    def set_format(self, user_id, format_str):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["format"] = format_str
        self._save()
    
    def get_caption(self, user_id):
        return self.data.get(str(user_id), {}).get("caption", "")
    
    def set_caption(self, user_id, caption):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["caption"] = caption
        self._save()
    
    def get_thumbnail(self, user_id):
        path = self.data.get(str(user_id), {}).get("thumbnail", "")
        if path and os.path.exists(path):
            return path
        return None
    
    def set_thumbnail(self, user_id, path):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["thumbnail"] = path
        self._save()
    
    def get_metadata(self, user_id):
        return self.data.get(str(user_id), {}).get("metadata", "Off")
    
    def set_metadata(self, user_id, value):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["metadata"] = value
        self._save()
    
    def get_title(self, user_id):
        return self.data.get(str(user_id), {}).get("title", "Encoded by @Animes_Cruise")
    
    def set_title(self, user_id, title):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["title"] = title
        self._save()
    
    def get_author(self, user_id):
        return self.data.get(str(user_id), {}).get("author", "@Animes_Cruise")
    
    def set_author(self, user_id, author):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["author"] = author
        self._save()
    
    def get_artist(self, user_id):
        return self.data.get(str(user_id), {}).get("artist", "@Animes_Cruise")
    
    def set_artist(self, user_id, artist):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["artist"] = artist
        self._save()
    
    def get_audio(self, user_id):
        return self.data.get(str(user_id), {}).get("audio", "By @Animes_Cruise")
    
    def set_audio(self, user_id, audio):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["audio"] = audio
        self._save()
    
    def get_subtitle(self, user_id):
        return self.data.get(str(user_id), {}).get("subtitle", "By @Animes_Cruise")
    
    def set_subtitle(self, user_id, subtitle):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["subtitle"] = subtitle
        self._save()
    
    def get_video(self, user_id):
        return self.data.get(str(user_id), {}).get("video", "Encoded By @Animes_Cruise")
    
    def set_video(self, user_id, video):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["video"] = video
        self._save()
    
    def total_users_count(self):
        return len(self.data)

codeflixbots = Database()

# ==================== UTILITIES ====================

def humanbytes(size):
    if not size:
        return "0 B"
    power = 2**10
    n = 0
    labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size > power:
        size /= power
        n += 1
    return f"{round(size, 2)} {labels[n]}"

async def progress_for_pyrogram(current, total, ud_type, message, start):
    now = time.time()
    diff = now - start
    if round(diff % 5.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff if diff > 0 else 0
        
        progress = "".join(["■" for i in range(int(percentage / 5))])
        progress += "".join(["□" for i in range(20 - int(percentage / 5))])
        
        tmp = f"{progress}\n📊 {round(percentage, 2)}%\n📦 {humanbytes(current)} / {humanbytes(total)}\n⚡ {humanbytes(speed)}/s"
        
        try:
            await message.edit_text(
                text=f"{ud_type}\n\n{tmp}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_processing")]])
            )
        except:
            pass

async def safe_edit(msg, text):
    try:
        await msg.edit(text)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            pass

async def cleanup_files(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except:
            pass

async def process_thumbnail(thumb_path):
    if not thumb_path or not os.path.exists(thumb_path):
        return None
    try:
        with Image.open(thumb_path) as img:
            img = img.convert("RGB").resize((320, 320))
            img.save(thumb_path, "JPEG")
        return thumb_path
    except:
        return None

# ==================== NSFW DETECTION ====================

NSFW_KEYWORDS = [
    "porn", "sex", "nude", "naked", "hentai", "xxx", "adult",
    "boobs", "tits", "pussy", "dick", "cock", "ass", "fuck"
]

async def check_anti_nsfw(new_name, message):
    lower_name = new_name.lower()
    for keyword in NSFW_KEYWORDS:
        if keyword.lower() in lower_name:
            await message.reply_text("❌ NSFW content detected! File rejected.")
            return True
    return False

# ==================== SEASON/EPISODE/QUALITY EXTRACTION ====================

SEASON_EPISODE_PATTERNS = [
    (re.compile(r'S(\d+)(?:E|EP)(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'\[S(\d+)[\s-]+(\d+)\]', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'Season\s*(\d+)\s*Episode\s*(\d+)', re.IGNORECASE), ('season', 'episode')),
    (re.compile(r'\bS(\d+)\b', re.IGNORECASE), ('season', None)),
    (re.compile(r'(?:E|EP)(\d+)', re.IGNORECASE), (None, 'episode')),
]

QUALITY_PATTERNS = [
    (re.compile(r'\b(4k|2160p)\b', re.IGNORECASE), "4k"),
    (re.compile(r'\b(1080p)\b', re.IGNORECASE), "1080p"),
    (re.compile(r'\b(720p)\b', re.IGNORECASE), "720p"),
    (re.compile(r'\b(480p)\b', re.IGNORECASE), "480p"),
]

def extract_season_episode(text):
    if not text:
        return None, None
    season_found = None
    episode_found = None
    for pattern, (season_group, episode_group) in SEASON_EPISODE_PATTERNS:
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
                episode_found = match.group(2 if season_group else 1)
            except:
                try:
                    episode_found = match.group(1)
                except:
                    pass
    return season_found, episode_found

def extract_quality(text):
    if not text:
        return None
    for pattern, quality in QUALITY_PATTERNS:
        if pattern.search(text):
            return quality
    return None

# ==================== METADATA ====================

async def add_metadata(input_path, output_path, user_id):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return  # Skip metadata if ffmpeg not found
    
    metadata_enabled = codeflixbots.get_metadata(user_id)
    if metadata_enabled != "On":
        return
    
    title = codeflixbots.get_title(user_id)
    author = codeflixbots.get_author(user_id)
    
    cmd = [ffmpeg, '-y', '-i', input_path]
    if title:
        cmd.extend(['-metadata', f'title={title}'])
    if author:
        cmd.extend(['-metadata', f'artist={author}'])
    cmd.extend(['-map', '0', '-c', 'copy', '-loglevel', 'error', output_path])
    
    try:
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except:
        pass
    return input_path

# ==================== FILE PROCESSING ====================

async def process_file(client, message, user_id, format_template, file_name, media_type, season, episode, quality, status_msg):
    download_path = None
    
    try:
        # Replace placeholders
        format_template = format_template.replace('{season}', str(season) if season else 'XX')
        format_template = format_template.replace('{episode}', str(episode) if episode else 'XX')
        format_template = format_template.replace('{quality}', str(quality) if quality else 'Unknown')
        
        ext = os.path.splitext(file_name)[1] or ('.mp4' if media_type == 'video' else '.mp3')
        new_filename = f"{format_template}{ext}"
        
        unique_id = f"{user_id}_{int(time.time())}"
        download_path = f"downloads/{unique_id}{ext}"
        
        os.makedirs("downloads", exist_ok=True)
        
        await safe_edit(status_msg, "**📥 Downloading...**")
        
        file_path = await client.download_media(
            message,
            file_name=download_path,
            progress=progress_for_pyrogram,
            progress_args=("Downloading...", status_msg, time.time())
        )
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("Download failed")
        
        await safe_edit(status_msg, "**✅ Download complete!**")
        
        # Check cancel
        if codeflixbots.user_cancel.get(user_id, False):
            raise Exception("Cancelled by user")
        
        # Metadata (optional)
        await safe_edit(status_msg, "**🔧 Processing...**")
        metadata_path = f"metadata/{unique_id}{ext}"
        os.makedirs("metadata", exist_ok=True)
        result_path = await add_metadata(file_path, metadata_path, user_id) or file_path
        
        # Upload
        await safe_edit(status_msg, "**📤 Uploading...**")
        caption = codeflixbots.get_caption(user_id) or f"**{new_filename}**"
        caption = caption.replace('{filename}', new_filename).replace('{filesize}', humanbytes(os.path.getsize(result_path)))
        
        thumb = codeflixbots.get_thumbnail(user_id)
        
        upload_params = {
            'chat_id': message.chat.id,
            'caption': caption,
            'thumb': thumb,
            'progress': progress_for_pyrogram,
            'progress_args': ("Uploading...", status_msg, time.time())
        }
        
        if media_type == "document":
            await client.send_document(document=result_path, file_name=new_filename, **upload_params)
        elif media_type == "video":
            await client.send_video(video=result_path, **upload_params)
        elif media_type == "audio":
            await client.send_audio(audio=result_path, file_name=new_filename, **upload_params)
        
        await safe_edit(status_msg, "**✅ Done!**")
        await asyncio.sleep(2)
        await status_msg.delete()
        
    except Exception as e:
        await safe_edit(status_msg, f"**❌ Error:** `{str(e)[:100]}`")
    finally:
        await cleanup_files(download_path)

async def process_queue(user_id):
    if codeflixbots.user_processing.get(user_id, False):
        return
    
    codeflixbots.user_processing[user_id] = True
    
    while codeflixbots.user_queues.get(user_id) and not codeflixbots.user_cancel.get(user_id, False):
        task = codeflixbots.user_queues[user_id].pop(0)
        
        status_msg = await task['message'].reply_text(
            f"**📋 Processing {task['index']}/{task['total']}**\n\n**File:** `{task['file_name'][:50]}`"
        )
        
        await process_file(
            task['client'], task['message'], task['user_id'],
            task['format_template'], task['file_name'],
            task['media_type'], task['season'], task['episode'], 
            task['quality'], status_msg
        )
    
    codeflixbots.user_processing[user_id] = False
    codeflixbots.user_cancel[user_id] = False

# ==================== TEXT ====================

START_TXT = """<b>ʜᴇʏ {}! 👋

ɪ ᴀᴍ ᴀᴅᴠᴀɴᴄᴇᴅ ʀᴇɴᴀᴍᴇ ʙᴏᴛ!

📌 Commands:
/autorename - Set rename format
/set_caption - Set custom caption
/queue - View your queue
/cancel_queue - Clear all pending files
/help - Get help</b>"""

HELP_TXT = """<b>📖 How to Use:

1️⃣ Set format: /autorename Series S{season}E{episode} {quality}
2️⃣ Send your file
3️⃣ Bot auto-detects season/episode/quality

📋 Queue Commands:
/queue - See pending files
/cancel_queue - Cancel all files

🖼 Thumbnail:
Send any photo to set as thumbnail
/viewthumb - View thumbnail
/delthumb - Delete thumbnail</b>"""

# ==================== WEB SERVER ====================

routes = web.RouteTableDef()

@routes.get("/", allow_head=True)
async def root_route_handler(request):
    return web.json_response({"status": "running"})

@routes.get("/health", allow_head=True)
async def health_route_handler(request):
    return web.json_response({"status": "healthy"})

async def web_server():
    web_app = web.Application()
    web_app.add_routes(routes)
    return web_app

# ==================== BOT INSTANCE ====================

app = Client(
    "autorename_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    workers=100
)

# ==================== COMMANDS ====================

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    user = message.from_user
    await message.reply_photo(
        Config.START_PIC,
        caption=START_TXT.format(user.mention),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Help", callback_data="help"),
             InlineKeyboardButton("📋 Queue", callback_data="view_queue")],
            [InlineKeyboardButton("❌ Cancel Queue", callback_data="cancel_queue")]
        ])
    )

@app.on_message(filters.private & filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP_TXT, disable_web_page_preview=True)

@app.on_message(filters.private & filters.command("autorename"))
async def auto_rename_command(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("**Usage:** `/autorename Your Format`\n\nExample: `/autorename Series S{season}E{episode} {quality}`")
    
    format_template = parts[1].strip()
    codeflixbots.set_format(message.from_user.id, format_template)
    await message.reply_text(f"**✅ Format saved!**\n\n`{format_template}`")

@app.on_message(filters.private & filters.command("set_caption"))
async def set_caption(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/set_caption Your caption`")
    caption = message.text.split(" ", 1)[1]
    codeflixbots.set_caption(message.from_user.id, caption)
    await message.reply_text("**✅ Caption saved!**")

@app.on_message(filters.private & filters.command("del_caption"))
async def del_caption(client, message):
    codeflixbots.set_caption(message.from_user.id, "")
    await message.reply_text("**✅ Caption deleted!**")

@app.on_message(filters.private & filters.command(["view_thumb", "viewthumb"]))
async def view_thumb(client, message):
    thumb = codeflixbots.get_thumbnail(message.from_user.id)
    if thumb:
        await client.send_photo(message.chat.id, thumb)
    else:
        await message.reply_text("**No thumbnail set!**")

@app.on_message(filters.private & filters.command(["del_thumb", "delthumb"]))
async def del_thumb(client, message):
    thumb = codeflixbots.get_thumbnail(message.from_user.id)
    if thumb and os.path.exists(thumb):
        os.remove(thumb)
    codeflixbots.set_thumbnail(message.from_user.id, "")
    await message.reply_text("**✅ Thumbnail deleted!**")

@app.on_message(filters.private & filters.command("metadata"))
async def metadata_cmd(client, message):
    current = codeflixbots.get_metadata(message.from_user.id)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"On {'✅' if current == 'On' else ''}", callback_data="metadata_on"),
         InlineKeyboardButton(f"Off {'✅' if current == 'Off' else ''}", callback_data="metadata_off")]
    ])
    await message.reply_text(f"**Metadata: {current}**", reply_markup=buttons)

@app.on_message(filters.private & filters.command("settitle"))
async def set_title(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/settitle Your Title`")
    title = message.text.split(" ", 1)[1]
    codeflixbots.set_title(message.from_user.id, title)
    await message.reply_text("**✅ Title saved!**")

@app.on_message(filters.private & filters.command("setauthor"))
async def set_author(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/setauthor Your Author`")
    author = message.text.split(" ", 1)[1]
    codeflixbots.set_author(message.from_user.id, author)
    await message.reply_text("**✅ Author saved!**")

@app.on_message(filters.private & filters.command("setartist"))
async def set_artist(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/setartist Your Artist`")
    artist = message.text.split(" ", 1)[1]
    codeflixbots.set_artist(message.from_user.id, artist)
    await message.reply_text("**✅ Artist saved!**")

@app.on_message(filters.private & filters.command("queue"))
async def queue_cmd(client, message):
    user_id = message.from_user.id
    queue = codeflixbots.user_queues.get(user_id, [])
    if not queue:
        return await message.reply_text("**📋 Your queue is empty!**")
    
    text = f"**📋 Queue ({len(queue)} files)**\n\n"
    for i, task in enumerate(queue[:10], 1):
        text += f"{i}. `{task['file_name'][:40]}`\n   S{task['season']}E{task['episode']} | {task['quality']}\n\n"
    await message.reply_text(text)

@app.on_message(filters.private & filters.command("cancel_queue"))
async def cancel_queue_cmd(client, message):
    user_id = 
