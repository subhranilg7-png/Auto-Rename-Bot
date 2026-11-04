import re, os, time
from os import environ, getenv
id_pattern = re.compile(r'^.\d+$')


class Config(object):
    # pyro client config
    API_ID    = int(os.environ.get("API_ID", "0") or 0)
    API_HASH  = os.environ.get("API_HASH", "").strip()
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

    # database config
    DB_NAME = os.environ.get("DB_NAME", "Yato")
    DB_URL  = os.environ.get("DB_URL", "mongodb")
    PORT    = int(os.environ.get("PORT", "8080"))

    # other configs
    BOT_UPTIME  = time.time()
    START_PIC   = os.environ.get("START_PIC", "https://graph.org/file/29a3acbbab9de5f45a5fe.jpg")
    ADMIN       = [int(admin) if id_pattern.search(admin) else admin for admin in os.environ.get('ADMIN', '6497757690').split()]
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "-1001868871195"))
    DUMP_CHANNEL = int(os.environ.get("DUMP_CHANNEL", "-1001868871195"))

    # webhook configuration
    WEBHOOK = os.environ.get("WEBHOOK", "True").strip().lower() in ("1", "true", "yes", "on")
    
    # Force subscription - DISABLED
    FORCE_SUB_CHANNELS = []  # Empty list means no force subscription


class Txt(object):

    START_TXT = """<b>Hey! {}

I rename your files with your own format, caption and thumbnail — one after another.

<u>Quick start</u>
1. /settings — set your rename format (tap the buttons)
2. Send any photo to set a thumbnail
3. Send me your files</b>"""

    FILE_NAME_TXT = """<b>» Set your rename format</b>

<b>Variables:</b>
➲ <code>{{season}}</code> — season number
➲ <code>{{episode}}</code> — episode number
➲ <code>{{quality}}</code> — quality, e.g. 720p

<b>Example:</b>
<code>/autorename Overflow S{{season}}E{{episode}} [{{quality}}]</code>

Easier: open /settings → <b>Rename format</b>. You tap the variables and see a live preview of the new name."""

    ABOUT_TXT = f"""<b>❍ ᴍʏ ɴᴀᴍᴇ : <a href="https://t.me/codeflix_bots">ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ</a>
❍ ᴅᴇᴠᴇʟᴏᴩᴇʀ : <a href="https://t.me/cosmic_freak">ʏᴀᴛᴏ</a>
❍ ɢɪᴛʜᴜʙ : <a href="https://github.com/cosmic_freak">ʏᴀᴛᴏ</a>
❍ ʟᴀɴɢᴜᴀɢᴇ : <a href="https://www.python.org/">ᴘʏᴛʜᴏɴ</a>
❍ ᴅᴀᴛᴀʙᴀꜱᴇ : <a href="https://www.mongodb.com/">ᴍᴏɴɢᴏ ᴅʙ</a>
❍ ʜᴏꜱᴛᴇᴅ ᴏɴ : <a href="https://t.me/codeflix_bots">ᴠᴘs</a>
❍ ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ : <a href="https://t.me/animes_cruise">ᴀɴɪᴍᴇ ᴄʀᴜɪsᴇ</a>

➻ ᴄʟɪᴄᴋ ᴏɴ ᴛʜᴇ ʙᴜᴛᴛᴏɴs ɢɪᴠᴇɴ ʙᴇʟᴏᴡ ғᴏʀ ɢᴇᴛᴛɪɴɢ ʙᴀsɪᴄ ʜᴇʟᴩ ᴀɴᴅ ɪɴғᴏ ᴀʙᴏᴜᴛ ᴍᴇ.</b>"""

    THUMBNAIL_TXT = """<b>» Custom thumbnail</b>

➲ Send any photo to set it as your thumbnail (it is cropped to a square).
➲ /view_thumb — see your current thumbnail
➲ /del_thumb — delete it

Note: with no thumbnail saved, <b>videos</b> keep their own thumbnail; documents get none."""

    CAPTION_TXT = """<b>» Custom caption</b>

<b>Variables:</b>
{filename} — the new file name
{filesize} — file size
{duration} — duration (videos and audio)

➲ /set_caption — set a caption
➲ /see_caption — view it
➲ /del_caption — delete it
➲ /setmedia — choose how files are sent (document / video / audio)

Example: /set_caption {filename}"""

    PROGRESS_BAR = """\n
<b>» Size</b> : {1} | {2}
<b>» Done</b> : {0}%
<b>» Speed</b> : {3}/s
<b>» ETA</b> : {4} """

    DONATE_TXT = """<blockquote> ᴛʜᴀɴᴋs ғᴏʀ sʜᴏᴡɪɴɢ ɪɴᴛᴇʀᴇsᴛ ɪɴ ᴅᴏɴᴀᴛɪᴏɴ</blockquote>

<b><i>💞  ɪꜰ ʏᴏᴜ ʟɪᴋᴇ ᴏᴜʀ ʙᴏᴛ ꜰᴇᴇʟ ꜰʀᴇᴇ ᴛᴏ ᴅᴏɴᴀᴛᴇ ᴀɴʏ ᴀᴍᴏᴜɴᴛ ₹𝟷𝟶, ₹𝟸𝟶, ₹𝟻𝟶, ₹𝟷𝟶𝟶, ᴇᴛᴄ.</i></b>

ᴅᴏɴᴀᴛɪᴏɴs ᴀʀᴇ ʀᴇᴀʟʟʏ ᴀᴘᴘʀᴇᴄɪᴀᴛᴇᴅ ɪᴛ ʜᴇʟᴘs ɪɴ ʙᴏᴛ ᴅᴇᴠᴇʟᴏᴘᴍᴇɴᴛ

 <u>ʏᴏᴜ ᴄᴀɴ ᴀʟsᴏ ᴅᴏɴᴀᴛᴇ ᴛʜʀᴏᴜɢʜ ᴜᴘɪ</u>

 ᴜᴘɪ ɪᴅ : <code>LodaLassan@fam</code>

ɪғ ʏᴏᴜ ᴡɪsʜ ʏᴏᴜ ᴄᴀɴ sᴇɴᴅ ᴜs ss
ᴏɴ - @ProYato"""

    PREMIUM_TXT = """<b>ᴜᴘɢʀᴀᴅᴇ ᴛᴏ ᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ sᴇʀᴠɪᴄᴇ ᴀɴᴅ ᴇɴJᴏʏ ᴇxᴄʟᴜsɪᴠᴇ ғᴇᴀᴛᴜʀᴇs:
○ ᴜɴʟɪᴍɪᴛᴇᴅ Rᴇɴᴀᴍɪɴɢ: ʀᴇɴᴀᴍᴇ ᴀs ᴍᴀɴʏ ғɪʟᴇs ᴀs ʏᴏᴜ ᴡᴀɴᴛ ᴡɪᴛʜᴏᴜᴛ ᴀɴʏ ʀᴇsᴛʀɪᴄᴛɪᴏɴs.
○ ᴇᴀʀʟʏ Aᴄᴄᴇss: ʙᴇ ᴛʜᴇ ғɪʀsᴛ ᴛᴏ ᴛᴇsᴛ ᴀɴᴅ ᴜsᴇ ᴏᴜʀ ʟᴀᴛᴇsᴛ ғᴇᴀᴛᴜʀᴇs ʙᴇғᴏʀᴇ ᴀɴʏᴏɴᴇ ᴇʟsᴇ.

• ᴜꜱᴇ /plan ᴛᴏ ꜱᴇᴇ ᴀʟʟ ᴏᴜʀ ᴘʟᴀɴꜱ ᴀᴛ ᴏɴᴄᴇ.

➲ ғɪʀsᴛ sᴛᴇᴘ : ᴘᴀʏ ᴛʜᴇ ᴀᴍᴏᴜɴᴛ ᴀᴄᴄᴏʀᴅɪɴɢ ᴛᴏ ʏᴏᴜʀ ғᴀᴠᴏʀɪᴛᴇ ᴘʟᴀɴ ᴛᴏ ᴛʜɪs rohit162@fam ᴜᴘɪ ɪᴅ.

➲ secoɴᴅ sᴛᴇᴘ : ᴛᴀᴋᴇ ᴀ sᴄʀᴇᴇɴsʜᴏᴛ ᴏғ ʏᴏᴜʀ ᴘᴀʏᴍᴇɴᴛ ᴀɴᴅ sʜᴀʀᴇ ɪᴛ ᴅɪʀᴇᴄᴛʟʏ ʜᴇʀᴇ: @sewxiy

➲ ᴀʟᴛᴇʀɴᴀᴛɪᴠᴇ sᴛᴇᴘ : ᴏʀ ᴜᴘʟᴏᴀᴅ ᴛʜᴇ sᴄʀᴇᴇɴsʜᴏᴛ ʜᴇʀᴇ ᴀɴᴅ ʀᴇᴘʟʏ ᴡɪᴛʜ ᴛʜᴇ /bought ᴄᴏᴍᴍᴀɴᴅ.

Yᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴘʟᴀɴ ᴡɪʟʟ ʙᴇ ᴀᴄᴛɪᴠᴀᴛᴇᴅ ᴀғᴛᴇʀ ᴠᴇʀɪғɪᴄᴀᴛɪᴏɴ</b>"""

    PREPLANS_TXT = """<b>👋 bro,
    
🎖️ <u>ᴀᴠᴀɪʟᴀʙʟᴇ ᴘʟᴀɴs</u> :

Pʀɪᴄɪɴɢ:
➜ ᴍᴏɴᴛʜʟʏ ᴘʀᴇᴍɪᴜᴍ: ₹50/ᴍᴏɴᴛʜ
➜ ᴅᴀɪʟʏ ᴘʀᴇᴍɪᴜᴍ: ₹𝟻/ᴅᴀʏ
➜  ғᴏʀ ʙᴏᴛ ʜᴏsᴛɪɴɢ: ᴄᴏɴᴛᴀᴄᴛ @ProYato

➲ ᴜᴘɪ ɪᴅ - <code>LodaLassan@fam</code>

‼️ᴜᴘʟᴏᴀᴅ ᴛʜᴇ ᴘᴀʏᴍᴇɴᴛ sᴄʀᴇᴇɴsʜᴏᴛ ʜᴇʀᴇ ᴀɴᴅ ʀᴇᴘʟʏ ᴡɪᴛʜ ᴛʜᴇ /bought ᴄᴏᴍᴍᴀɴᴅ.</b>"""

    HELP_TXT = """<b>Help</b>

Everything personal is in <b>/settings</b>: rename format, caption, thumbnail, metadata, and how files are sent.
Send me files and I rename them one after another. /queue shows progress and lets you cancel files.

Pick a topic below, or use /commands for the full list."""

    SEND_METADATA = """
<b>--Metadata Settings:--</b>

➜ /metadata: Turn on or off metadata.

<b>Description</b> : Metadata will change MKV video files including all audio, streams, and subtitle titles."""

    SOURCE_TXT = """
<b>ʜᴇʏ,
 ᴛʜɪs ɪs ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ʙᴏᴛ,
ᴀɴ ᴏᴩᴇɴ sᴏᴜʀᴄᴇ ᴛᴇʟᴇɢʀᴀᴍ ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ʙᴏᴛ.</b>

ᴡʀɪᴛᴛᴇɴ ɪɴ ᴩʏᴛʜᴏɴ ᴡɪᴛʜ ᴛʜᴇ ʜᴇʟᴩ ᴏғ :
[ᴩʏʀᴏɢʀᴀᴍ](https://github.com/pyrogram/pyrogram)
ᴀɴᴅ ᴜsɪɴɢ [ᴍᴏɴɢᴏ](https://cloud.mongodb.com) ᴀs ᴅᴀᴛᴀʙᴀsᴇ.

<b>ʜᴇʀᴇ ɪs ᴍʏ sᴏᴜʀᴄᴇ ᴄᴏᴅᴇ :</b> [ɢɪᴛʜᴜʙ](https://github.com/codeflix_bots/autorenamebot)

ᴀᴜᴛᴏ ʀᴇɴᴀᴍᴇ ʙᴏᴛ ɪs ʟɪᴄᴇɴsᴇᴅ ᴜɴᴅᴇʀ ᴛʜᴇ [ᴍɪᴛ ʟɪᴄᴇɴsᴇ](https://github.com/codeflix_bots/autorenamebot/blob/main/LICENSE).
© 2024 | [sᴜᴘᴘᴏʀᴛ ᴄʜᴀᴛ](https://t.me/codeflixsupport), ᴀʟʟ ʀɪɢʜᴛs ʀᴇsᴇʀᴠᴇᴅ."""

    META_TXT = """
**ᴍᴀɴᴀɢɪɴɢ ᴍᴇᴛᴀᴅᴀᴛᴀ ғᴏʀ ʏᴏᴜʀ ᴠɪᴅᴇᴏs ᴀɴᴅ ғɪʟᴇs**

**ᴠᴀʀɪᴏᴜꜱ ᴍᴇᴛᴀᴅᴀᴛᴀ:**

- **ᴛɪᴛʟᴇ**: Descriptive title of the media.
- **ᴀᴜᴛʜᴏʀ**: The creator or owner of the media.
- **ᴀʀᴛɪꜱᴛ**: The artist associated with the media.
- **ᴀᴜᴅɪᴏ**: Title or description of audio content.
- **ꜱᴜʙᴛɪᴛʟᴇ**: Title of subtitle content.
- **ᴠɪᴅᴇᴏ**: Title or description of video content.

**ᴄᴏᴍᴍᴀɴᴅꜱ ᴛᴏ ᴛᴜʀɴ ᴏɴ ᴏғғ ᴍᴇᴛᴀᴅᴀᴛᴀ:**
➜ /metadata: Turn on or off metadata.

**ᴄᴏᴍᴍᴀɴᴅꜱ ᴛᴏ ꜱᴇᴛ ᴍᴇᴛᴀᴅᴀᴛᴀ:**

➜ /settitle: Set a custom title of media.
➜ /setauthor: Set the author.
➜ /setartist: Set the artist.
➜ /setaudio: Set audio title.
➜ /setsubtitle: Set subtitle title.
➜ /setvideo: Set video title.

**ᴇxᴀᴍᴘʟᴇ:** /settitle Your Title Here

**ᴜꜱᴇ ᴛʜᴇꜱᴇ ᴄᴏᴍᴍᴀɴᴅꜱ ᴛᴏ ᴇɴʀɪᴄʜ ʏᴏᴜʀ ᴍᴇᴅɪᴀ ᴡɪᴛʜ ᴀᴅᴅɪᴛɪᴏɴᴀʟ ᴍᴇᴛᴀᴅᴀᴛᴀ ɪɴꜰᴏʀᴍᴀᴛɪᴏɴ!**
"""
