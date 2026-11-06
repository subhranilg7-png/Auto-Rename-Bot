"""
Safer downloads/uploads for big files.

* A watchdog notices a transfer that has made no progress for STALL_SECONDS and aborts it —
  Cancel also works during a stall (before, Cancel was only noticed when the next chunk arrived).
* Downloads and uploads that fail or stall are retried automatically (the library only retries
  single chunks and can end with "Session is stopped").
"""
import os
import time
import asyncio
import logging

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from helper.cancel import TaskCancelled, TransferStalled, is_cancelled, touch, last_activity, raise_if_cancelled
from helper.utils import progress_for_pyrogram

logger = logging.getLogger(__name__)

STALL_SECONDS = int(os.environ.get("TRANSFER_STALL_SECONDS", "120") or 120)
DOWNLOAD_ATTEMPTS = 3
UPLOAD_ATTEMPTS = 2


async def _kill(task):
    if not task.done():
        task.cancel()
        await asyncio.wait({task}, timeout=5)


async def run_with_watchdog(make_call, task_id, stall=None):
    """Run make_call() and abort it if the user cancels or it stalls."""
    stall = stall or STALL_SECONDS
    touch(task_id)
    task = asyncio.ensure_future(make_call())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=1.0)
            if done:
                return task.result()
            if is_cancelled(task_id):
                await _kill(task)
                raise TaskCancelled()
            if time.time() - last_activity(task_id) > stall:
                await _kill(task)
                raise TransferStalled(f"no data received for {stall} seconds")
    except asyncio.CancelledError:
        await _kill(task)
        raise


def _remove_partial(path):
    for p in (path, f"{path}.temp" if path else None):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception as e:
            logger.error(f"Could not remove partial file {p}: {e}")


async def _note(status_msg, task_id, text):
    """Edit the status message but keep its Cancel button."""
    if not status_msg:
        return
    try:
        await status_msg.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("• ᴄᴀɴᴄᴇʟ •", callback_data=f"cancel_{task_id}")]])
        )
    except Exception:
        pass


async def download_with_retries(client, message, download_path, task_id, status_msg=None, attempts=DOWNLOAD_ATTEMPTS):
    """Returns the downloaded path. Raises TaskCancelled, or the last error after all attempts."""
    last_error = None
    for attempt in range(1, attempts + 1):
        raise_if_cancelled(task_id)

        def make_call():
            return message.download(
                file_name=download_path,
                progress=progress_for_pyrogram,
                progress_args=("Downloading...", status_msg, time.time(), client, task_id)
            )
        try:
            result = await run_with_watchdog(make_call, task_id)
            if result is None:
                raise_if_cancelled(task_id)          # a stopped download returns None
                raise RuntimeError("The download returned nothing")
            return result
        except TaskCancelled:
            _remove_partial(download_path)
            raise
        except Exception as e:
            last_error = e
            _remove_partial(download_path)
            logger.warning(f"Download attempt {attempt}/{attempts} failed: {e!r}")
            if attempt < attempts:
                await _note(status_msg, task_id, f"**⚠️ Download problem:** `{str(e)[:80]}`\n**Retrying ({attempt + 1}/{attempts})…**")
                await asyncio.sleep(3 * attempt)
    raise last_error


async def upload_with_retries(make_send, task_id, status_msg=None, attempts=UPLOAD_ATTEMPTS):
    """make_send() must start a fresh upload each time it is called."""
    last_error = None
    for attempt in range(1, attempts + 1):
        raise_if_cancelled(task_id)
        try:
            return await run_with_watchdog(make_send, task_id)
        except TaskCancelled:
            raise
        except Exception as e:
            last_error = e
            logger.warning(f"Upload attempt {attempt}/{attempts} failed: {e!r}")
            if attempt < attempts:
                await _note(status_msg, task_id, f"**⚠️ Upload problem:** `{str(e)[:80]}`\n**Retrying ({attempt + 1}/{attempts})…**")
                await asyncio.sleep(3 * attempt)
    raise last_error
