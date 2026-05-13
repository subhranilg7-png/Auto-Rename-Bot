import os
import re
import time
import asyncio
import logging
import json
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

# ==================== CONFIG ====================

class Config:
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    ADMIN = int(os.environ.get("ADMIN", 0)) if os.environ.get("ADMIN") else None
    LOG_CHANNEL = os.environ.get("LOG_CHANNEL", None)
    PORT = int(os.environ.get("PORT", 8080))
    DB_FILE = "database.json"
    
    # Choose mode: "webhook" or "polling"
    MODE = os.environ.get("MODE", "webhook")
    
    # Your Render URL (for webhook mode)
    RENDER_URL = os.environ.get("RENDER_URL", "")

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
        return self.data.get(str(user_id), {}).get("format", None)
    
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

codeflixbots = Database()

# ==================== BOT INSTANCE ====================

app = Client(
    "autorename_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# ==================== TEXT ====================

START_TXT = """<b>ʜᴇʏ {}! 👋

ɪ ᴀᴍ ᴀᴅᴠᴀɴᴄᴇᴅ ʀᴇɴᴀᴍᴇ ʙᴏᴛ!

📌 Commands:
/autorename - Set rename format
/set_caption - Set custom caption
/queue - View your queue
/cancel_queue - Clear all pending files
/help - Get help

🔄 Mode: {}</b>"""

HELP_TXT = """<b>📖 How to Use:

1️⃣ Set format: /autorename Series S{season}E{episode}
2️⃣ Send your file
3️⃣ Bot auto-renames it

Example filename: Show S01E05 720p.mkv

📋 Queue Commands:
/queue - See pending files
/cancel_queue - Cancel all files</b>"""

# ==================== QUEUE SYSTEM ====================

user_queues = {}
user_processing = {}
user_cancel = {}

def extract_season_episode(filename):
    match = re.search(r'S(\d+)[ ._-]?E(\d+)', filename, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)
    return None, None

async def process_file(client, message, user_id, format_template, file_name, media_type, season, episode, status_msg):
    download_path = None
    
    try:
        # Replace placeholders
        new_name = format_template.replace('{season}', season).replace('{episode}', episode)
        ext = os.path.splitext(file_name)[1]
        new_filename = f"{new_name}{ext}"
        
        download_path = f"downloads/{user_id}_{int(time.time())}{ext}"
        os.makedirs("downloads", exist_ok=True)
        
        await status_msg.edit_text("📥 Downloading...")
        
        file_path = await client.download_media(message, file_name=download_path)
        
        if not file_path:
            raise Exception("Download failed")
        
        # Check cancel
        if user_cancel.get(user_id, False):
            raise Exception("Cancelled by user")
        
        await status_msg.edit_text("📤 Uploading...")
        caption = await codeflixbots.get_caption(user_id) or f"**{new_filename}**"
        
        if media_type == "document":
            await client.send_document(message.chat.id, document=file_path, file_name=new_filename, caption=caption)
        elif media_type == "video":
            await client.send_video(message.chat.id, video=file_path, caption=caption)
        else:
            await client.send_audio(message.chat.id, audio=file_path, caption=caption)
        
        await status_msg.edit_text("✅ Done!")
        await asyncio.sleep(2)
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:100]}")
    finally:
        if download_path and os.path.exists(download_path):
            os.remove(download_path)

async def process_queue(user_id):
    if user_processing.get(user_id, False):
        return
    
    user_processing[user_id] = True
    
    while user_queues.get(user_id) and not user_cancel.get(user_id, False):
        task = user_queues[user_id].pop(0)
        
        status_msg = await task['message'].reply_text(
            f"📋 Processing {task['index']}/{task['total']}\n\nFile: {task['file_name'][:50]}"
        )
        
        await process_file(
            task['client'], task['message'], user_id,
            task['format_template'], task['file_name'],
            task['media_type'], task['season'], task['episode'],
            status_msg
        )
    
    user_processing[user_id] = False
    user_cancel[user_id] = False

# ==================== BOT COMMANDS ====================

@app.on_message(filters.private & filters.command("start"))
async def start(client, message):
    user = message.from_user
    mode = Config.MODE.upper()
    await message.reply_text(
        START_TXT.format(user.first_name, mode),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📖 Help", callback_data="help"),
             InlineKeyboardButton("📋 Queue", callback_data="view_queue")],
            [InlineKeyboardButton("❌ Cancel Queue", callback_data="cancel_queue")]
        ])
    )
    
    # Send log to channel
    if Config.LOG_CHANNEL:
        try:
            await client.send_message(
                Config.LOG_CHANNEL,
                f"✅ New user started!\nUser: {user.mention}\nID: `{user.id}`\nMode: {mode}"
            )
        except:
            pass

@app.on_message(filters.private & filters.command("help"))
async def help_cmd(client, message):
    await message.reply_text(HELP_TXT)

@app.on_message(filters.private & filters.command("autorename"))
async def set_format(client, message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("Usage: `/autorename Your Format Here`\n\nExample: `/autorename Series S{season}E{episode} [1080p]`")
    
    format_template = parts[1].strip()
    await codeflixbots.set_format(message.from_user.id, format_template)
    await message.reply_text(f"✅ Format saved!\n`{format_template}`")

@app.on_message(filters.private & filters.command("set_caption"))
async def set_caption(client, message):
    if len(message.command) == 1:
        return await message.reply_text("Usage: `/set_caption Your caption here`")
    caption = message.text.split(" ", 1)[1]
    await codeflixbots.set_caption(message.from_user.id, caption)
    await message.reply_text("✅ Caption saved!")

@app.on_message(filters.private & filters.command("queue"))
async def queue_cmd(client, message):
    user_id = message.from_user.id
    queue = user_queues.get(user_id, [])
    if not queue:
        return await message.reply_text("📋 Your queue is empty!")
    
    text = f"📋 Queue ({len(queue)} files)\n\n"
    for i, task in enumerate(queue[:10], 1):
        text += f"{i}. {task['file_name'][:40]}\n   S{task['season']}E{task['episode']}\n\n"
    await message.reply_text(text)

@app.on_message(filters.private & filters.command("cancel_queue"))
async def cancel_queue_cmd(client, message):
    user_id = message.from_user.id
    user_cancel[user_id] = True
    count = len(user_queues.get(user_id, []))
    user_queues[user_id] = []
    await message.reply_text(f"✅ Cancelled {count} files!")

@app.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_file(client, message):
    user_id = message.from_user.id
    
    # Get format template
    format_template = await codeflixbots.get_format(user_id)
    if not format_template:
        return await message.reply_text("⚠️ Please set format first using /autorename")
    
    # Get file info
    if message.document:
        file_name = message.document.file_name or "file"
        media_type = "document"
    elif message.video:
        file_name = message.video.file_name or "video"
        media_type = "video"
    else:
        file_name = message.audio.file_name or "audio"
        media_type = "audio"
    
    # Extract season and episode
    season, episode = extract_season_episode(file_name)
    if not season or not episode:
        return await message.reply_text("⚠️ Could not detect season/episode!\nUse format: S01E05 in filename")
    
    # Add to queue
    if user_id not in user_queues:
        user_queues[user_id] = []
    
    queue_len = len(user_queues[user_id])
    for i, task in enumerate(user_queues[user_id]):
        task['index'] = i + 1
        task['total'] = queue_len + 1
    
    task = {
        'client': client, 'message': message, 'user_id': user_id,
        'file_name': file_name, 'media_type': media_type,
        'format_template': format_template, 'season': season,
        'episode': episode, 'index': queue_len + 1, 'total': queue_len + 1
    }
    
    user_queues[user_id].append(task)
    
    await message.reply_text(
        f"📋 Added to queue!\n\nPosition: {queue_len + 1}\nQueue size: {queue_len + 1}\nDetected: S{season}E{episode}"
    )
    
    await process_queue(user_id)

@app.on_callback_query()
async def callback_handler(client, query):
    data = query.data
    user_id = query.from_user.id
    
    if data == "help":
        await query.message.edit_text(HELP_TXT)
    elif data == "view_queue":
        queue = user_queues.get(user_id, [])
        if not queue:
            await query.answer("Queue is empty!", show_alert=True)
        else:
            text = f"📋 Queue ({len(queue)} files)\n\n"
            for i, task in enumerate(queue[:10], 1):
                text += f"{i}. {task['file_name'][:40]}\n"
            await query.message.edit_text(text)
    elif data == "cancel_queue":
        user_cancel[user_id] = True
        count = len(user_queues.get(user_id, []))
        user_queues[user_id] = []
        await query.message.edit_text(f"✅ Cancelled {count} files!")

# ==================== WEBHOOK SUPPORT ====================

routes = web.RouteTableDef()

@routes.post(f"/webhook/{Config.BOT_TOKEN}")
async def webhook_handler(request):
    """Receive updates from Telegram via webhook"""
    try:
        data = await request.json()
        # Process update manually for webhook
        from pyrogram.types import Update
        update = Update(**data)
        await app.process_update(update)
        return web.Response(status=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.Response(status=500)

@routes.get("/")
@routes.get("/health")
async def health_check(request):
    return web.json_response({
        "status": "running",
        "mode": Config.MODE,
        "timestamp": datetime.now().isoformat()
    })

async def run_web_server():
    """Start the web server for webhook mode"""
    web_app = web.Application()
    web_app.add_routes(routes)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", Config.PORT)
    await site.start()
    logger.info(f"Web server started on port {Config.PORT}")

async def setup_webhook():
    """Set webhook for Telegram"""
    if not Config.RENDER_URL:
        logger.warning("RENDER_URL not set, webhook mode may not work")
        return
    
    webhook_url = f"{Config.RENDER_URL}/webhook/{Config.BOT_TOKEN}"
    try:
        await app.set_webhook(webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

async def remove_webhook():
    """Remove webhook (for polling mode)"""
    try:
        await app.delete_webhook()
        logger.info("Webhook removed")
    except:
        pass

# ==================== KEEP-ALIVE FOR POLLING MODE ====================

async def keep_alive():
    """Ping the server every 4 minutes to keep it awake (for polling mode)"""
    url = f"http://localhost:{Config.PORT}/health"
    while True:
        await asyncio.sleep(240)  # 4 minutes
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                await session.get(url)
                logger.debug("Keep-alive ping sent")
        except:
            pass

async def polling_mode():
    """Run bot in polling mode with keep-alive"""
    logger.info("Starting in POLLING mode")
    await remove_webhook()
    await run_web_server()
    asyncio.create_task(keep_alive())
    
    # Start polling
    await app.start()
    logger.info("Bot started in polling mode")
    await asyncio.Event().wait()

async def webhook_mode():
    """Run bot in webhook mode"""
    logger.info("Starting in WEBHOOK mode")
    await app.start()
    await setup_webhook()
    await run_web_server()
    logger.info("Bot started in webhook mode")
    await asyncio.Event().wait()

# ==================== MAIN ====================

async def send_startup_message():
    """Send startup notification"""
    if Config.LOG_CHANNEL:
        try:
            me = await app.get_me()
            await app.send_message(
                Config.LOG_CHANNEL,
                f"🤖 **Bot Started!**\n\n"
                f"**Name:** {me.first_name}\n"
                f"**Username:** @{me.username}\n"
                f"**Mode:** {Config.MODE.upper()}\n"
                f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        except Exception as e:
            logger.error(f"Failed to send startup message: {e}")

async def main():
    os.makedirs("downloads", exist_ok=True)
    
    if Config.MODE == "webhook":
        await webhook_mode()
    else:
        await polling_mode()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
