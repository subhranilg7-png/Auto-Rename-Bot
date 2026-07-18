import os
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pyrogram.errors import UserNotParticipant
from config import Config

# DISABLED: Force subscription is turned off
FORCE_SUB_CHANNELS = []  # Empty list means no force subscription

# The code below is disabled but kept for reference
# To re-enable, change the above line to: FORCE_SUB_CHANNELS = Config.FORCE_SUB_CHANNELS

async def not_subscribed(_, __, message):
    # Always returns False because force sub is disabled
    return False

@Client.on_message(filters.private & filters.create(not_subscribed))
async def forces_sub(client, message):
    # This function won't be triggered because not_subscribed always returns False
    pass

@Client.on_callback_query(filters.regex("check_subscription"))
async def check_subscription(client, callback_query: CallbackQuery):
    # Just answer the callback without doing anything
    await callback_query.answer("Force subscription is disabled", show_alert=False)
