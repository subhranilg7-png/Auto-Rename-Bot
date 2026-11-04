"""
Format backups in the Save channel: ONE text message per format.
The message id is stored on the format in MongoDB, so editing/deleting a format edits/deletes
that one post. Mongo stays the source of truth; /restore_formats can rebuild it from these posts.
"""
import re
import html
import logging

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified

from helper.database import codeflixbots

logger = logging.getLogger(__name__)

HEADER = "🗄 Format backup"


def build_backup_text(channel, fmt):
    def pre(x):
        return f"<pre>{html.escape(x or '')}</pre>"
    return (
        f"<b>{HEADER}</b>\n\n"
        f"<b>Sub channel:</b> {html.escape(channel.get('title', ''))}\n"
        f"<b>Channel ID:</b> <code>{channel['_id']}</code>\n"
        f"<b>Format ID:</b> <code>{fmt['format_id']}</code>\n"
        f"<b>Label:</b> {html.escape(fmt['label'])}\n"
        f"<b>Thumbnail:</b> <code>{html.escape(fmt['thumbnail'])}</code>\n"
        f"<b>Main html:</b> {int(bool(fmt.get('main_html')))}\n"
        f"<b>Sub html:</b> {int(bool(fmt.get('sub_html')))}\n\n"
        f"<b>Rename format:</b>\n{pre(fmt['rename_format'])}\n"
        f"<b>Main post:</b>\n{pre(fmt['main_post'])}\n"
        f"<b>Sub post:</b>\n{pre(fmt['sub_post'])}"
    )


def parse_backup(message):
    """
    Reads a backup post (new single-text layout, or the older photo+caption layout).
    Returns a dict, or None if it doesn't look like a complete format backup.
    """
    text = (getattr(message, 'text', None) or getattr(message, 'caption', None) or '')
    text = str(text)
    if HEADER.replace("🗄 ", "") not in text:
        return None

    def field(name):
        m = re.search(rf'^{name}:[ \t]*(.+)$', text, flags=re.MULTILINE)
        return m.group(1).strip() if m else None

    channel_id = field('Channel ID')
    format_id = field('Format ID')
    label = field('Label')
    if not (channel_id and re.fullmatch(r'-?\d+', channel_id) and format_id and label):
        return None

    thumbnail = field('Thumbnail')
    if not thumbnail and getattr(message, 'photo', None):
        thumbnail = message.photo.file_id          # old layout: the thumbnail was the photo
    if not thumbnail:
        return None

    sections = re.search(
        r'Rename format:\n+(.*?)\n+Main (?:channel )?post:\n+(.*?)\n+Sub (?:channel )?post:\n+(.*)\Z',
        text, flags=re.DOTALL
    )
    if not sections:
        return None
    rename_format, main_post, sub_post = (s.strip() for s in sections.groups())
    if not (rename_format and main_post and sub_post):
        return None

    return {
        'channel_id': int(channel_id),
        'channel_title': field('Sub channel') or channel_id,
        'format_id': format_id,
        'label': label,
        'thumbnail': thumbnail,
        'rename_format': rename_format,
        'main_post': main_post,
        'sub_post': sub_post,
        'main_html': field('Main html') == '1',
        'sub_html': field('Sub html') == '1',
    }


def format_doc_from_backup(parsed, new_id=None, label=None):
    return {
        'format_id': new_id or parsed['format_id'],
        'label': label or parsed['label'],
        'thumbnail': parsed['thumbnail'],
        'rename_format': parsed['rename_format'],
        'main_post': parsed['main_post'],
        'sub_post': parsed['sub_post'],
        'main_html': parsed['main_html'],
        'sub_html': parsed['sub_html'],
    }


async def sync_format(client, channel, fmt):
    """Create or edit the one backup post for this format. Returns its message id (or None)."""
    save_channel = await codeflixbots.get_save_channel()
    if not save_channel:
        return None
    text = build_backup_text(channel, fmt)
    mid = fmt.get('backup_msg_id')
    if mid:
        try:
            await client.edit_message_text(save_channel, mid, text, parse_mode=ParseMode.HTML)
            return mid
        except MessageNotModified:
            return mid
        except Exception as e:
            logger.warning(f"Backup post {mid} could not be edited ({e}); sending a new one.")
    try:
        sent = await client.send_message(save_channel, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Could not back up format {fmt['format_id']}: {e}")
        return None
    await codeflixbots.update_format_field(channel['_id'], fmt['format_id'], {'backup_msg_id': sent.id})
    fmt['backup_msg_id'] = sent.id
    return sent.id


async def delete_backup(client, fmt):
    mid = fmt.get('backup_msg_id')
    save_channel = await codeflixbots.get_save_channel()
    if not mid or not save_channel:
        return False
    try:
        await client.delete_messages(save_channel, mid)
        return True
    except Exception as e:
        logger.warning(f"Could not delete backup post {mid}: {e}")
        return False


async def restore_all(client, user_id):
    """
    Rebuild MongoDB formats from the Save channel. A bot can't list channel history, so this
    reads message ids 1..latest in batches. Existing formats are never overwritten.
    """
    save_channel = await codeflixbots.get_save_channel()
    if not save_channel:
        return {'error': "No Save channel is set."}
    try:
        probe = await client.send_message(save_channel, "⏳ Scanning backups…")
        latest = probe.id
        await client.delete_messages(save_channel, probe.id)
    except Exception as e:
        return {'error': f"Couldn't use the Save channel: {e}"}

    found = {}
    for start in range(1, latest, 100):
        ids = list(range(start, min(start + 100, latest)))
        try:
            msgs = await client.get_messages(save_channel, ids)
        except Exception as e:
            logger.warning(f"Could not read backup ids {ids[0]}-{ids[-1]}: {e}")
            continue
        for m in msgs or []:
            if not m or getattr(m, 'empty', False):
                continue
            parsed = parse_backup(m)
            if parsed:
                parsed['backup_msg_id'] = m.id
                found[(parsed['channel_id'], parsed['format_id'])] = parsed   # later post wins

    restored = present = 0
    for (cid, fid), parsed in found.items():
        channel = await codeflixbots.get_subchannel(cid)
        if not channel:
            await codeflixbots.add_subchannel(cid, parsed['channel_title'], None, user_id)
        if await codeflixbots.get_format(cid, fid):
            present += 1
            continue
        doc = format_doc_from_backup(parsed)
        doc['backup_msg_id'] = parsed['backup_msg_id']
        await codeflixbots.add_format(cid, doc)
        restored += 1
    return {'found': len(found), 'restored': restored, 'present': present}
