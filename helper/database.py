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
            self._client.server_info()
            logging.info("Successfully connected to MongoDB")
        except Exception as e:
            logging.error(f"Failed to connect to MongoDB: {e}")
            raise e
        self.db = self._client[database_name]
        self.col = self.db.user
        self.processing_col = self.db.processing
        self.admins_col = self.db.admins
        self.settings_col = self.db.settings
        self.subchannels_col = self.db.subchannels

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


codeflixbots = Database(Config.DB_URL, Config.DB_NAME)
