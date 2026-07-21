import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import aiohttp, warnings, pytz
from datetime import datetime, timedelta
from pytz import timezone
from pyrogram import Client, __version__
from pyrogram.raw.all import layer
from config import Config
from aiohttp import web
from route import web_server
import pyrogram.utils
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
import os
import time

pyrogram.utils.MIN_CHANNEL_ID = -1009147483647

PORT = Config.PORT

BOT_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("help", "Help menu"),
    BotCommand("commands", "Show all commands"),
    BotCommand("autorename", "Set auto rename format"),
    BotCommand("queue", "View your queue status"),
    BotCommand("cancel_queue", "Cancel all pending files"),
    BotCommand("viewthumb", "View your thumbnail"),
    BotCommand("delthumb", "Delete your thumbnail"),
    BotCommand("set_caption", "Set custom caption"),
    BotCommand("see_caption", "View your caption"),
    BotCommand("del_caption", "Delete your caption"),
    BotCommand("metadata", "Turn on/off metadata"),
    BotCommand("set_main_channel", "[Admin] Set the Main channel"),
    BotCommand("set_save_channel", "[Admin] Set the backup/save channel"),
    BotCommand("set_stickers", "[Admin] Set Main/Sub channel stickers"),
    BotCommand("add_channel", "[Admin] Add a sub channel"),
    BotCommand("add_format", "[Admin] Add a format to a sub channel"),
    BotCommand("delete_format", "[Admin] Delete a format from a sub channel"),
    BotCommand("list_channels", "[Admin] List sub channels & formats"),
    BotCommand("auto_post", "[Admin] Start an auto-post session"),
    BotCommand("stop_auto_post", "[Admin] End the auto-post session"),
    BotCommand("add_admin", "[Owner] Add an admin"),
    BotCommand("remove_admin", "[Owner] Remove an admin"),
    BotCommand("admins", "List all admins"),
]


class Bot(Client):

    def __init__(self):
        super().__init__(
            name="codeflixbots",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN,
            workers=200,
            plugins={"root": "plugins"},
            sleep_threshold=15,
        )
        self.start_time = time.time()

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)
        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username
        self.uptime = Config.BOT_UPTIME

        try:
            await self.set_bot_commands(BOT_COMMANDS)
        except Exception as e:
            print(f"Failed to set bot commands: {e}")

        if Config.WEBHOOK:
            app = web.AppRunner(await web_server())
            await app.setup()
            await web.TCPSite(app, "0.0.0.0", PORT).start()
        print(f"{me.first_name} Is Started.....✨️")

        uptime_seconds = int(time.time() - self.start_time)
        uptime_string = str(timedelta(seconds=uptime_seconds))

        try:
            await self.send_photo(
                chat_id=Config.LOG_CHANNEL,
                photo=Config.START_PIC,
                caption=(
                    "**ᴀɴʏᴀ ɪs ʀᴇsᴛᴀʀᴛᴇᴅ ᴀɢᴀɪɴ  !**\n\n"
                    f"ɪ ᴅɪᴅɴ'ᴛ sʟᴇᴘᴛ sɪɴᴄᴇ: `{uptime_string}`"
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("ᴜᴘᴅᴀᴛᴇs", url="https://t.me/codeflix_bots")]]
                )
            )
        except Exception as e:
            print(f"Failed to send startup message: {e}")


Bot().run()
