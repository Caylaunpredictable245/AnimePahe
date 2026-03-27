from __future__ import annotations
import json
import logging
import threading
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from enum import Enum

from core.config import (
    BASE_DIR, AUTO_DOWNLOAD_STATE_FILE, QUALITY_SETTINGS_FILE,
    START_PIC_URL, FIXED_THUMBNAIL_URL,
    DUMP_CHANNEL_ID, DUMP_CHANNEL_USERNAME, DELETE_TIMER
)
from core.database import (
    bot_settings_collection, load_json_data, save_json_data,
    save_bot_setting, load_bot_setting
)

logger = logging.getLogger(__name__)



class EpisodeState(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    POSTED = "posted"


class EpisodeTracker:
    def __init__(self):
        self._lock = threading.RLock()
        self._async_lock = None
        self.tracker_file = BASE_DIR / "episode_tracker.json"
        self.episodes: Dict[str, Dict[str, Any]] = {}
        self.load_tracker()
    
    @property
    def async_lock(self):
        if self._async_lock is None:
            try:
                self._async_lock = asyncio.Lock()
            except RuntimeError:
                # No event loop running yet
                pass
        return self._async_lock
    
    def _get_episode_id(self, anime_title: str, episode_number: int) -> str:
        return f"{anime_title}_{episode_number}"
    
    def load_tracker(self):
        try:
            if self.tracker_file.exists():
                with open(self.tracker_file, 'r') as f:
                    data = json.load(f)
                    self.episodes = data.get('episodes', {})
                    
                    for ep_id, ep_data in self.episodes.items():
                        if ep_data.get('state') == EpisodeState.PROCESSING.value:
                            logger.warning(f"Found stale PROCESSING episode on startup: {ep_id}, resetting to PENDING")
                            ep_data['state'] = EpisodeState.PENDING.value
                            ep_data['reset_at'] = datetime.now().isoformat()
                    
                    self._save_tracker()
                    logger.info(f"Loaded {len(self.episodes)} episodes from tracker")
        except Exception as e:
            logger.error(f"Error loading episode tracker: {e}")
            self.episodes = {}
    
    def _save_tracker(self):
        try:
            data = {
                'episodes': self.episodes,
                'last_updated': datetime.now().isoformat()
            }
            temp_file = self.tracker_file.with_suffix('.tmp')
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            temp_file.replace(self.tracker_file)
        except Exception as e:
            logger.error(f"Error saving episode tracker: {e}")
    
    def get_state(self, anime_title: str, episode_number: int) -> Optional[EpisodeState]:
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            ep_data = self.episodes.get(ep_id)
            if ep_data:
                try:
                    return EpisodeState(ep_data.get('state'))
                except ValueError:
                    return None
            return None
    
    def can_process(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            state = self.get_state(anime_title, episode_number)
            if state is None:
                return True
            return state == EpisodeState.PENDING
    
    def is_posted(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            state = self.get_state(anime_title, episode_number)
            return state == EpisodeState.POSTED
    
    def is_processing(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            state = self.get_state(anime_title, episode_number)
            return state == EpisodeState.PROCESSING
    
    def is_completed_or_posted(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            state = self.get_state(anime_title, episode_number)
            return state in (EpisodeState.COMPLETED, EpisodeState.POSTED)
    
    def try_start_processing(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            
            current_state = self.get_state(anime_title, episode_number)
            
            if current_state is not None and current_state != EpisodeState.PENDING:
                logger.info(f"Episode {ep_id} cannot start processing: current state is {current_state.value}")
                return False

            self.episodes[ep_id] = {
                'anime_title': anime_title,
                'episode_number': episode_number,
                'state': EpisodeState.PROCESSING.value,
                'started_at': datetime.now().isoformat(),
                'qualities_downloaded': [],
                'qualities_uploaded': []
            }
            self._save_tracker()
            logger.info(f"Episode {ep_id} state: -> PROCESSING")
            return True
    
    def mark_quality_downloaded(self, anime_title: str, episode_number: int, quality: str):
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            if ep_id in self.episodes:
                if quality not in self.episodes[ep_id].get('qualities_downloaded', []):
                    self.episodes[ep_id].setdefault('qualities_downloaded', []).append(quality)
                    self._save_tracker()
    
    def mark_quality_uploaded(self, anime_title: str, episode_number: int, quality: str, msg_id: int):
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            if ep_id in self.episodes:
                uploaded = self.episodes[ep_id].setdefault('qualities_uploaded', [])
                if not any(q.get('quality') == quality for q in uploaded if isinstance(q, dict)):
                    uploaded.append({'quality': quality, 'msg_id': msg_id})
                    self._save_tracker()
    
    def mark_completed(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            current_state = self.get_state(anime_title, episode_number)
            
            if current_state != EpisodeState.PROCESSING:
                logger.warning(f"Episode {ep_id} mark_completed called but state is {current_state}")
                return False
            
            self.episodes[ep_id]['state'] = EpisodeState.COMPLETED.value
            self.episodes[ep_id]['completed_at'] = datetime.now().isoformat()
            self._save_tracker()
            logger.info(f"Episode {ep_id} state: PROCESSING -> COMPLETED")
            return True
    
    def mark_posted(self, anime_title: str, episode_number: int) -> bool:
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            current_state = self.get_state(anime_title, episode_number)
            
            if current_state not in (EpisodeState.COMPLETED, EpisodeState.PROCESSING):
                logger.warning(f"Episode {ep_id} mark_posted called but state is {current_state}")
                return False
            
            self.episodes[ep_id]['state'] = EpisodeState.POSTED.value
            self.episodes[ep_id]['posted_at'] = datetime.now().isoformat()
            self._save_tracker()
            logger.info(f"Episode {ep_id} state: {current_state.value} -> POSTED")
            return True
    
    def release_processing(self, anime_title: str, episode_number: int, success: bool = False):
        with self._lock:
            ep_id = self._get_episode_id(anime_title, episode_number)
            current_state = self.get_state(anime_title, episode_number)
            
            if current_state != EpisodeState.PROCESSING:
                return
            
            if not success:
                self.episodes[ep_id]['state'] = EpisodeState.PENDING.value
                self.episodes[ep_id]['released_at'] = datetime.now().isoformat()
                self._save_tracker()
                logger.info(f"Episode {ep_id} state: PROCESSING -> PENDING (failed, will retry)")
    
    def get_processing_episodes(self) -> List[str]:
        with self._lock:
            return [
                ep_id for ep_id, data in self.episodes.items()
                if data.get('state') == EpisodeState.PROCESSING.value
            ]
    
    def cleanup_old_entries(self, days: int = 30):
        with self._lock:
            cutoff = datetime.now() - timedelta(days=days)
            to_remove = []
            for ep_id, data in self.episodes.items():
                posted_at = data.get('posted_at')
                if posted_at:
                    try:
                        if datetime.fromisoformat(posted_at) < cutoff:
                            to_remove.append(ep_id)
                    except:
                        pass
            
            for ep_id in to_remove:
                del self.episodes[ep_id]
            
            if to_remove:
                self._save_tracker()
                logger.info(f"Cleaned up {len(to_remove)} old episode entries")


episode_tracker = EpisodeTracker()


class AnimeQueue:
    
    def __init__(self):
        self.pending_queue = []
        self.processing_queue = []
        self.processed_episodes = set()
        self.lock = threading.Lock()
        self.queue_file = BASE_DIR / "anime_queue.json"
        self.load_queue()
    
    def load_queue(self):
        try:
            if self.queue_file.exists():
                with open(self.queue_file, 'r') as f:
                    data = json.load(f)
                    self.pending_queue = data.get('pending', [])
                    self.processed_episodes = set(data.get('processed', []))
                    logger.info(f"Loaded {len(self.pending_queue)} pending episodes from queue")
        except Exception as e:
            logger.error(f"Error loading queue: {e}")
    
    def save_queue(self):
        try:
            with self.lock:
                data = {
                    'pending': self.pending_queue,
                    'processed': list(self.processed_episodes)
                }
                with open(self.queue_file, 'w') as f:
                    json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving queue: {e}")
    
    def add_to_pending(self, anime_info):
        with self.lock:
            episode_id = f"{anime_info['title']}_{anime_info['episode']}"
            if episode_id not in [item['id'] for item in self.pending_queue]:
                anime_info['id'] = episode_id
                anime_info['added_time'] = datetime.now().isoformat()
                self.pending_queue.append(anime_info)
                self.save_queue()
                logger.info(f"Added {episode_id} to pending queue")
                return True
        return False
    
    def get_next_pending(self):
        with self.lock:
            if self.pending_queue:
                return self.pending_queue[0]
        return None
    
    def remove_from_pending(self, episode_id):
        with self.lock:
            self.pending_queue = [item for item in self.pending_queue if item['id'] != episode_id]
            self.save_queue()
    
    def mark_as_processed(self, anime_title, episode_number):
        with self.lock:
            episode_id = f"{anime_title}_{episode_number}"
            self.processed_episodes.add(episode_id)
            self.save_queue()
    
    def is_processed(self, anime_title, episode_number):
        episode_id = f"{anime_title}_{episode_number}"
        return episode_id in self.processed_episodes
    
    def clear_old_entries(self, days=7):
        with self.lock:
            cutoff_date = datetime.now() - timedelta(days=days)
            self.pending_queue = [
                item for item in self.pending_queue
                if datetime.fromisoformat(item['added_time']) > cutoff_date
            ]
            self.save_queue()


class QualitySettings:
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: Dict[str, Any] = {
            "enabled_qualities": ["360p", "720p", "1080p"],
            "download_all": True,
            "batch_mode": False
        }
        self.load_state()
        
    def load_state(self) -> None:
        if bot_settings_collection is not None:
            try:
                loaded = load_bot_setting("quality_settings")
                if loaded and isinstance(loaded, dict):
                    self.state.update(loaded)
                logger.info("Quality settings loaded successfully from MongoDB")
            except Exception as e:
                logger.error(f"Error loading quality settings from MongoDB: {e}")
        else:
            try:
                if QUALITY_SETTINGS_FILE.exists():
                    with open(QUALITY_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                        loaded_state = json.load(f)
                        self.state.update(loaded_state)
                    logger.info("Quality settings loaded successfully from JSON")
            except json.JSONDecodeError as e:
                logger.error(f"Corrupted quality settings file: {e}")
                self._backup_corrupted_state()
            except Exception as e:
                logger.error(f"Error loading quality settings: {str(e)}")
    
    def _backup_corrupted_state(self) -> None:
        try:
            if QUALITY_SETTINGS_FILE.exists():
                backup_path = QUALITY_SETTINGS_FILE.with_suffix('.json.bak')
                QUALITY_SETTINGS_FILE.rename(backup_path)
                logger.info(f"Corrupted quality settings file backed up to {backup_path}")
        except Exception as e:
            logger.error(f"Failed to backup corrupted quality settings file: {e}")
    
    def save_state(self) -> None:
        with self._lock:
            if bot_settings_collection is not None:
                try:
                    save_bot_setting("quality_settings", self.state)
                    logger.info("Quality settings saved successfully to MongoDB")
                except Exception as e:
                    logger.error(f"Error saving quality settings to MongoDB: {e}")
            else:
                temp_file = QUALITY_SETTINGS_FILE.with_suffix('.tmp')
                try:
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(self.state, f, indent=2)
                    temp_file.replace(QUALITY_SETTINGS_FILE)
                    logger.info("Quality settings saved successfully to JSON")
                except Exception as e:
                    logger.error(f"Error saving quality settings: {str(e)}")
                    if temp_file.exists():
                        temp_file.unlink()
    
    @property
    def enabled_qualities(self) -> List[str]:
        return self.state.get("enabled_qualities", ["360p", "720p", "1080p"])
    
    @enabled_qualities.setter
    def enabled_qualities(self, qualities: List[str]) -> None:
        self.state["enabled_qualities"] = qualities
        self.save_state()
    
    @property
    def download_all(self) -> bool:
        return self.state.get("download_all", True)
    
    @download_all.setter
    def download_all(self, value: bool) -> None:
        self.state["download_all"] = bool(value)
        self.save_state()
        
    @property
    def batch_mode(self) -> bool:
        return self.state.get("batch_mode", False)
    
    @batch_mode.setter
    def batch_mode(self, value: bool) -> None:
        self.state["batch_mode"] = bool(value)
        self.save_state()


class BotSettings:
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: Dict[str, Any] = {
            "start_pic": START_PIC_URL,
            "thumbnail": FIXED_THUMBNAIL_URL,
            "dump_channel_id": DUMP_CHANNEL_ID,
            "dump_channel_username": DUMP_CHANNEL_USERNAME,
            "file_delete_timer": DELETE_TIMER
        }
        self.load_state()
        
    def load_state(self) -> None:
        if bot_settings_collection is not None:
            try:
                for setting in bot_settings_collection.find():
                    name = setting.get("setting_name")
                    if not name:
                        continue
                    if "setting_value" in setting:
                        self.state[name] = setting["setting_value"]
                    elif "value" in setting:
                        self.state[name] = setting["value"]
                logger.info("Bot settings loaded successfully from MongoDB")
            except Exception as e:
                logger.error(f"Error loading bot settings from MongoDB: {e}")
        else:
            try:
                from core.config import JSON_DATA_FILE
                if JSON_DATA_FILE.exists():
                    with open(JSON_DATA_FILE, 'r') as f:
                        data = json.load(f)
                        if "bot_settings" in data:
                            self.state.update(data["bot_settings"])
                    logger.info("Bot settings loaded successfully from JSON")
            except Exception as e:
                logger.error(f"Error loading bot settings: {e}")
    
    def save_state(self) -> None:
        with self._lock:
            if bot_settings_collection is not None:
                try:
                    for key, value in self.state.items():
                        if key is None or (isinstance(key, str) and not key.strip()):
                            continue
                        save_bot_setting(key, value)
                    logger.info("Bot settings saved successfully to MongoDB")
                except Exception as e:
                    logger.error(f"Error saving bot settings to MongoDB: {e}")
            else:
                try:
                    data = load_json_data()
                    data["bot_settings"] = self.state
                    save_json_data(data)
                    logger.info("Bot settings saved successfully to JSON")
                except Exception as e:
                    logger.error(f"Error saving bot settings: {e}")
    
    def get(self, key: str, default=None):
        return self.state.get(key, default)
    
    def set(self, key: str, value: Any) -> None:
        self.state[key] = value
        self.save_state()


class AutoDownloadState:
    
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state: Dict[str, Any] = {
            "enabled": False,
            "last_checked": None,
            "processed_episodes": [],
            "interval_seconds": 300,
            "retry_attempts": 3,
            "retry_delay": 300,
            "processing_info": {
                "title": None,
                "episode": None,
                "quality": None,
                "status": None
            }
        }
        self.load_state()
        
    def get_interval(self) -> int:
        return self.state["interval_seconds"]
    
    def load_state(self) -> None:
        if bot_settings_collection is not None:
            try:
                loaded = load_bot_setting("auto_download_state")
                if loaded and isinstance(loaded, dict):
                    self.state.update(loaded)
                logger.info("Auto download state loaded successfully from MongoDB")
            except Exception as e:
                logger.error(f"Error loading auto download state from MongoDB: {e}")
        else:
            try:
                if AUTO_DOWNLOAD_STATE_FILE.exists():
                    with open(AUTO_DOWNLOAD_STATE_FILE, 'r', encoding='utf-8') as f:
                        loaded_state = json.load(f)
                        self.state.update(loaded_state)
                    logger.info("Auto download state loaded successfully from JSON")
            except json.JSONDecodeError as e:
                logger.error(f"Corrupted state file: {e}")
                self._backup_corrupted_state()
            except Exception as e:
                logger.error(f"Error loading auto download state: {str(e)}")
    
    def _backup_corrupted_state(self) -> None:
        try:
            if AUTO_DOWNLOAD_STATE_FILE.exists():
                backup_path = AUTO_DOWNLOAD_STATE_FILE.with_suffix('.json.bak')
                AUTO_DOWNLOAD_STATE_FILE.rename(backup_path)
                logger.info(f"Corrupted state file backed up to {backup_path}")
        except Exception as e:
            logger.error(f"Failed to backup corrupted state file: {e}")
    
    def save_state(self) -> None:
        with self._lock:
            if bot_settings_collection is not None:
                try:
                    save_bot_setting("auto_download_state", self.state)
                    logger.info("Auto download state saved successfully to MongoDB")
                except Exception as e:
                    logger.error(f"Error saving auto download state to MongoDB: {e}")
            else:
                temp_file = AUTO_DOWNLOAD_STATE_FILE.with_suffix('.tmp')
                try:
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(self.state, f, indent=2)
                    temp_file.replace(AUTO_DOWNLOAD_STATE_FILE)
                    logger.info("Auto download state saved successfully to JSON")
                except Exception as e:
                    logger.error(f"Error saving auto download state: {str(e)}")
                    if temp_file.exists():
                        temp_file.unlink()
    
    @property
    def enabled(self) -> bool:
        return self.state.get("enabled", False)
    
    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.state["enabled"] = bool(value)
        self.save_state()
    
    @property
    def interval(self) -> int:
        return self.state.get("interval_seconds", 300)
    
    @interval.setter
    def interval(self, seconds: int) -> None:
        if not isinstance(seconds, int) or seconds <= 0:
            raise ValueError("Interval must be a positive integer")
        self.state["interval_seconds"] = seconds
        self.save_state()
    
    @property
    def last_checked(self) -> Optional[str]:
        return self.state.get("last_checked")
    
    @last_checked.setter
    def last_checked(self, timestamp: Optional[str]) -> None:
        self.state["last_checked"] = timestamp
        self.save_state()


class UserState:
    
    def __init__(self):
        self.anime_results = None
        self.anime_session = None
        self.anime_title = None
        self.total_episodes = None
        self.episodes = None
        self.current_page = 1
        self.total_pages = None
        self.episode_session = None
        self.episode_number = None
        self.download_links = None
        self.waiting_for_interval = False
        self.last_command_time = 0
        self.progress_message = None
        self.quality_setting = False
        self.rate_limited_until = 0
        self.current_batch_page = 1


anime_queue = AnimeQueue()
quality_settings = QualitySettings()
bot_settings = BotSettings()
auto_download_state = AutoDownloadState()
user_states = {}

__all__ = [
    'AnimeQueue', 'QualitySettings', 'BotSettings', 'AutoDownloadState', 'UserState',
    'anime_queue', 'quality_settings', 'bot_settings', 'auto_download_state', 'user_states',
    'EpisodeState', 'EpisodeTracker', 'episode_tracker'
]
