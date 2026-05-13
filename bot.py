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
    
    async def add_user(self, user_id):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {
                "join_date": datetime.now().isoformat(),
                "format": "{season} - Episode {episode} [{quality}]",
                "caption": "",
                "thumbnail": "",
                "metadata": "On",
                "title": "Encoded by @Codeflix_Bots",
                "author": "@Codeflix_Bots",
                "artist": "@Codeflix_Bots"
            }
            self._save()
            return True
        return False
    
    async def get_format(self, user_id):
        return self.data.get(str(user_id), {}).get("format", "{season} - Episode {episode} [{quality}]")
    
    async def set_format(self, user_id, format_str):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["format"] = format_str
        self._save()
    
    async def get_caption(self, user_id):
        return self.data.get(str(user_id), {}).get("caption", "")
    
    async def set_caption(self, user_id, caption):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["caption"] = caption
        self._save()
    
    async def get_thumbnail(self, user_id):
        path = self.data.get(str(user_id), {}).get("thumbnail", "")
        if path and os.path.exists(path):
            return path
        return None
    
    async def set_thumbnail(self, user_id, path):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["thumbnail"] = path
        self._save()
    
    async def get_metadata(self, user_id):
        return self.data.get(str(user_id), {}).get("metadata", "On")
    
    async def set_metadata(self, user_id, value):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["metadata"] = value
        self._save()
    
    async def get_title(self, user_id):
        return self.data.get(str(user_id), {}).get("title", "Encoded by @Codeflix_Bots")
    
    async def set_title(self, user_id, title):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["title"] = title
        self._save()
    
    async def get_author(self, user_id):
        return self.data.get(str(user_id), {}).get("author", "@Codeflix_Bots")
    
    async def set_author(self, user_id, author):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["author"] = author
        self._save()
    
    async def get_artist(self, user_id):
        return self.data.get(str(user_id), {}).get("artist", "@Codeflix_Bots")
    
    async def set_artist(self, user_id, artist):
        if str(user_id) not in self.data:
            self.data[str(user_id)] = {}
        self.data[str(user_id)]["artist"] = artist
        self._save()

db = Database()

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

# ==================== SEASON/EPISODE/QUALITY EXTRACTION ====================

def extract_season_episode_quality(filename):
    season = None
    episode = None
    quality = "Unknown"
    
    # Extract Season and Episode
    match = re.search(r'S(\d+)[ ._-]?E(\d+)', filename, re.IGNORECASE)
    if match:
        season = match.group(1)
        episode = match.group(2)
    else:
        match = re.search(r'Episode[\s-]?(\d+)', filename, re.IGNORECASE)
        if match:
            episode = match.group(1)
    
    # Extract Quality
    if re.search(r'4k|2160p', filename, re.IGNORECASE):
        quality = "4K"
    elif re.search(r'1080p', filename, re.IGNORECASE):
        quality = "1080p"
    elif re.search(r'720p', filename, re.IGNORECASE):
        quality = "720p"
    elif re.search(r'480p', filename, re.IGNORECASE):
        quality = "480p"
    
    return season, episode, quality

# ==================== METADATA ====================

async def add_metadata(input_path, output_path, user_id):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return input_path
    
    metadata_enabled = await db.get_metadata(user_id)
    if metadata_enabled != "On":
        return input_path
    
    title = await db.get_title(user_id)
    author = await db.get_author(user_id)
    artist = await db.get_artist(user_id)
    
    cmd = [ffmpeg, '-y', '-i', input_path]
    if title:
        cmd.extend(['-metadata', f'title={title}'])
    if artist:
        cmd.extend(['-metadata', f'artist={artist}'])
    if author:
        cmd.extend(['-metadata', f'author={author}'])
    cmd.extend(['-map', '0', '-c', 'copy', '-loglevel', 'error', output_path])
    
    try:
        process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await process.communicate()
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return output_path
    except Exception as e:
        logger.error(f"Metadata error: {e}")
    
    return input_path

# ==================== FILE PROCESSING ====================

async def process_file(client, message, user_id, format_template, file_name, media_type, season, episode, quality, status_msg):
    download_path = None
    
    try:
        # Replace placeholders
        new_name = format_template.replace('{season}', str(season) if season else 'XX')
        new_name = new_name.replace('{episode}', str(episode) if episode else 'XX')
        new_name = new_name.replace('{quality}', quality)
        
        ext = os.path.splitext(file_name)[1] or ('.mp4' if media_type == 'video' else '.mp3')
        new_filename = f"{new_name}{ext}"
        
        unique_id = f"{user_id}_{int(time.time())}"
        download_path = f"downloads/{unique_id}{ext}"
        
        os.makedirs("downloads", exist_ok=True)
        
        await status_msg.edit_text("📥 Downloading...")
        
        file_path = await client.download_media(
            message,
            file_name=download_path,
            progress=progress_for_pyrogram,
            progress_args=("Downloading...", status_msg, time.time())
        )
        
        if not file_path or not os.path.exists(file_path):
            raise Exception("Download failed")
        
        await status_msg.edit_text("✅ Download complete!")
        
        # Check cancel
        if db.user_cancel.get(user_id, False):
            raise Exception("Cancelled by user")
        
        # Metadata
        await status_msg.edit_text("🔧 Processing metadata...")
        metadata_path = f"metadata/{unique_id}{ext}"
        os.makedirs("metadata", exist_ok=True)
        result_path = await add_metadata(file_path, metadata_path, user_id)
        
        # Upload
        await status_msg.edit_text("📤 Uploading...")
        caption = await db.get_caption(user_id) or f"**{new_filename}**"
        caption = caption.replace('{filename}', new_filename).replace('{filesize}', humanbytes(os.path.getsize(result_path)))
        
        thumb = await db.get_thumbnail(user_id)
        
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
        
        await status_msg.edit_text("✅ Done!")
        await asyncio.sleep(2)
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
    finally:
        await cleanup_files(download_path)

async def process_queue(user_id):
    if db.user_processing.get(user_id, False):
        return
    
    db.user_processing[user_id] = True
    
    while db.user_queues.get(user_id) and not db.user_cancel.get(user_id, False):
        task = db.user_queues[user_id].pop(0)
        
        status_msg = await task['message'].reply_text(
            f"📋 Processing {task['index']}/{task['total']}\n\nFile: {task['file_name'][:50]}"
        )
        
        await process_file(
            task['client'], task['message'], task['user_id'],
            task['format_template'], task['file_name'],
            task['media_type'], task['season'], task['episode'],
            task['quality'], status_msg
        )
    
    db.user_processing[user_id] = False
    db.user_cancel[user_id] = False

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
    return web.json_response({"status": "running", "bot": "Codeflix Renamer"})

@routes.get("/health", allow_head=True)
async def health_route_handler(request):
    return web.json_response({"status": "healthy"})

async def start_web_server():
    web_app = web.Application()
    web_app.add_routes(routes)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    logger.info(f"Web server started on port {Config.PORT}")

# ==================== BOT INSTANCE ====================

app = Client(
    "codeflix_renamer",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    workers=100
)

# ==================== COMMANDS ====================

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    user = message.from_user
    await db.add_user(user.id)
    
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Help", callback_data="help"),
         InlineKeyboardButton("📋 Queue", callback_data="view_queue")],
        [InlineKeyboardButton("❌ Cancel Queue", callback_data="cancel_queue")]
    ])
    
    try:
        await message.reply_photo(Config.START_PIC, caption=START_TXT.format(user.mention), reply_markup=buttons)
    except:
        await message.reply_text(START_TXT.format(user.mention), reply_markup=buttons)

@app.on_message(filters.private & filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP_TXT, disable_web_page_preview=True)

@app.on_message(filters.private & filters.command("autorename"))
async def auto_rename_command(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("**Usage:** `/autorename Your Format`\n\nExample: `/autorename Series S{season}E{episode} {quality}`")
    
    format_template = parts[1].strip()
    await db.set_format(message.from_user.id, format_template)
    await message.reply_text(f"**✅ Format saved!**\n\n`{format_template}`")

@app.on_message(filters.private & filters.command("set_caption"))
async def set_caption(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/set_caption Your caption here`\n\nVariables: `{filename}`, `{filesize}`")
    caption = message.text.split(" ", 1)[1]
    await db.set_caption(message.from_user.id, caption)
    await message.reply_text("**✅ Caption saved!**")

@app.on_message(filters.private & filters.command("del_caption"))
async def del_caption(client, message):
    await db.set_caption(message.from_user.id, "")
    await message.reply_text("**✅ Caption deleted!**")

@app.on_message(filters.private & filters.command(["view_thumb", "viewthumb"]))
async def view_thumb(client, message):
    thumb = await db.get_thumbnail(message.from_user.id)
    if thumb:
        await client.send_photo(message.chat.id, thumb)
    else:
        await message.reply_text("**No thumbnail set!**")

@app.on_message(filters.private & filters.command(["del_thumb", "delthumb"]))
async def del_thumb(client, message):
    thumb = await db.get_thumbnail(message.from_user.id)
    if thumb and os.path.exists(thumb):
        os.remove(thumb)
    await db.set_thumbnail(message.from_user.id, None)
    await message.reply_text("**✅ Thumbnail deleted!**")

@app.on_message(filters.private & filters.command("metadata"))
async def metadata_cmd(client, message):
    current = await db.get_metadata(message.from_user.id)
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"On {'✅' if current == 'On' else ''}", callback_data="metadata_on"),
         InlineKeyboardButton(f"Off {'✅' if current == 'Off' else ''}", callback_data="metadata_off")]
    ])
    await message.reply_text(f"**Metadata is currently: {current}**", reply_markup=buttons)

@app.on_message(filters.private & filters.command("settitle"))
async def set_title(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/settitle Your Title`")
    title = message.text.split(" ", 1)[1]
    await db.set_title(message.from_user.id, title)
    await message.reply_text(f"**✅ Title saved!**\n\n`{title}`")

@app.on_message(filters.private & filters.command("setauthor"))
async def set_author(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/setauthor Your Author`")
    author = message.text.split(" ", 1)[1]
    await db.set_author(message.from_user.id, author)
    await message.reply_text(f"**✅ Author saved!**\n\n`{author}`")

@app.on_message(filters.private & filters.command("setartist"))
async def set_artist(client, message):
    if len(message.command) == 1:
        return await message.reply_text("**Usage:** `/setartist Your Artist`")
    artist = message.text.split(" ", 1)[1]
    await db.set_artist(message.from_user.id, artist)
    await message.reply_text(f"**✅ Artist saved!**\n\n`{artist}`")

@app.on_message(filters.private & filters.command("queue"))
async def queue_cmd(client, message):
    user_id = message.from_user.id
    queue = db.user_queues.get(user_id, [])
    if not queue:
        return await message.reply_text("**📋 Your queue is empty!**")
    
    text = f"**📋 Queue ({len(queue)} files)**\n\n"
    for i, task in enumerate(queue[:10], 1):
        text += f"{i}. `{task['file_name'][:40]}`\n   S{task['season']}E{task['episode']} | {task['quality']}\n\n"
    if len(queue) > 10:
        text += f"\n... and {len(queue) - 10} more"
    await message.reply_text(text)

@app.on_message(filters.private & filters.command("cancel_queue"))
async def cancel_queue_cmd(client, message):
    user_id = message.from_user.id
    db.user_cancel[user_id] = True
    count = len(db.user_queues.get(user_id, []))
    db.user_queues[user_id] = []
    await message.reply_text(f"**✅ Cancelled {count} files from queue!**")

@app.on_message(filters.private & filters.photo)
async def add_thumbnail(client, message):
    msg = await message.reply_text("Processing thumbnail...")
    os.makedirs("downloads", exist_ok=True)
    thumb_path = await client.download_media(message, file_name=f"downloads/thumb_{message.from_user.id}.jpg")
    thumb_path = await process_thumbnail(thumb_path)
    await db.set_thumbnail(message.from_user.id, thumb_path)
    await msg.edit_text("**✅ Thumbnail saved! (320x320)**")

# ==================== FILE HANDLER ====================

@app.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    user_id = message.from_user.id
    
    # Add user if not exists
    await db.add_user(user_id)
    
    format_template = await db.get_format(user_id)
    if not format_template:
        return await message.reply_text("**⚠️ Please set format first using /autorename**")
    
    if message.document:
        file_name = message.document.file_name or "file"
        media_type = "document"
    elif message.video:
        file_name = message.video.file_name or "video"
        media_type = "video"
    else:
        file_name = message.audio.file_name or "audio"
        media_type = "audio"
    
    combined = f"{file_name} {message.caption or ''}"
    season, episode, quality = extract_season_episode_quality(combined)
    
    if not season or not episode:
        return await message.reply_text(
            "**⚠️ Could not detect Season/Episode!**\n\n"
            "Please ensure filename contains S01E05 format.\n"
            "Example: `Show Name S01E05 720p.mkv`"
        )
    
    if quality == "Unknown":
        quality = "HD"
    
    # Add to queue
    if user_id not in db.user_queues:
        db.user_queues[user_id] = []
    
    queue_len = len(db.user_queues[user_id])
    for i, task in enumerate(db.user_queues[user_id]):
        task['index'] = i + 1
        task['total'] = queue_len + 1
    
    task = {
        'client': client, 'message': message, 'user_id': user_id,
        'file_name': file_name, 'media_type': media_type,
        'format_template': format_template, 'season': season,
        'episode': episode, 'quality': quality,
        'index': queue_len + 1, 'total': queue_len + 1
    }
    
    db.user_queues[user_id].append(task)
    
    await message.reply_text(
        f"**📋 Added to queue!**\n\n"
        f"**Position:** {queue_len + 1}\n"
        f"**Queue size:** {queue_len + 1}\n"
        f"**Detected:** S{season}E{episode} | {quality}\n\n"
        f"Use `/queue` to view, `/cancel_queue` to clear"
    )
    
    await process_queue(user_id)

# ==================== CALLBACK HANDLERS ====================

@app.on_callback_query()
async def callback_handler(client, query):
    data = query.data
    user_id = query.from_user.id
    
    if data == "help":
        await query.message.edit_text(HELP_TXT, disable_web_page_preview=True)
    elif data == "view_queue":
        queue = db.user_queues.get(user_id, [])
        if not queue:
            await query.answer("Queue is empty!", show_alert=True)
        else:
            text = f"**📋 Queue ({len(queue)} files)**\n\n"
            for i, task in enumerate(queue[:10], 1):
                text += f"{i}. `{task['file_name'][:40]}`\n"
            await query.message.edit_text(text)
    elif data == "cancel_queue":
        db.user_cancel[user_id] = True
        count = len(db.user_queues.get(user_id, []))
        db.user_queues[user_id] = []
        await query.message.edit_text(f"**✅ Cancelled {count} files!**")
    elif data == "metadata_on":
        await db.set_metadata(user_id, "On")
        await query.message.edit_text("**✅ Metadata enabled!**")
    elif data == "metadata_off":
        await db.set_metadata(user_id, "Off")
        await query.message.edit_text("**✅ Metadata disabled!**")
    elif data == "cancel_processing":
        db.user_cancel[user_id] = True
        await query.answer("Cancelling current operation...", show_alert=True)

# ==================== MAIN ====================

async def main():
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("metadata", exist_ok=True)
    
    await app.start()
    logger.info("Bot started!")
    
    await start_web_server()
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")