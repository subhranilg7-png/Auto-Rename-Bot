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
        self.queue_col = self.db.rename_queue          # unfinished rename tasks (persistent queue)
        self.seq_col = self.db.sequence_files          # files collected by /sequence, waiting for 'work'

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

    # ── Default season (/defaultseason) ───────────────────────────────────────
    async def get_default_season(self, user_id):
        """Returns (enabled: bool, season: str | None)."""
        try:
            user = await self.col.find_one({'_id': int(user_id)})
            if not user:
                return False, None
            return bool(user.get('default_season_enabled', False)), user.get('default_season')
        except Exception as e:
            logging.error(f"Error getting default season for user {user_id}: {e}")
            return False, None

    async def set_default_season(self, user_id, season):
        try:
            await self.col.update_one(
                {'_id': int(user_id)}, {'$set': {'default_season': str(season)}}
            )
        except Exception as e:
            logging.error(f"Error setting default season for user {user_id}: {e}")

    async def set_default_season_enabled(self, user_id, enabled):
        try:
            await self.col.update_one(
                {'_id': int(user_id)}, {'$set': {'default_season_enabled': bool(enabled)}}
            )
        except Exception as e:
            logging.error(f"Error toggling default season for user {user_id}: {e}")

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


    # ── Persistent rename queue ───────────────────────────────────────────────
    # One document per unfinished file. A document is deleted as soon as its file
    # is done, so this collection is empty whenever the bot is idle.
    async def init_indexes(self, ttl_days=7):
        """Safety net: records that somehow outlive a week are removed by MongoDB itself."""
        ttl = ttl_days * 86400
        for col in (self.queue_col, self.seq_col):
            try:
                await col.create_index("created_at", expireAfterSeconds=ttl)
            except Exception as e:
                logging.error(f"Could not create TTL index on {col.name}: {e}")

    async def add_queue_task(self, task_id, fields):
        try:
            await self.queue_col.update_one(
                {"_id": task_id},
                {"$set": fields,
                 "$setOnInsert": {"attempts": 0, "created_at": datetime.datetime.utcnow()}},
                upsert=True,
            )
        except Exception as e:
            logging.error(f"Error saving queue task {task_id}: {e}")

    async def mark_task_started(self, task_id):
        try:
            await self.queue_col.update_one(
                {"_id": task_id}, {"$inc": {"attempts": 1}, "$set": {"status": "processing"}}
            )
        except Exception as e:
            logging.error(f"Error marking task {task_id} started: {e}")

    async def delete_task(self, task_id):
        try:
            await self.queue_col.delete_one({"_id": task_id})
        except Exception as e:
            logging.error(f"Error deleting queue task {task_id}: {e}")

    async def delete_user_tasks(self, user_id):
        try:
            await self.queue_col.delete_many({"user_id": int(user_id)})
        except Exception as e:
            logging.error(f"Error deleting queue tasks of user {user_id}: {e}")

    async def get_pending_tasks(self):
        try:
            cursor = self.queue_col.find({}).sort([("user_id", 1), ("message_id", 1)])
            return await cursor.to_list(length=None)
        except Exception as e:
            logging.error(f"Error loading pending queue tasks: {e}")
            return []

    # ── /sequence settings (stored on the user document) ──────────────────────
    async def get_sequence(self, user_id):
        """Returns (enabled: bool, next_episode: int)."""
        try:
            user = await self.col.find_one({"_id": int(user_id)})
            if not user:
                return False, 1
            return bool(user.get("sequence_enabled", False)), int(user.get("sequence_next", 1) or 1)
        except Exception as e:
            logging.error(f"Error getting sequence settings for user {user_id}: {e}")
            return False, 1

    async def set_sequence_enabled(self, user_id, enabled):
        try:
            await self.col.update_one({"_id": int(user_id)}, {"$set": {"sequence_enabled": bool(enabled)}})
        except Exception as e:
            logging.error(f"Error toggling sequence for user {user_id}: {e}")

    async def set_sequence_next(self, user_id, number):
        try:
            await self.col.update_one({"_id": int(user_id)}, {"$set": {"sequence_next": int(number)}})
        except Exception as e:
            logging.error(f"Error setting sequence number for user {user_id}: {e}")

    # ── Files collected while /sequence is on ─────────────────────────────────
    async def add_sequence_file(self, doc):
        try:
            doc = dict(doc)
            doc_id = doc.pop("_id")
            await self.seq_col.update_one(
                {"_id": doc_id},
                {"$set": doc, "$setOnInsert": {"created_at": datetime.datetime.utcnow()}},
                upsert=True,
            )
        except Exception as e:
            logging.error(f"Error saving collected file: {e}")

    async def get_sequence_files(self, user_id):
        try:
            cursor = self.seq_col.find({"user_id": int(user_id)}).sort("message_id", 1)
            return await cursor.to_list(length=None)
        except Exception as e:
            logging.error(f"Error loading collected files for user {user_id}: {e}")
            return []

    async def count_sequence_files(self, user_id):
        try:
            return await self.seq_col.count_documents({"user_id": int(user_id)})
        except Exception as e:
            logging.error(f"Error counting collected files for user {user_id}: {e}")
            return 0

    async def delete_sequence_files(self, user_id, ids=None):
        """Delete a user's collected files; with `ids`, only those (files that arrived meanwhile stay)."""
        try:
            query = {"user_id": int(user_id)}
            if ids:
                query["_id"] = {"$in": list(ids)}
            result = await self.seq_col.delete_many(query)
            return result.deleted_count
        except Exception as e:
            logging.error(f"Error clearing collected files for user {user_id}: {e}")
            return 0


codeflixbots = Database(Config.DB_URL, Config.DB_NAME)
