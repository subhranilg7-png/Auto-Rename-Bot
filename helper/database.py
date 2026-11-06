import motor.motor_asyncio
import datetime
import pytz
from config import Config
import logging
from .utils import send_log


class Database:
    def __init__(self, uri, database_name):
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        except Exception as e:
            logging.error(f"Failed to create MongoDB client: {e}")
            raise e
        self.db = self._client[database_name]
        self.col = self.db.user
        self.processing_col = self.db.processing
        self.admins_col = self.db.admins
        self.settings_col = self.db.settings
        self.subchannels_col = self.db.subchannels
        self.queue_col = self.db.rename_queue
        self.ap_sessions_col = self.db.autopost_sessions
        self.ap_groups_col = self.db.autopost_groups
        self.ap_files_col = self.db.autopost_files
        self.patterns_col = self.db.patterns

    async def ping(self):
        """Real connection check (server_info() on Motor is a coroutine, so the old
        un-awaited call never tested anything)."""
        try:
            await self._client.admin.command("ping")
            logging.info("Successfully connected to MongoDB")
        except Exception as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            raise

    def new_user(self, id):
        return dict(
            _id=int(id),
            join_date=datetime.date.today().isoformat(),
            file_id=None,
            caption=None,
            metadata="Off",
            format_template=None,
            ban_status=dict(
                is_banned=False,
                ban_duration=0,
                banned_on=datetime.date.max.isoformat(),
                ban_reason=''
            )
        )

    async def add_user(self, b, m):
        u = m.from_user
        if not await self.is_user_exist(u.id):
            user = self.new_user(u.id)
            try:
                await self.col.insert_one(user)
                await send_log(b, u)
            except Exception as e:
                logging.error(f"Error adding user {u.id}: {e}")

    async def is_user_exist(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return bool(user)
        except Exception as e:
            logging.error(f"Error checking if user {id} exists: {e}")
            return False

    async def total_users_count(self):
        try:
            return await self.col.count_documents({})
        except Exception as e:
            logging.error(f"Error counting users: {e}")
            return 0

    async def get_all_users(self):
        try:
            return self.col.find({})
        except Exception as e:
            logging.error(f"Error getting all users: {e}")
            return None

    async def delete_user(self, user_id):
        try:
            await self.col.delete_many({"_id": int(user_id)})
        except Exception as e:
            logging.error(f"Error deleting user {user_id}: {e}")

    async def set_thumbnail(self, id, file_id):
        try:
            await self.col.update_one({"_id": int(id)}, {"$set": {"file_id": file_id}})
        except Exception as e:
            logging.error(f"Error setting thumbnail for user {id}: {e}")

    async def get_thumbnail(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("file_id", None) if user else None
        except Exception as e:
            logging.error(f"Error getting thumbnail for user {id}: {e}")
            return None

    async def set_caption(self, id, caption):
        try:
            await self.col.update_one({"_id": int(id)}, {"$set": {"caption": caption}})
        except Exception as e:
            logging.error(f"Error setting caption for user {id}: {e}")

    async def get_caption(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("caption", None) if user else None
        except Exception as e:
            logging.error(f"Error getting caption for user {id}: {e}")
            return None

    async def set_format_template(self, id, format_template):
        try:
            await self.col.update_one(
                {"_id": int(id)}, {"$set": {"format_template": format_template}}
            )
        except Exception as e:
            logging.error(f"Error setting format template for user {id}: {e}")

    async def get_format_template(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("format_template", None) if user else None
        except Exception as e:
            logging.error(f"Error getting format template for user {id}: {e}")
            return None

    async def set_media_preference(self, id, media_type):
        try:
            await self.col.update_one(
                {"_id": int(id)}, {"$set": {"media_type": media_type}}
            )
        except Exception as e:
            logging.error(f"Error setting media preference for user {id}: {e}")

    async def get_media_preference(self, id):
        try:
            user = await self.col.find_one({"_id": int(id)})
            return user.get("media_type", None) if user else None
        except Exception as e:
            logging.error(f"Error getting media preference for user {id}: {e}")
            return None

    async def get_metadata(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('metadata', "Off") if user else "Off"
        except Exception as e:
            logging.error(f"Error getting metadata for user {user_id}: {e}")
            return "Off"

    async def set_metadata(self, user_id, metadata):
        try:
            await self.col.update_one({'_id': int(user_id)}, {'$set': {'metadata': metadata}})
        except Exception as e:
            logging.error(f"Error setting metadata for user {user_id}: {e}")

    async def get_title(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('title', 'Encoded by @Animes_Cruise') if user else 'Encoded by @Animes_Cruise'
        except:
            return 'Encoded by @Animes_Cruise'

    async def set_title(self, user_id, title):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'title': title}})

    async def get_author(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('author', '@Animes_Cruise') if user else '@Animes_Cruise'
        except:
            return '@Animes_Cruise'

    async def set_author(self, user_id, author):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'author': author}})

    async def get_artist(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('artist', '@Animes_Cruise') if user else '@Animes_Cruise'
        except:
            return '@Animes_Cruise'

    async def set_artist(self, user_id, artist):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'artist': artist}})

    async def get_audio(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('audio', 'By @Animes_Cruise') if user else 'By @Animes_Cruise'
        except:
            return 'By @Animes_Cruise'

    async def set_audio(self, user_id, audio):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'audio': audio}})

    async def get_subtitle(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('subtitle', 'By @Animes_Cruise') if user else 'By @Animes_Cruise'
        except:
            return 'By @Animes_Cruise'

    async def set_subtitle(self, user_id, subtitle):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'subtitle': subtitle}})

    async def get_video(self, user_id):
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            return user.get('video', 'Encoded By @Animes_Cruise') if user else 'Encoded By @Animes_Cruise'
        except:
            return 'Encoded By @Animes_Cruise'

    async def set_video(self, user_id, video):
        await self.col.update_one({'_id': int(user_id)}, {'$set': {'video': video}})

    # ── Processing lock (prevents duplicate processing across restarts) ────────

    async def is_processing(self, file_id):
        try:
            doc = await self.processing_col.find_one({"_id": file_id})
            if not doc:
                return False
            age = (datetime.datetime.utcnow() - doc["time"]).total_seconds()
            if age > 600:
                await self.clear_processing(file_id)
                return False
            return True
        except:
            return False

    async def set_processing(self, file_id):
        try:
            await self.processing_col.update_one(
                {"_id": file_id},
                {"$set": {"time": datetime.datetime.utcnow()}},
                upsert=True
            )
        except:
            pass

    async def clear_processing(self, file_id):
        try:
            await self.processing_col.delete_one({"_id": file_id})
        except:
            pass

    # ── Admin management ────────────────────────────────────────────────────────

    async def add_admin(self, user_id, added_by):
        try:
            await self.admins_col.update_one(
                {"_id": int(user_id)},
                {"$set": {
                    "added_by": int(added_by),
                    "added_on": datetime.datetime.utcnow().isoformat()
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error adding admin {user_id}: {e}")
            return False

    async def remove_admin(self, user_id):
        try:
            result = await self.admins_col.delete_one({"_id": int(user_id)})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error removing admin {user_id}: {e}")
            return False

    async def get_admins(self):
        try:
            admins = []
            async for doc in self.admins_col.find({}):
                admins.append(doc["_id"])
            return admins
        except Exception as e:
            logging.error(f"Error getting admins: {e}")
            return []

    async def is_admin(self, user_id):
        try:
            user_id = int(user_id)
            if user_id in Config.ADMIN:
                return True
            doc = await self.admins_col.find_one({"_id": user_id})
            return bool(doc)
        except Exception as e:
            logging.error(f"Error checking admin status for {user_id}: {e}")
            return False

    # ── Main channel setting ────────────────────────────────────────────────────

    async def set_main_channel(self, channel_id):
        try:
            await self.settings_col.update_one(
                {"_id": "main"},
                {"$set": {"channel_id": int(channel_id)}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error setting main channel: {e}")
            return False

    async def get_main_channel(self):
        try:
            doc = await self.settings_col.find_one({"_id": "main"})
            return doc.get("channel_id") if doc else None
        except Exception as e:
            logging.error(f"Error getting main channel: {e}")
            return None

    async def set_save_channel(self, channel_id):
        try:
            await self.settings_col.update_one(
                {"_id": "save"},
                {"$set": {"channel_id": int(channel_id)}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error setting save channel: {e}")
            return False

    async def get_save_channel(self):
        try:
            doc = await self.settings_col.find_one({"_id": "save"})
            return doc.get("channel_id") if doc else None
        except Exception as e:
            logging.error(f"Error getting save channel: {e}")
            return None

    async def set_main_sticker(self, sticker_file_id):
        try:
            await self.settings_col.update_one(
                {"_id": "main_sticker"},
                {"$set": {"file_id": sticker_file_id}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error setting main sticker: {e}")
            return False

    async def get_main_sticker(self):
        try:
            doc = await self.settings_col.find_one({"_id": "main_sticker"})
            return doc.get("file_id") if doc else None
        except Exception as e:
            logging.error(f"Error getting main sticker: {e}")
            return None

    async def set_sub_sticker(self, sticker_file_id):
        try:
            await self.settings_col.update_one(
                {"_id": "sub_sticker"},
                {"$set": {"file_id": sticker_file_id}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error setting sub sticker: {e}")
            return False

    async def get_sub_sticker(self):
        try:
            doc = await self.settings_col.find_one({"_id": "sub_sticker"})
            return doc.get("file_id") if doc else None
        except Exception as e:
            logging.error(f"Error getting sub sticker: {e}")
            return None

    # ── Sub-channels & formats ──────────────────────────────────────────────────

    async def add_subchannel(self, channel_id, title, invite_link, added_by):
        try:
            await self.subchannels_col.update_one(
                {"_id": int(channel_id)},
                {"$set": {
                    "title": title,
                    "invite_link": invite_link,
                    "added_by": int(added_by),
                    "added_on": datetime.datetime.utcnow().isoformat()
                },
                "$setOnInsert": {"formats": []}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error adding subchannel {channel_id}: {e}")
            return False

    async def get_subchannel(self, channel_id):
        try:
            return await self.subchannels_col.find_one({"_id": int(channel_id)})
        except Exception as e:
            logging.error(f"Error getting subchannel {channel_id}: {e}")
            return None

    async def get_all_subchannels(self):
        try:
            channels = []
            async for doc in self.subchannels_col.find({}):
                channels.append(doc)
            return channels
        except Exception as e:
            logging.error(f"Error getting subchannels: {e}")
            return []

    async def delete_subchannel(self, channel_id):
        try:
            result = await self.subchannels_col.delete_one({"_id": int(channel_id)})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error deleting subchannel {channel_id}: {e}")
            return False

    async def add_format(self, channel_id, format_doc):
        try:
            await self.subchannels_col.update_one(
                {"_id": int(channel_id)},
                {"$push": {"formats": format_doc}}
            )
            return True
        except Exception as e:
            logging.error(f"Error adding format to {channel_id}: {e}")
            return False

    async def delete_format(self, channel_id, format_id):
        try:
            result = await self.subchannels_col.update_one(
                {"_id": int(channel_id)},
                {"$pull": {"formats": {"format_id": format_id}}}
            )
            return result.modified_count > 0
        except Exception as e:
            logging.error(f"Error deleting format {format_id} from {channel_id}: {e}")
            return False

    async def get_format(self, channel_id, format_id):
        try:
            doc = await self.subchannels_col.find_one(
                {"_id": int(channel_id), "formats.format_id": format_id},
                {"formats.$": 1}
            )
            if doc and doc.get("formats"):
                return doc["formats"][0]
            return None
        except Exception as e:
            logging.error(f"Error getting format {format_id} from {channel_id}: {e}")
            return None

    # ── Persistent rename queue (survives restarts) ─────────────────────────────
    # One document per pending file. Only ids/strings are stored (chat_id +
    # message_id + Telegram file_id), never file bytes. `seq` keeps the original
    # order so the queue resumes exactly where it stopped.

    async def queue_add(self, task):
        try:
            last = await self.queue_col.find_one(
                {"user_id": int(task["user_id"])}, sort=[("seq", -1)]
            )
            seq = (last["seq"] + 1) if last else 1
            doc = {
                "user_id": int(task["user_id"]),
                "chat_id": int(task["chat_id"]),
                "message_id": int(task["message_id"]),
                "file_id": task["file_id"],
                "file_name": task["file_name"],
                "media_type": task["media_type"],
                "format_template": task["format_template"],
                "season": task.get("season"),
                "episode": task.get("episode"),
                "quality": task.get("quality"),
                "seq": seq,
                "added_on": datetime.datetime.utcnow(),
            }
            res = await self.queue_col.insert_one(doc)
            return res.inserted_id
        except Exception as e:
            logging.error(f"Error adding queue item for {task.get('user_id')}: {e}")
            return None

    async def queue_remove(self, doc_id):
        try:
            if doc_id is not None:
                await self.queue_col.delete_one({"_id": doc_id})
        except Exception as e:
            logging.error(f"Error removing queue item {doc_id}: {e}")

    async def queue_clear_user(self, user_id):
        try:
            res = await self.queue_col.delete_many({"user_id": int(user_id)})
            return res.deleted_count
        except Exception as e:
            logging.error(f"Error clearing queue for {user_id}: {e}")
            return 0

    async def queue_get_user(self, user_id):
        try:
            return [d async for d in self.queue_col.find({"user_id": int(user_id)}).sort("seq", 1)]
        except Exception as e:
            logging.error(f"Error reading queue for {user_id}: {e}")
            return []

    async def queue_users(self):
        try:
            return await self.queue_col.distinct("user_id")
        except Exception as e:
            logging.error(f"Error listing queue users: {e}")
            return []


    # ── Auto-post persistence (survives restarts) ───────────────────────────────
    # Only ids/strings are stored (chat_id + message_id + Telegram file_id), never file bytes.

    async def get_autopost_window(self, default=15):
        try:
            doc = await self.settings_col.find_one({"_id": "autopost_window"})
            return int(doc["seconds"]) if doc and doc.get("seconds") else default
        except Exception as e:
            logging.error(f"Error getting auto-post window: {e}")
            return default

    async def set_autopost_window(self, seconds):
        try:
            await self.settings_col.update_one(
                {"_id": "autopost_window"}, {"$set": {"seconds": int(seconds)}}, upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error setting auto-post window: {e}")
            return False

    async def ap_session_set(self, user_id, channel_id, format_id):
        try:
            await self.ap_sessions_col.update_one(
                {"_id": int(user_id)},
                {"$set": {"channel_id": int(channel_id), "format_id": format_id}},
                upsert=True
            )
        except Exception as e:
            logging.error(f"Error saving auto-post session for {user_id}: {e}")

    async def ap_session_del(self, user_id):
        try:
            await self.ap_sessions_col.delete_one({"_id": int(user_id)})
        except Exception as e:
            logging.error(f"Error deleting auto-post session for {user_id}: {e}")

    async def ap_sessions_all(self):
        try:
            return [d async for d in self.ap_sessions_col.find({})]
        except Exception as e:
            logging.error(f"Error loading auto-post sessions: {e}")
            return []

    async def ap_group_create(self, doc):
        try:
            await self.ap_groups_col.insert_one(doc)
        except Exception as e:
            logging.error(f"Error creating auto-post group {doc.get('_id')}: {e}")

    async def ap_group_set(self, group_id, fields):
        try:
            await self.ap_groups_col.update_one({"_id": group_id}, {"$set": fields})
        except Exception as e:
            logging.error(f"Error updating auto-post group {group_id}: {e}")

    async def ap_group_delete(self, group_id):
        try:
            await self.ap_files_col.delete_many({"group_id": group_id})
            await self.ap_groups_col.delete_one({"_id": group_id})
        except Exception as e:
            logging.error(f"Error deleting auto-post group {group_id}: {e}")

    async def ap_groups_delete_for_user(self, user_id):
        try:
            ids = [d["_id"] async for d in self.ap_groups_col.find({"user_id": int(user_id)}, {"_id": 1})]
            for gid in ids:
                await self.ap_group_delete(gid)
        except Exception as e:
            logging.error(f"Error clearing auto-post groups for {user_id}: {e}")

    async def ap_groups_delete_for_channel(self, channel_id):
        try:
            ids = [d["_id"] async for d in self.ap_groups_col.find({"channel_id": int(channel_id)}, {"_id": 1})]
            for gid in ids:
                await self.ap_group_delete(gid)
        except Exception as e:
            logging.error(f"Error clearing auto-post groups for channel {channel_id}: {e}")

    async def ap_file_add(self, doc):
        try:
            res = await self.ap_files_col.insert_one(doc)
            return res.inserted_id
        except Exception as e:
            logging.error(f"Error saving auto-post file {doc.get('file_name')}: {e}")
            return None

    async def ap_file_done(self, doc_id):
        try:
            if doc_id is not None:
                await self.ap_files_col.update_one({"_id": doc_id}, {"$set": {"done": True}})
        except Exception as e:
            logging.error(f"Error marking auto-post file done {doc_id}: {e}")

    async def ap_groups_load(self):
        """All unfinished groups with their files, oldest first."""
        try:
            out = []
            async for g in self.ap_groups_col.find({}).sort("created", 1):
                files = [f async for f in self.ap_files_col.find({"group_id": g["_id"]}).sort("seq", 1)]
                out.append((g, files))
            return out
        except Exception as e:
            logging.error(f"Error loading auto-post groups: {e}")
            return []


    # ── Admin panel helpers ─────────────────────────────────────────────────────

    async def update_format_field(self, channel_id, format_id, fields):
        """Set one or more fields of a single format in place."""
        try:
            res = await self.subchannels_col.update_one(
                {"_id": int(channel_id), "formats.format_id": format_id},
                {"$set": {f"formats.$.{k}": v for k, v in fields.items()}}
            )
            return res.matched_count > 0
        except Exception as e:
            logging.error(f"Error updating format {format_id}: {e}")
            return False

    async def set_invite_link(self, channel_id, link):
        try:
            await self.subchannels_col.update_one(
                {"_id": int(channel_id)}, {"$set": {"invite_link": link}}
            )
            return True
        except Exception as e:
            logging.error(f"Error setting invite link for {channel_id}: {e}")
            return False

    async def ap_recent_add(self, user_id, channel_id, format_id):
        """Remember the last 3 (channel, format) pairs used for one-tap restart."""
        try:
            doc = await self.settings_col.find_one({"_id": f"ap_recent_{int(user_id)}"})
            items = [i for i in (doc.get("items", []) if doc else [])
                     if not (i[0] == int(channel_id) and i[1] == format_id)]
            items.insert(0, [int(channel_id), format_id])
            await self.settings_col.update_one(
                {"_id": f"ap_recent_{int(user_id)}"}, {"$set": {"items": items[:3]}}, upsert=True
            )
        except Exception as e:
            logging.error(f"Error saving recent auto-post for {user_id}: {e}")

    async def ap_recent_get(self, user_id):
        try:
            doc = await self.settings_col.find_one({"_id": f"ap_recent_{int(user_id)}"})
            return doc.get("items", []) if doc else []
        except Exception as e:
            logging.error(f"Error reading recent auto-posts for {user_id}: {e}")
            return []

    # ── Custom detection patterns (global) ──────────────────────────────────────

    async def patterns_all(self):
        try:
            return [d async for d in self.patterns_col.find({}).sort("order", 1)]
        except Exception as e:
            logging.error(f"Error loading patterns: {e}")
            return []

    async def pattern_add(self, template):
        try:
            last = await self.patterns_col.find_one({}, sort=[("order", -1)])
            doc = {
                "_id": __import__("uuid").uuid4().hex[:8],
                "template": template, "enabled": True,
                "order": (last["order"] + 1) if last else 1,
                "created": datetime.datetime.utcnow(),
            }
            await self.patterns_col.insert_one(doc)
            return doc
        except Exception as e:
            logging.error(f"Error adding pattern: {e}")
            return None

    async def pattern_update(self, pattern_id, fields):
        try:
            await self.patterns_col.update_one({"_id": pattern_id}, {"$set": fields})
            return True
        except Exception as e:
            logging.error(f"Error updating pattern {pattern_id}: {e}")
            return False

    async def pattern_delete(self, pattern_id):
        try:
            res = await self.patterns_col.delete_one({"_id": pattern_id})
            return res.deleted_count > 0
        except Exception as e:
            logging.error(f"Error deleting pattern {pattern_id}: {e}")
            return False


    # ── Transfer tuning saved from the Settings screen ──────────────────────────

    async def get_transfer_stall(self, default=120):
        try:
            doc = await self.settings_col.find_one({"_id": "transfer_stall"})
            return int(doc["value"]) if doc and doc.get("value") else default
        except Exception as e:
            logging.error(f"Error getting transfer stall timeout: {e}")
            return default

    async def set_transfer_stall(self, seconds):
        try:
            await self.settings_col.update_one({"_id": "transfer_stall"}, {"$set": {"value": int(seconds)}}, upsert=True)
            return True
        except Exception as e:
            logging.error(f"Error saving transfer stall timeout: {e}")
            return False

    async def get_max_transmissions(self, default=None):
        try:
            doc = await self.settings_col.find_one({"_id": "max_transmissions"})
            return int(doc["value"]) if doc and doc.get("value") else default
        except Exception as e:
            logging.error(f"Error getting max transmissions: {e}")
            return default

    async def set_max_transmissions(self, value):
        try:
            await self.settings_col.update_one({"_id": "max_transmissions"}, {"$set": {"value": int(value)}}, upsert=True)
            return True
        except Exception as e:
            logging.error(f"Error saving max transmissions: {e}")
            return False


codeflixbots = Database(Config.DB_URL, Config.DB_NAME)


def read_setting_sync(key):
    """
    Read one saved setting before the bot's event loop exists (the Telegram client is created
    with max_concurrent_transmissions at startup). Returns the saved value or None.
    """
    try:
        from pymongo import MongoClient
        client = MongoClient(Config.DB_URL, serverSelectionTimeoutMS=3000)
        doc = client[Config.DB_NAME]["settings"].find_one({"_id": key})
        client.close()
        return int(doc["value"]) if doc and doc.get("value") else None
    except Exception as e:
        logging.warning(f"Could not read saved setting {key}: {e}")
        return None
