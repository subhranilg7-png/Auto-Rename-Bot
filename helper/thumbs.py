"""
Thumbnail helpers.

How a user's thumbnail is stored
--------------------------------
MongoDB keeps only the Telegram ``file_id`` of the image the user sent (the same
approach the auto-post bot uses). The cropped JPEG that Telegram needs for uploads
is rebuilt from that file_id whenever it is missing, so a wiped disk (Render
redeploy, Termux cleanup, ...) never loses the thumbnail.

Older installs stored a local file path in the same field; those values (they start
with ``downloads/``) are still honoured while the file exists.
"""
import os
import glob
import hashlib
import asyncio
import logging
from PIL import Image, ImageOps

from helper.database import codeflixbots

logger = logging.getLogger(__name__)

THUMB_DIR = os.path.join("downloads", "thumbs")
THUMB_SIZE = 320            # Telegram: max 320 px on either side
THUMB_MAX_BYTES = 200_000   # Telegram: max 200 KB
LEGACY_PREFIX = "downloads/"

os.makedirs(THUMB_DIR, exist_ok=True)

_locks = {}


def _lock_for(user_id):
    lock = _locks.get(user_id)
    if lock is None:
        lock = _locks[user_id] = asyncio.Lock()
    return lock


def make_square_thumb(src_path, dst_path, size=THUMB_SIZE, max_bytes=THUMB_MAX_BYTES):
    """
    Exact-centre 1:1 crop using pixel coordinates, then ONE high quality resize.

    - the square's side is the shorter edge of the original image
    - the crop box is positioned from the integer centre of the image
    - the crop is taken from the full resolution picture, before any scaling
    - the result is scaled down once with Lanczos and never scaled up
    - saved as JPEG quality 95 / 4:4:4, lowered in small steps only if the file
      would exceed Telegram's 200 KB limit
    """
    with Image.open(src_path) as im:
        im.load()
        im = ImageOps.exif_transpose(im)   # honour phone-camera rotation
        im = im.convert("RGB")

    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    im = im.crop((left, top, left + side, top + side))

    if side > size:
        im = im.resize((size, size), Image.LANCZOS)

    quality = 95
    while True:
        im.save(dst_path, "JPEG", quality=quality, subsampling=0, optimize=True)
        if os.path.getsize(dst_path) <= max_bytes or quality <= 70:
            break
        quality -= 5
    return dst_path


def _cache_paths(user_id, file_id):
    tag = hashlib.sha1(file_id.encode()).hexdigest()[:10]
    base = os.path.join(THUMB_DIR, f"{user_id}_{tag}")
    return f"{base}_raw.jpg", f"{base}_crop.jpg"


def clear_user_thumb_cache(user_id, keep=None):
    """Remove cached thumbnail files of a user (optionally keeping one path)."""
    for path in glob.glob(os.path.join(THUMB_DIR, f"{user_id}_*")):
        if keep and os.path.abspath(path) == os.path.abspath(keep):
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def is_legacy_path(value):
    return isinstance(value, str) and value.startswith(LEGACY_PREFIX)


async def build_thumb_from_file_id(client, user_id, file_id):
    """Download the saved image by file_id (if needed) and return the cropped thumb path."""
    raw_path, crop_path = _cache_paths(user_id, file_id)
    async with _lock_for(user_id):
        if os.path.exists(crop_path) and os.path.getsize(crop_path) > 0:
            return crop_path
        try:
            await client.download_media(file_id, file_name=raw_path)
            if not os.path.exists(raw_path) or os.path.getsize(raw_path) == 0:
                return None
            make_square_thumb(raw_path, crop_path)
            return crop_path
        except Exception as e:
            logger.error(f"Could not build thumbnail for user {user_id}: {e}")
            return None
        finally:
            try:
                if os.path.exists(raw_path):
                    os.remove(raw_path)
            except OSError:
                pass


async def get_user_thumb_path(client, user_id):
    """
    Path of the user's ready-to-upload thumbnail, or None.
    Rebuilds it from the saved file_id when the cached file is gone.
    """
    value = await codeflixbots.get_thumbnail(user_id)
    if not value:
        return None
    if is_legacy_path(value):
        return value if os.path.exists(value) else None
    return await build_thumb_from_file_id(client, user_id, value)
