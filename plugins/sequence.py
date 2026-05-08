import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from helper.database import codeflixbots

# ── Quality rank for sorting ──────────────────────────────────────────────────
QUALITY_RANK = {
    '480p': 1,
    '576p': 2,
    '720p': 3,
    '1080p': 4,
    '2k': 5,
    '1440p': 5,
    '4k': 6,
    '2160p': 6,
    'unknown': 99
}

# ── In-memory collection store ────────────────────────────────────────────────
# { user_id: [ { 'message': msg, 'season': int, 'episode': int, 'quality': str }, ... ] }
sequence_collections = {}

# ── Pending manual input store ────────────────────────────────────────────────
# { user_id: { 'field': 'season'/'episode'/'quality', 'data': {...} } }
pending_sequence_input = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_episode(text):
    if not text:
        return None
    patterns = [
        r'(?:E|EP|Episode)[\s\-_]*(\d+)',
        r'\[E(\d+)',
        r'S\d+[\s\-_]*E(\d+)',
        r'\[S\d+[\s\-]*(\d+)\]',
        r'[-_\s](\d{2,3})[-_\s]',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None

def extract_season(text):
    if not text:
        return None
    patterns = [
        r'S(\d+)[\s\-_]*E',
        r'Season[\s_]*(\d+)',
        r'\[S(\d+)\]',
        r'S(\d+)[\s\-_]*\d+',
        r'S(\d+)',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None

def extract_quality(text):
    if not text:
        return 'Unknown'
    patterns = [
        r'\b(4k|2160p)\b',
        r'\b(2k|1440p)\b',
        r'\b(1080p)\b',
        r'\b(720p)\b',
        r'\b(576p)\b',
        r'\b(480p)\b',
        r'\[(4k|2160p|2k|1440p|1080p|720p|576p|480p)\]',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).lower()
    return 'Unknown'

def get_quality_rank(quality):
    if not quality:
        return 99
    return QUALITY_RANK.get(quality.lower(), 99)

def sort_sequence(files, mode):
    """
    Episode wise : Season → Episode → Quality
    Quality wise : Season → Quality → Episode
    Season wise  : Quality → Season → Episode
    """
    def sort_key(f):
        s = f.get('season') or 999
        e = f.get('episode') or 999
        q = get_quality_rank(f.get('quality'))
        if mode == 'episode':
            return (s, e, q)
        elif mode == 'quality':
            return (s, q, e)
        elif mode == 'season':
            return (q, s, e)
        return (s, e, q)

    return sorted(files, key=sort_key)


# ── /bot_mode command ─────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('bot_mode'))
async def bot_mode(client, message):
    current = await codeflixbots.get_bot_mode(message.from_user.id)
    text = f"**🤖 Current Mode: `{current.upper()}`**\n\nSelect a mode:"
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Auto Rename Mode", callback_data="mode_autorename"),
            InlineKeyboardButton("📋 Sequence Mode", callback_data="mode_sequence")
        ]
    ])
    await message.reply_text(text, reply_markup=buttons)


@Client.on_callback_query(filters.regex("^mode_"))
async def mode_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    mode = callback_query.data.replace("mode_", "")
    await codeflixbots.set_bot_mode(user_id, mode)
    mode_name = "🔄 Auto Rename Mode" if mode == "autorename" else "📋 Sequence Mode"
    await callback_query.message.edit_text(f"**✅ Switched to {mode_name}**")


# ── /sequence_mode command ────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('sequence_mode'))
async def sequence_mode_cmd(client, message):
    current = await codeflixbots.get_sequence_mode(message.from_user.id)
    text = f"**📋 Current Sequence Mode: `{current.upper()}`**\n\nHow would you like to sequence?"
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 Episode Wise", callback_data="seq_episode"),
            InlineKeyboardButton("🎞 Quality Wise", callback_data="seq_quality"),
            InlineKeyboardButton("📺 Season Wise", callback_data="seq_season")
        ]
    ])
    await message.reply_text(text, reply_markup=buttons)


@Client.on_callback_query(filters.regex("^seq_"))
async def seq_mode_callback(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    mode = callback_query.data.replace("seq_", "")
    await codeflixbots.set_sequence_mode(user_id, mode)
    names = {'episode': '🎬 Episode Wise', 'quality': '🎞 Quality Wise', 'season': '📺 Season Wise'}
    await callback_query.message.edit_text(f"**✅ Sequence mode set to {names[mode]}**")


# ── /start_sequence command ───────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('start_sequence'))
async def start_sequence(client, message):
    user_id = message.from_user.id
    bot_mode = await codeflixbots.get_bot_mode(user_id)
    if bot_mode != 'sequence':
        return await message.reply_text("**❌ Please switch to Sequence Mode first using /bot_mode**")
    sequence_collections[user_id] = []
    await message.reply_text("**✅ Sequence started! Send your files now...\n\nSend /end_sequence when done.**")


# ── File collector in sequence mode ──────────────────────────────────────────

@Client.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def collect_sequence_file(client, message):
    user_id = message.from_user.id
    bot_mode = await codeflixbots.get_bot_mode(user_id)

    if bot_mode != 'sequence':
        return  # Let file_rename.py handle it

    if user_id not in sequence_collections:
        return await message.reply_text("**❌ Please send /start_sequence first**")

    # Get filename and caption
    if message.document:
        file_name = message.document.file_name or ""
    elif message.video:
        file_name = message.video.file_name or ""
    elif message.audio:
        file_name = message.audio.file_name or ""
    else:
        file_name = ""

    caption = message.caption or ""
    combined = f"{file_name} {caption}"

    # Extract info
    episode = extract_episode(combined)
    season = extract_season(combined)
    quality = extract_quality(combined)

    file_entry = {
        'message': message,
        'episode': episode,
        'season': season,
        'quality': quality,
        'file_name': file_name,
        'caption': caption
    }

    sequence_collections[user_id].append(file_entry)

    # Notify user what was detected
    detected = []
    if season:
        detected.append(f"Season: {season}")
    if episode:
        detected.append(f"Episode: {episode}")
    if quality and quality != 'Unknown':
        detected.append(f"Quality: {quality}")

    detected_text = " | ".join(detected) if detected else "Nothing detected — will use send order"
    count = len(sequence_collections[user_id])
    await message.reply_text(f"**✅ File #{count} collected**\n`{detected_text}`")


# ── /end_sequence command ─────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('end_sequence'))
async def end_sequence(client, message):
    user_id = message.from_user.id

    if user_id not in sequence_collections or not sequence_collections[user_id]:
        return await message.reply_text("**❌ No files collected. Send /start_sequence first.**")

    files = sequence_collections[user_id]
    seq_mode = await codeflixbots.get_sequence_mode(user_id)

    # Assign send order for files with no episode detected
    for i, f in enumerate(files):
        if f['episode'] is None:
            f['episode'] = 1000 + i  # Push to end

    # Sort files
    sorted_files = sort_sequence(files, seq_mode)

    msg = await message.reply_text(f"**📋 Sequencing {len(sorted_files)} files in `{seq_mode}` mode...**")

    # Forward files in sorted order
    for i, f in enumerate(sorted_files, 1):
        try:
            await f['message'].forward(user_id)
        except Exception as e:
            await message.reply_text(f"**❌ Failed to forward file #{i}: {e}**")

    # Clear collection — stay in sequence mode
    sequence_collections.pop(user_id, None)
    await msg.edit(f"**✅ Done! {len(sorted_files)} files forwarded in sequence.**\n\nStill in Sequence Mode. Use /bot_mode to switch.")
