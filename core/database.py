from __future__ import annotations
import json
import logging
from datetime import datetime
from typing import List

import pymongo
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from motor.motor_asyncio import AsyncIOMotorClient

from core.config import (
    MONGO_URI, DB_NAME, BASE_DIR, JSON_DATA_FILE
)

logger = logging.getLogger(__name__)

mongo_client = None
db = None
processed_episodes_collection = None
anime_banners_collection = None
anime_hashtags_collection = None
admins_collection = None
bot_settings_collection = None
anime_channels_collection = None
requests_collection = None
processed_requests_collection = None

def _migrate_bot_settings(collection):
    try:
        null_name_count = collection.count_documents(
            {"$or": [{"setting_name": None}, {"setting_name": {"$exists": False}}]}
        )
        if null_name_count > 0:
            logger.warning(
                f"[Migration] Found {null_name_count} bot_settings documents with null/missing setting_name. Removing them."
            )
            result = collection.delete_many(
                {"$or": [{"setting_name": None}, {"setting_name": {"$exists": False}}]}
            )
            logger.info(f"[Migration] Deleted {result.deleted_count} invalid documents from bot_settings")

        docs_with_value_only = collection.count_documents(
            {"value": {"$exists": True}, "setting_value": {"$exists": False}}
        )
        if docs_with_value_only > 0:
            logger.warning(
                f"[Migration] Found {docs_with_value_only} documents with 'value' but no 'setting_value'. Normalizing."
            )
            for doc in collection.find({"value": {"$exists": True}, "setting_value": {"$exists": False}}):
                collection.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"setting_value": doc["value"]}}
                )
            logger.info(f"[Migration] Normalized {docs_with_value_only} documents (copied 'value' -> 'setting_value')")

        docs_missing_value = collection.count_documents(
            {"setting_value": {"$exists": False}}
        )
        if docs_missing_value > 0:
            logger.warning(
                f"[Migration] Found {docs_missing_value} documents missing 'setting_value'. Setting default."
            )
            collection.update_many(
                {"setting_value": {"$exists": False}},
                {"$set": {"setting_value": None}}
            )
            logger.info(f"[Migration] Added default setting_value to {docs_missing_value} documents")

        try:
            existing_indexes = collection.index_information()
            if "setting_name_1" in existing_indexes:
                collection.drop_index("setting_name_1")
                logger.info("[Migration] Dropped existing 'setting_name_1' index")
        except Exception as e:
            logger.warning(f"[Migration] Could not drop index 'setting_name_1': {e}")

        collection.create_index(
            [("setting_name", pymongo.ASCENDING)],
            unique=True
        )
        logger.info("[Migration] Successfully rebuilt unique index on setting_name")

    except Exception as e:
        logger.error(f"[Migration] bot_settings migration failed: {e}")


def _validate_bot_setting(setting_name, setting_value):
    if setting_name is None or (isinstance(setting_name, str) and not setting_name.strip()):
        raise ValueError(f"setting_name must be a non-empty string, got: {setting_name!r}")
    if not isinstance(setting_name, str):
        raise ValueError(f"setting_name must be a string, got type: {type(setting_name).__name__}")


def save_bot_setting(setting_name: str, setting_value) -> bool:
    try:
        _validate_bot_setting(setting_name, setting_value)
        if bot_settings_collection is not None:
            bot_settings_collection.update_one(
                {"setting_name": setting_name},
                {"$set": {"setting_value": setting_value, "value": setting_value}},
                upsert=True
            )
            return True
        return False
    except ValueError as e:
        logger.error(f"Validation error saving bot setting: {e}")
        return False
    except Exception as e:
        logger.error(f"Error saving bot setting '{setting_name}': {e}")
        return False


def load_bot_setting(setting_name: str, default=None):
    try:
        if bot_settings_collection is not None:
            doc = bot_settings_collection.find_one({"setting_name": setting_name})
            if doc:
                if "setting_value" in doc:
                    return doc["setting_value"]
                elif "value" in doc:
                    return doc["value"]
            return default
        return default
    except Exception as e:
        logger.error(f"Error loading bot setting '{setting_name}': {e}")
        return default


if MONGO_URI:
    try:
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = mongo_client.anime_bot
        processed_episodes_collection = db.processed_episodes
        anime_banners_collection = db.anime_banners
        anime_hashtags_collection = db.anime_hashtags
        admins_collection = db.admins
        bot_settings_collection = db.bot_settings
        anime_channels_collection = db.anime_channels
        requests_collection = db.requests
        processed_requests_collection = db.processed_requests
        
        try:
            _migrate_bot_settings(bot_settings_collection)
        except Exception as e:
            logger.error(f"bot_settings migration error: {e}")
        
        try:
            processed_episodes_collection.create_index(
                [("anime_title", pymongo.ASCENDING), ("episode_number", pymongo.ASCENDING)], 
                unique=True
            )
            anime_banners_collection.create_index(
                [("anime_title", pymongo.ASCENDING)], 
                unique=True
            )
            anime_hashtags_collection.create_index(
                [("anime_title", pymongo.ASCENDING)], 
                unique=True
            )
            admins_collection.create_index(
                [("user_id", pymongo.ASCENDING)], 
                unique=True
            )
            anime_channels_collection.create_index(
                [("anime_title", pymongo.ASCENDING)], 
                unique=True
            )
            requests_collection.create_index(
                [("user_id", pymongo.ASCENDING)]
            )
            requests_collection.create_index(
                [("status", pymongo.ASCENDING)]
            )
            processed_requests_collection.create_index(
                [("request_text", pymongo.ASCENDING)],
                unique=True
            )
        except Exception as e:
            logger.warning(f"Index creation failed: {e}")
        
        mongo_client.admin.command('ismaster')
        logger.info("Successfully connected to MongoDB")
    except (ConnectionFailure, OperationFailure) as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        mongo_client = None
        db = None
        processed_episodes_collection = None
        anime_banners_collection = None
        anime_hashtags_collection = None
        admins_collection = None
        bot_settings_collection = None
        anime_channels_collection = None
        requests_collection = None
        processed_requests_collection = None
else:
    logger.warning("MONGO_URI not provided. Using JSON file for data storage.")
    
    if not JSON_DATA_FILE.exists():
        with open(JSON_DATA_FILE, 'w') as f:
            json.dump({
                "processed_episodes": [], 
                "posted_banners": [],
                "anime_hashtags": [],
                "admins": [],
                "bot_settings": {},
                "anime_channels": [],
                "requests": []
            }, f)

def load_json_data():
    try:
        with open(JSON_DATA_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"processed_episodes": [], "posted_banners": [], "anime_hashtags": [], "admins": [], "bot_settings": {}, "anime_channels": []}


def save_json_data(data):
    with open(JSON_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


async def add_anime_channel(anime_title: str, channel_id: int, channel_username: str = None) -> bool:
    try:
        anime_data = {
            "anime_title": anime_title,
            "channel_id": channel_id,
            "channel_username": channel_username,
            "added_at": datetime.now().isoformat()
        }
        
        if anime_channels_collection is not None:
            anime_channels_collection.replace_one(
                {"anime_title": anime_title},
                anime_data,
                upsert=True
            )
            logger.info(f"Added anime channel mapping for {anime_title}")
        else:
            data = load_json_data()
            existing = next((item for item in data.get("anime_channels", []) if item["anime_title"] == anime_title), None)
            if existing:
                existing.update(anime_data)
            else:
                data.setdefault("anime_channels", []).append(anime_data)
            save_json_data(data)
            logger.info(f"Added anime channel mapping for {anime_title} (JSON)")
        
        return True
    except Exception as e:
        logger.error(f"Error adding anime channel: {e}")
        return False


async def remove_anime_channel(anime_title: str) -> bool:
    try:
        if anime_channels_collection is not None:
            result = anime_channels_collection.delete_one({"anime_title": anime_title})
            logger.info(f"Removed anime channel mapping for {anime_title}")
            return result.deleted_count > 0
        else:
            data = load_json_data()
            original_len = len(data.get("anime_channels", []))
            data["anime_channels"] = [item for item in data.get("anime_channels", []) if item["anime_title"] != anime_title]
            if len(data["anime_channels"]) < original_len:
                save_json_data(data)
                logger.info(f"Removed anime channel mapping for {anime_title} (JSON)")
                return True
            return False
    except Exception as e:
        logger.error(f"Error removing anime channel: {e}")
        return False


async def get_anime_channel(anime_title: str) -> dict:
    try:
        if anime_channels_collection is not None:
            result = anime_channels_collection.find_one({"anime_title": anime_title})
            return result
        else:
            data = load_json_data()
            result = next((item for item in data.get("anime_channels", []) if item["anime_title"] == anime_title), None)
            return result
    except Exception as e:
        logger.error(f"Error getting anime channel: {e}")
        return None


async def get_all_anime_channels() -> list:
    try:
        if anime_channels_collection is not None:
            results = list(anime_channels_collection.find({}, {"_id": 0}))
            return results
        else:
            data = load_json_data()
            return data.get("anime_channels", [])
    except Exception as e:
        logger.error(f"Error getting all anime channels: {e}")
        return []


async def add_request(user_id: int, text: str, username: str = None) -> bool:
    try:
        request_data = {
            "user_id": user_id,
            "text": text,
            "username": username,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "completed_at": None
        }
        
        if requests_collection is not None:
            requests_collection.insert_one(request_data)
            logger.info(f"Added request from user {user_id}: {text}")
        else:
            data = load_json_data()
            data.setdefault("requests", []).append(request_data)
            save_json_data(data)
            logger.info(f"Added request from user {user_id}: {text} (JSON)")
        
        return True
    except Exception as e:
        logger.error(f"Error adding request: {e}")
        return False


async def add_processed_request_result(request_text: str, anime_title: str) -> bool:
    try:
        if processed_requests_collection is not None:
            processed_requests_collection.update_one(
                {"request_text": request_text},
                {
                    "$addToSet": {"processed_results": anime_title},
                    "$set": {"updated_at": datetime.now().isoformat()}
                },
                upsert=True
            )
            logger.info(f"Added processed result '{anime_title}' for request '{request_text}'")
        else:
            data = load_json_data()
            processed_list = data.setdefault("processed_requests", [])
            existing = next((item for item in processed_list if item["request_text"] == request_text), None)
            if existing:
                if anime_title not in existing.get("processed_results", []):
                    existing.setdefault("processed_results", []).append(anime_title)
                existing["updated_at"] = datetime.now().isoformat()
            else:
                processed_list.append({
                    "request_text": request_text,
                    "processed_results": [anime_title],
                    "updated_at": datetime.now().isoformat()
                })
            save_json_data(data)
            logger.info(f"Added processed result '{anime_title}' for request '{request_text}' (JSON)")
        
        return True
    except Exception as e:
        logger.error(f"Error adding processed request result: {e}")
        return False


async def get_processed_request_results(request_text: str) -> list:
    try:
        if processed_requests_collection is not None:
            result = processed_requests_collection.find_one({"request_text": request_text})
            return result.get("processed_results", []) if result else []
        else:
            data = load_json_data()
            processed_list = data.get("processed_requests", [])
            existing = next((item for item in processed_list if item["request_text"] == request_text), None)
            return existing.get("processed_results", []) if existing else []
    except Exception as e:
        logger.error(f"Error getting processed request results: {e}")
        return []


async def clear_processed_request(request_text: str) -> bool:
    try:
        if processed_requests_collection is not None:
            result = processed_requests_collection.delete_one({"request_text": request_text})
            logger.info(f"Cleared processed results for request '{request_text}'")
            return result.deleted_count > 0
        else:
            data = load_json_data()
            original_len = len(data.get("processed_requests", []))
            data["processed_requests"] = [item for item in data.get("processed_requests", []) if item["request_text"] != request_text]
            if len(data["processed_requests"]) < original_len:
                save_json_data(data)
                logger.info(f"Cleared processed results for request '{request_text}' (JSON)")
                return True
            return False
    except Exception as e:
        logger.error(f"Error clearing processed request: {e}")
        return False


async def get_user_pending_requests(user_id: int) -> int:
    try:
        if requests_collection is not None:
            count = requests_collection.count_documents({"user_id": user_id, "status": "pending"})
            return count
        else:
            data = load_json_data()
            count = sum(1 for r in data.get("requests", []) if r["user_id"] == user_id and r["status"] == "pending")
            return count
    except Exception as e:
        logger.error(f"Error getting user pending requests: {e}")
        return 0


async def get_all_pending_requests() -> list:
    try:
        if requests_collection is not None:
            results = list(requests_collection.find({"status": "pending"}).sort("created_at", pymongo.ASCENDING))
            return results
        else:
            data = load_json_data()
            return [r for r in data.get("requests", []) if r["status"] == "pending"]
    except Exception as e:
        logger.error(f"Error getting all pending requests: {e}")
        return []


async def get_pending_request_count() -> int:
    try:
        if requests_collection is not None:
            count = requests_collection.count_documents({"status": "pending"})
            return count
        else:
            data = load_json_data()
            count = sum(1 for r in data.get("requests", []) if r["status"] == "pending")
            return count
    except Exception as e:
        logger.error(f"Error getting pending request count: {e}")
        return 0


def mark_request_processed(request_id) -> bool:
    try:
        if requests_collection is not None:
            result = requests_collection.update_one(
                {"_id": request_id},
                {"$set": {"status": "completed", "completed_at": datetime.now().isoformat()}}
            )
            logger.info(f"Marked request {request_id} as completed")
            return result.modified_count > 0
        else:
            data = load_json_data()
            for r in data.get("requests", []):
                if r.get("_id") == request_id or str(r.get("_id")) == str(request_id):
                    r["status"] = "completed"
                    r["completed_at"] = datetime.now().isoformat()
                    save_json_data(data)
                    logger.info(f"Marked request {request_id} as completed (JSON)")
                    return True
            return False
    except Exception as e:
        logger.error(f"Error marking request processed: {e}")
        return False


async def delete_request(request_id) -> bool:
    try:
        if requests_collection is not None:
            result = requests_collection.delete_one({"_id": request_id})
            logger.info(f"Deleted request {request_id}")
            return result.deleted_count > 0
        else:
            data = load_json_data()
            original_len = len(data.get("requests", []))
            data["requests"] = [r for r in data.get("requests", []) if r.get("_id") != request_id]
            if len(data["requests"]) < original_len:
                save_json_data(data)
                logger.info(f"Deleted request {request_id} (JSON)")
                return True
            return False
    except Exception as e:
        logger.error(f"Error deleting request: {e}")
        return False


async def get_max_requests_setting() -> int:
    try:
        if bot_settings_collection is not None:
            return load_bot_setting("max_requests", default=5)
        else:
            data = load_json_data()
            return data.get("bot_settings", {}).get("max_requests", 5)
    except Exception as e:
        logger.error(f"Error getting max requests setting: {e}")
        return 5


async def set_max_requests_setting(value: int) -> bool:
    try:
        if bot_settings_collection is not None:
            save_bot_setting("max_requests", value)
            logger.info(f"Set max_requests to {value}")
        else:
            data = load_json_data()
            data.setdefault("bot_settings", {})["max_requests"] = value
            save_json_data(data)
            logger.info(f"Set max_requests to {value} (JSON)")
        return True
    except Exception as e:
        logger.error(f"Error setting max requests: {e}")
        return False


async def get_request_process_time() -> str:
    try:
        if bot_settings_collection is not None:
            return load_bot_setting("request_process_time", default="00:00")
        else:
            data = load_json_data()
            return data.get("bot_settings", {}).get("request_process_time", "00:00")
    except Exception as e:
        logger.error(f"Error getting request process time: {e}")
        return "00:00"


async def set_request_process_time(time_str: str) -> bool:
    try:
        if bot_settings_collection is not None:
            save_bot_setting("request_process_time", time_str)
            logger.info(f"Set request_process_time to {time_str}")
        else:
            data = load_json_data()
            data.setdefault("bot_settings", {})["request_process_time"] = time_str
            save_json_data(data)
            logger.info(f"Set request_process_time to {time_str} (JSON)")
        return True
    except Exception as e:
        logger.error(f"Error setting request process time: {e}")
        return False


async def get_request_group_chat() -> dict:
    try:
        if bot_settings_collection is not None:
            return load_bot_setting("request_group_chat", default={})
        else:
            data = load_json_data()
            return data.get("bot_settings", {}).get("request_group_chat", {})
    except Exception as e:
        logger.error(f"Error getting request group chat: {e}")
        return {}


async def set_request_group_chat(chat_id: int = None, username: str = None) -> bool:
    try:
        group_config = {}
        if chat_id:
            group_config["chat_id"] = chat_id
        if username:
            group_config["username"] = username
        
        if bot_settings_collection is not None:
            save_bot_setting("request_group_chat", group_config)
            logger.info(f"Set request_group_chat to {group_config}")
        else:
            data = load_json_data()
            data.setdefault("bot_settings", {})["request_group_chat"] = group_config
            save_json_data(data)
            logger.info(f"Set request_group_chat to {group_config} (JSON)")
        return True
    except Exception as e:
        logger.error(f"Error setting request group chat: {e}")
        return False
