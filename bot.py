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
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
import os
import time

_missing = [n for n, v in (("API_ID", Config.API_ID), ("API_HASH", Config.API_HASH),
                           ("BOT_TOKEN", Config.BOT_TOKEN)) if not v]
if _missing:
    raise SystemExit(
        f"Missing required environment variable(s): {', '.join(_missing)}. "
        "Set them before starting the bot (e.g. `export API_ID=... API_HASH=... BOT_TOKEN=...`)."
    )

PORT = Config.PORT

async def _all_admin_ids():
    try:
        from helper.database import codeflixbots
        return [int(a) for a in await codeflixbots.get_admins()]
    except Exception:
        return []


def _menu(commands):
    return [BotCommand(c, d[:250]) for c, d in commands]




def _saved_transmissions():
    """The value chosen in Admin panel -> Settings wins over the environment variable."""
    from helper.database import read_setting_sync
    saved = read_setting_sync("max_transmissions")
    return saved if saved else Config.MAX_TRANSMISSIONS


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
            max_concurrent_transmissions=_saved_transmissions(),
        )
        self.start_time = time.time()

    async def start(self, *args, **kwargs):
        await super().start(*args, **kwargs)
        from helper.database import codeflixbots
        await codeflixbots.ping()
        import helper.transfer as _transfer
        _transfer.STALL_SECONDS = await codeflixbots.get_transfer_stall(_transfer.STALL_SECONDS)
        me = await self.get_me()
        self.mention = me.mention
        self.username = me.username
        self.uptime = Config.BOT_UPTIME

        try:
            from helper.commands_registry import USER_COMMANDS, ADMIN_COMMANDS
            from pyrogram.types import BotCommandScopeChat
            await self.set_bot_commands(_menu(USER_COMMANDS))
            for admin_id in set(Config.ADMIN or []) | set(await _all_admin_ids()):
                try:
                    await self.set_bot_commands(_menu(USER_COMMANDS + ADMIN_COMMANDS), scope=BotCommandScopeChat(admin_id))
                except Exception as e:
                    print(f"Could not set the admin command menu for {admin_id}: {e}")
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
            from helper.database import codeflixbots as _db
            from helper.patterns import reload_patterns
            await reload_patterns(_db)
            from plugins.file_rename import restore_queues
            from plugins.auto_post import restore_autopost
            asyncio.create_task(restore_queues(self))
            asyncio.create_task(restore_autopost(self))
        except Exception as e:
            print(f"Failed to restore queue: {e}")

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
