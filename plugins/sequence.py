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
sequence_collections = {}


# ── Detection helpers ─────────────────────────────────────────────────────────

def seq_extract_episode(text):
    if not text:
        return None
    patterns = [
        r'\[E(\d+)\s*-',
        r'S\d+[\s-]*E(\d+)',
        r'(?:E|EP)(\d+)',
        r'Episode\s*(\d+)',
        r'\[S\d+[\s-]+(\d+)\]',
        r'[-_\s](\d{2,3})[-_\s]',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None

def seq_extract_season(text):
    if not text:
        return None
    patterns = [
        r'S(\d+)[\s-]*E\d+',
        r'\[S(\d+)\]',
        r'Season\s*(\d+)',
        r'\bS(\d+)\b',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None

def seq_extract_quality(text):
    if not text:
        return 'unknown'
    patterns = [
        (r'\b(4k|2160p)\b', '4k'),
        (r'\b(2k|1440p)\b', '2k'),
        (r'\b(1080p)\b', '1080p'),
        (r'\b(720p)\b', '720p'),
        (r'\b(576p)\b', '576p'),
        (r'\b(480p)\b', '480p'),
        (r'\[(1080p|720p|576p|480p|4k|2160p)\]', None),
    ]
    for p, val in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return val if val else m.group(1).lower()
    return 'unknown'

def get_quality_rank(quality):
    return QUALITY_RANK.get((quality or 'unknown').lower(), 99)

def sort_sequence(files, mode):
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


# ── /bot_mode ─────────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('bot_mode'))
async def bot_mode(client, message):
    current = await codeflixbots.get_bot_mode(message.from_user.id)
    await message.reply_text(
        f"**🤖 Current Mode: `{current.upper()}`**\n\nSelect a mode:",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Auto Rename Mode", callback_data="mode_autorename"),
                InlineKeyboardButton("📋 Sequence Mode", callback_data="mode_sequence")
            ]
        ])
    )


@Client.on_callback_query(filters.regex("^mode_"))
async def mode_callback(client, callback_query: CallbackQuery):
    try:
        user_id = callback_query.from_user.id
        mode = callback_query.data.replace("mode_", "")
        await codeflixbots.set_bot_mode(user_id, mode)
        mode_name = "🔄 Auto Rename Mode" if mode == "autorename" else "📋 Sequence Mode"
        await callback_query.message.edit_text(f"**✅ Switched to {mode_name}**")
    except Exception:
        pass


# ── /sequence_mode ────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('sequence_mode'))
async def sequence_mode_cmd(client, message):
    current = await codeflixbots.get_sequence_mode(message.from_user.id)
    await message.reply_text(
        f"**📋 Current Sequence Mode: `{current.upper()}`**\n\nHow would you like to sequence?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🎬 Episode Wise", callback_data="seq_episode"),
                InlineKeyboardButton("🎞 Quality Wise", callback_data="seq_quality"),
                InlineKeyboardButton("📺 Season Wise", callback_data="seq_season")
            ]
        ])
    )


@Client.on_callback_query(filters.regex("^seq_"))
async def seq_mode_callback(client, callback_query: CallbackQuery):
    try:
        user_id = callback_query.from_user.id
        mode = callback_query.data.replace("seq_", "")
        await codeflixbots.set_sequence_mode(user_id, mode)
        names = {
            'episode': '🎬 Episode Wise',
            'quality': '🎞 Quality Wise',
            'season': '📺 Season Wise'
        }
        await callback_query.message.edit_text(f"**✅ Sequence mode set to {names[mode]}**")
    except Exception:
        pass


# ── /start_sequence ───────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('start_sequence'))
async def start_sequence(client, message):
    user_id = message.from_user.id
    bot_mode_val = await codeflixbots.get_bot_mode(user_id)
    if bot_mode_val != 'sequence':
        return await message.reply_text(
            "**❌ Please switch to Sequence Mode first using /bot_mode**"
        )
    sequence_collections[user_id] = []
    await message.reply_text(
        "**✅ Sequence started! Send your files now...\n\nSend /end_sequence when done.**"
    )


# ── File collector — documents, videos, and audio ────────────────────────────

@Client.on_message(
    filters.private &
    (filters.document | filters.video | filters.audio) &
    ~filters.sticker,
    group=1
)
async def collect_sequence_file(client, message):
    user_id = message.from_user.id

    # Only handle if in sequence mode
    bot_mode_val = await codeflixbots.get_bot_mode(user_id)
    if bot_mode_val != 'sequence':
        return

    if user_id not in sequence_collections:
        return await message.reply_text(
            "**❌ Please send /start_sequence first**"
        )

    # Get filename
    file_name = ""
    if message.document:
        file_name = message.document.file_name or ""
    elif message.video:
        file_name = message.video.file_name or ""
    elif message.audio:
        file_name = message.audio.file_name or ""

    caption = message.caption or ""
    combined = f"{file_name} {caption}".strip()

    episode = seq_extract_episode(combined)
    season = seq_extract_season(combined)
    quality = seq_extract_quality(combined)

    file_entry = {
        'message': message,
        'episode': episode,
        'season': season,
        'quality': quality,
        'file_name': file_name,
        'caption': caption
    }

    sequence_collections[user_id].append(file_entry)

    detected = []
    if season:
        detected.append(f"S{season:02d}")
    if episode:
        detected.append(f"E{episode:02d}")
    if quality and quality != 'unknown':
        detected.append(quality)

    detected_text = " | ".join(detected) if detected else "Nothing detected — will use send order"
    count = len(sequence_collections[user_id])
    await message.reply_text(
        f"**✅ File #{count} collected**\n`{detected_text}`",
        quote=True
    )


# ── /end_sequence ─────────────────────────────────────────────────────────────

@Client.on_message(filters.private & filters.command('end_sequence'))
async def end_sequence(client, message):
    user_id = message.from_user.id

    if user_id not in sequence_collections or not sequence_collections[user_id]:
        return await message.reply_text(
            "**❌ No files collected. Send /start_sequence first.**"
        )

    files = sequence_collections[user_id]
    seq_mode = await codeflixbots.get_sequence_mode(user_id)

    # Assign fallback order for files with no episode detected
    for i, f in enumerate(files):
        if f['episode'] is None:
            f['episode'] = 1000 + i

    sorted_files = sort_sequence(files, seq_mode)

    msg = await message.reply_text(
        f"**📋 Sequencing {len(sorted_files)} files in `{seq_mode}` mode...**"
    )

    success = 0
    failed = 0
    for i, f in enumerate(sorted_files, 1):
        try:
            await f['message'].forward(user_id)
            success += 1
        except Exception as e:
            failed += 1
            await message.reply_text(f"**❌ Failed to forward file #{i}: {e}**")

    sequence_collections.pop(user_id, None)

    try:
        await msg.edit(
            f"**✅ Done! {success} files forwarded in `{seq_mode}` sequence.**"
            + (f"\n⚠️ {failed} files failed." if failed else "")
            + "\n\nStill in Sequence Mode. Use /bot_mode to switch."
        )
    except:
        pass
