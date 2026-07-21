import random
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from helper.database import codeflixbots
from config import *
from config import Config


# Start Command Handler
@Client.on_message(filters.private & filters.command("start"))
async def start(client, message: Message):
    user = message.from_user
    await codeflixbots.add_user(client, message)

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs •", callback_data='commands')
        ],
        [
            InlineKeyboardButton('• ᴜᴘᴅᴀᴛᴇs', url='https://t.me/Codeflix_Bots'),
            InlineKeyboardButton('sᴜᴘᴘᴏʀᴛ •', url='https://t.me/CodeflixSupport')
        ],
        [
            InlineKeyboardButton('• ᴀʙᴏᴜᴛ', callback_data='about'),
            InlineKeyboardButton('sᴏᴜʀᴄᴇ •', callback_data='source')
        ]
    ])

    if Config.START_PIC:
        await message.reply_photo(
            Config.START_PIC,
            caption=Txt.START_TXT.format(user.mention),
            reply_markup=buttons
        )
    else:
        await message.reply_text(
            text=Txt.START_TXT.format(user.mention),
            reply_markup=buttons,
            disable_web_page_preview=True
        )


# /commands command
@Client.on_message(filters.private & filters.command("commands"))
async def commands_cmd(client, message: Message):
    await message.reply_text(
        text=COMMANDS_TXT,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("• ʜᴏᴍᴇ •", callback_data="home")]
        ])
    )


# Callback Query Handler
@Client.on_callback_query()
async def cb_handler(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    if data == "home":
        try:
            await query.message.edit_text(
                text=Txt.START_TXT.format(query.from_user.mention),
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅs •", callback_data='commands')],
                    [InlineKeyboardButton('• ᴜᴘᴅᴀᴛᴇs', url='https://t.me/Codeflix_Bots'), InlineKeyboardButton('sᴜᴘᴘᴏʀᴛ •', url='https://t.me/CodeflixSupport')],
                    [InlineKeyboardButton('• ᴀʙᴏᴜᴛ', callback_data='about'), InlineKeyboardButton('sᴏᴜʀᴄᴇ •', callback_data='source')]
                ])
            )
        except:
            pass

    elif data == "commands":
        try:
            await query.message.edit_text(
                text=COMMANDS_TXT,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ʜᴏᴍᴇ •", callback_data="home")]
                ])
            )
        except:
            pass

    elif data == "caption":
        try:
            await query.message.edit_text(
                text=Txt.CAPTION_TXT,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url='https://t.me/CodeflixSupport'), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
                ])
            )
        except:
            pass

    elif data == "help":
        try:
            await query.message.edit_text(
                text=Txt.HELP_TXT.format(client.mention),
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ғᴏʀᴍᴀᴛ •", callback_data='file_names')],
                    [InlineKeyboardButton('• ᴛʜᴜᴍʙɴᴀɪʟ', callback_data='thumbnail'), InlineKeyboardButton('ᴄᴀᴘᴛɪᴏɴ •', callback_data='caption')],
                    [InlineKeyboardButton('• ᴍᴇᴛᴀᴅᴀᴛᴀ', callback_data='meta'), InlineKeyboardButton('ᴅᴏɴᴀᴛᴇ •', callback_data='donate')],
                    [InlineKeyboardButton('• ʜᴏᴍᴇ', callback_data='home')]
                ])
            )
        except:
            pass

    elif data == "meta":
        try:
            await query.message.edit_text(
                text=Txt.SEND_METADATA,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
                ])
            )
        except:
            pass

    elif data == "donate":
        try:
            await query.message.edit_text(
                text=Txt.DONATE_TXT,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ʙᴀᴄᴋ", callback_data="help"), InlineKeyboardButton("ᴏᴡɴᴇʀ •", url='https://t.me/sewxiy')]
                ])
            )
        except:
            pass

    elif data == "file_names":
        try:
            format_template = await codeflixbots.get_format_template(user_id)
            await query.message.edit_text(
                text=Txt.FILE_NAME_TXT.format(format_template=format_template),
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
                ])
            )
        except:
            pass

    elif data == "thumbnail":
        try:
            await query.message.edit_caption(
                caption=Txt.THUMBNAIL_TXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
                ])
            )
        except:
            pass

    elif data == "metadatax":
        try:
            await query.message.edit_caption(
                caption=Txt.SEND_METADATA,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="help")]
                ])
            )
        except:
            pass

    elif data == "source":
        try:
            await query.message.edit_caption(
                caption=Txt.SOURCE_TXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴀᴄᴋ •", callback_data="home")]
                ])
            )
        except:
            pass

    elif data == "premiumx":
        try:
            await query.message.edit_caption(
                caption=Txt.PREMIUM_TXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ʙᴀᴄᴋ", callback_data="help"), InlineKeyboardButton("ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", url='https://t.me/sewxiy')]
                ])
            )
        except:
            pass

    elif data == "plans":
        try:
            await query.message.edit_caption(
                caption=Txt.PREPLANS_TXT,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• ᴄʟᴏsᴇ", callback_data="close"), InlineKeyboardButton("ʙᴜʏ ᴘʀᴇᴍɪᴜᴍ •", url='https://t.me/sewxiy')]
                ])
            )
        except:
            pass

    elif data == "about":
        try:
            await query.message.edit_text(
                text=Txt.ABOUT_TXT,
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("• sᴜᴘᴘᴏʀᴛ", url='https://t.me/CodeflixSupport'), InlineKeyboardButton("ᴄᴏᴍᴍᴀɴᴅs •", callback_data="commands")],
                    [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", url='https://t.me/cosmic_freak'), InlineKeyboardButton("ɴᴇᴛᴡᴏʀᴋ •", url='https://t.me/otakuflix_network')],
                    [InlineKeyboardButton("• ʙᴀᴄᴋ •", callback_data="home")]
                ])
            )
        except:
            pass

    elif data == "close":
        try:
            await query.message.delete()
            await query.message.reply_to_message.delete()
            await query.message.continue_propagation()
        except:
            try:
                await query.message.delete()
            except:
                pass


# Donation Command Handler
@Client.on_message(filters.command("donate"))
async def donation(client, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="ʙᴀᴄᴋ", callback_data="help"),
         InlineKeyboardButton(text="ᴏᴡɴᴇʀ", url='https://t.me/sewxiy')]
    ])
    yt = await message.reply_photo(
        photo='https://graph.org/file/1919fe077848bd0783d4c.jpg',
        caption=Txt.DONATE_TXT,
        reply_markup=buttons
    )
    await asyncio.sleep(300)
    await yt.delete()
    await message.delete()


# Premium Command Handler
@Client.on_message(filters.command("premium"))
async def getpremium(bot, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("ᴏᴡɴᴇʀ", url="https://t.me/sewxiy"),
         InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")]
    ])
    yt = await message.reply_photo(
        photo='https://graph.org/file/feebef43bbdf76e796b1b.jpg',
        caption=Txt.PREMIUM_TXT,
        reply_markup=buttons
    )
    await asyncio.sleep(300)
    await yt.delete()
    await message.delete()


# Plan Command Handler
@Client.on_message(filters.command("plan"))
async def premium(bot, message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("sᴇɴᴅ ss", url="https://t.me/sewxiy"),
         InlineKeyboardButton("ᴄʟᴏsᴇ", callback_data="close")]
    ])
    yt = await message.reply_photo(
        photo='https://graph.org/file/8b50e21db819f296661b7.jpg',
        caption=Txt.PREPLANS_TXT,
        reply_markup=buttons
    )
    await asyncio.sleep(300)
    await yt.delete()
    await message.delete()


# Bought Command Handler
@Client.on_message(filters.command("bought") & filters.private)
async def bought(client, message):
    msg = await message.reply('Wait im checking...')
    replied = message.reply_to_message
    if not replied:
        await msg.edit(
            "<b>Please reply with the screenshot of your payment.\n\n"
            "Upload your screenshot first, then reply to it using /bought</b>"
        )
    elif replied.photo:
        await client.send_photo(
            chat_id=Config.LOG_CHANNEL,
            photo=replied.photo.file_id,
            caption=(
                f'<b>User - {message.from_user.mention}\n'
                f'User id - <code>{message.from_user.id}</code>\n'
                f'Username - <code>{message.from_user.username}</code>\n'
                f'Name - <code>{message.from_user.first_name}</code></b>'
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Close", callback_data="close_data")]
            ])
        )
        await msg.edit_text('<b>Your screenshot has been sent to Admins ✅</b>')


# Help Command Handler
@Client.on_message(filters.private & filters.command("help"))
async def help_command(client, message):
    bot = await client.get_me()
    mention = bot.mention
    await message.reply_text(
        text=Txt.HELP_TXT.format(mention=mention),
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("• ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ғᴏʀᴍᴀᴛ •", callback_data='file_names')],
            [InlineKeyboardButton('• ᴛʜᴜᴍʙɴᴀɪʟ', callback_data='thumbnail'),
             InlineKeyboardButton('ᴄᴀᴘᴛɪᴏɴ •', callback_data='caption')],
            [InlineKeyboardButton('• ᴍᴇᴛᴀᴅᴀᴛᴀ', callback_data='meta'),
             InlineKeyboardButton('ᴅᴏɴᴀᴛᴇ •', callback_data='donate')],
            [InlineKeyboardButton('• ʜᴏᴍᴇ', callback_data='home')]
        ])
    )


# Commands text
COMMANDS_TXT = """<b>📋 ᴀʟʟ ᴀᴠᴀɪʟᴀʙʟᴇ ᴄᴏᴍᴍᴀɴᴅs :</b>

<b>🔄 ʀᴇɴᴀᴍᴇ :</b>
➲ /autorename — sᴇᴛ ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ғᴏʀᴍᴀᴛ

<b>📋 ǫᴜᴇᴜᴇ :</b>
➲ /queue — ᴠɪᴇᴡ ʏᴏᴜʀ ǫᴜᴇᴜᴇ sᴛᴀᴛᴜs
➲ /cancel_queue — ᴄᴀɴᴄᴇʟ ᴀʟʟ ᴘᴇɴᴅɪɴɢ ғɪʟᴇs

<b>🖼 ᴛʜᴜᴍʙɴᴀɪʟ :</b>
➲ /viewthumb — ᴠɪᴇᴡ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ
➲ /delthumb — ᴅᴇʟᴇᴛᴇ ʏᴏᴜʀ ᴛʜᴜᴍʙɴᴀɪʟ

<b>📝 ᴄᴀᴘᴛɪᴏɴ :</b>
➲ /set_caption — sᴇᴛ ᴄᴜsᴛᴏᴍ ᴄᴀᴘᴛɪᴏɴ
➲ /see_caption — ᴠɪᴇᴡ ʏᴏᴜʀ ᴄᴀᴘᴛɪᴏɴ
➲ /del_caption — ᴅᴇʟᴇᴛᴇ ʏᴏᴜʀ ᴄᴀᴘᴛɪᴏɴ

<b>🎞 ᴍᴇᴛᴀᴅᴀᴛᴀ :</b>
➲ /metadata — ᴛᴜʀɴ ᴏɴ/ᴏғғ ᴍᴇᴛᴀᴅᴀᴛᴀ
➲ /settitle — sᴇᴛ ᴛɪᴛʟᴇ
➲ /setauthor — sᴇᴛ ᴀᴜᴛʜᴏʀ
➲ /setartist — sᴇᴛ ᴀʀᴛɪsᴛ
➲ /setaudio — sᴇᴛ ᴀᴜᴅɪᴏ ᴛɪᴛʟᴇ
➲ /setsubtitle — sᴇᴛ sᴜʙᴛɪᴛʟᴇ ᴛɪᴛʟᴇ
➲ /setvideo — sᴇᴛ ᴠɪᴅᴇᴏ ᴛɪᴛʟᴇ

<b>📡 ᴄʜᴀɴɴᴇʟ sᴇᴛᴜᴘ (ᴀᴅᴍɪɴ ᴏɴʟʏ) :</b>
➲ /set_main_channel — sᴇᴛ ᴛʜᴇ ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ
➲ /set_save_channel — sᴇᴛ ᴛʜᴇ ʙᴀᴄᴋᴜᴘ/sᴀᴠᴇ ᴄʜᴀɴɴᴇʟ
➲ /set_stickers — sᴇᴛ ᴛʜᴇ ᴍᴀɪɴ/sᴜʙ ᴄʜᴀɴɴᴇʟ sᴛɪᴄᴋᴇʀs
➲ /add_channel — ᴀᴅᴅ ᴀ sᴜʙ ᴄʜᴀɴɴᴇʟ (ᴛʜᴜᴍʙ, ғᴏʀᴍᴀᴛ, ᴘᴏsᴛs)
➲ /add_format — ᴀᴅᴅ ᴀɴᴏᴛʜᴇʀ ғᴏʀᴍᴀᴛ ᴛᴏ ᴀɴ ᴇxɪsᴛɪɴɢ sᴜʙ ᴄʜᴀɴɴᴇʟ
➲ /delete_format — ᴅᴇʟᴇᴛᴇ ᴀ ғᴏʀᴍᴀᴛ ғʀᴏᴍ ᴀ sᴜʙ ᴄʜᴀɴɴᴇʟ
➲ /list_channels — ʟɪsᴛ ᴀʟʟ sᴜʙ ᴄʜᴀɴɴᴇʟs & ᴛʜᴇɪʀ ғᴏʀᴍᴀᴛs

<b>🚀 ᴀᴜᴛᴏ-ᴘᴏsᴛ (ᴀᴅᴍɪɴ ᴏɴʟʏ) :</b>
➲ /auto_post — sᴛᴀʀᴛ ᴀɴ ᴀᴜᴛᴏ-ᴘᴏsᴛ sᴇssɪᴏɴ ᴛᴏ ᴀ sᴜʙ ᴄʜᴀɴɴᴇʟ
➲ /stop_auto_post — ᴇɴᴅ ᴛʜᴇ ᴄᴜʀʀᴇɴᴛ ᴀᴜᴛᴏ-ᴘᴏsᴛ sᴇssɪᴏɴ

<b>👮 ᴀᴅᴍɪɴ ᴍᴀɴᴀɢᴇᴍᴇɴᴛ :</b>
➲ /add_admin — ᴀᴅᴅ ᴀɴ ᴀᴅᴍɪɴ (ᴏᴡɴᴇʀ ᴏɴʟʏ)
➲ /remove_admin — ʀᴇᴍᴏᴠᴇ ᴀɴ ᴀᴅᴍɪɴ (ᴏᴡɴᴇʀ ᴏɴʟʏ)
➲ /admins — ʟɪsᴛ ᴀʟʟ ᴀᴅᴍɪɴs

<b>ℹ️ ɢᴇɴᴇʀᴀʟ :</b>
➲ /start — sᴛᴀʀᴛ ᴛʜᴇ ʙᴏᴛ
➲ /help — ʜᴇʟᴘ ᴍᴇɴᴜ
➲ /commands — sʜᴏᴡ ᴛʜɪs ʟɪsᴛ
➲ /donate — sᴜᴘᴘᴏʀᴛ ᴅᴇᴠᴇʟᴏᴘᴇʀ
➲ /premium — ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴs
➲ /plan — ᴠɪᴇᴡ ᴘʟᴀɴs"""
