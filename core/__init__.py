from core.config import (
    BASE_DIR, LOG_DIR, DOWNLOAD_DIR, THUMBNAIL_DIR, DB_NAME,
    API_ID, API_HASH, BOT_TOKEN, ADMIN_CHAT_ID, MONGO_URI, PORT, BOT_USERNAME,
    CHANNEL_ID, CHANNEL_USERNAME, DUMP_CHANNEL_ID, DUMP_CHANNEL_USERNAME,
    FIXED_THUMBNAIL_URL, START_PIC_URL, STICKER_ID,
    AUTO_DOWNLOAD_STATE_FILE, QUALITY_SETTINGS_FILE, SESSION_FILE, JSON_DATA_FILE,
    HEADERS, YTDLP_HEADERS, WORKER_BASE_URL, ANILIST_API,
    Config, logger
)

from core.database import (
    mongo_client, db,
    processed_episodes_collection, anime_banners_collection,
    anime_hashtags_collection, admins_collection, bot_settings_collection,
    load_json_data, save_json_data,
    save_bot_setting, load_bot_setting
)

from core.client import (
    client, pyro_client, PYROFORK_AVAILABLE, FFMPEG_AVAILABLE,
    currently_processing, processing_lock
)

from core.state import (
    AnimeQueue, QualitySettings, BotSettings, AutoDownloadState, UserState,
    anime_queue, quality_settings, bot_settings, auto_download_state, user_states,
    EpisodeState, EpisodeTracker, episode_tracker
)

from core.utils import (
    sanitize_filename, create_short_name, format_size, format_speed, format_time, format_filename,
    download_start_pic, download_start_pic_if_not_exists,
    get_fixed_thumbnail, is_admin, add_admin, remove_admin,
    is_episode_processed, update_processed_qualities, mark_episode_processed,
    is_banner_posted, mark_banner_posted, get_anime_hashtag,
    encode, generate_batch_link, generate_single_link,
    ProgressMessage, UploadProgressBar,
    safe_edit, safe_respond, safe_send_message
)

from core.anime_api import (
    search_anime, get_episode_list, get_latest_releases, get_all_episodes,
    get_download_links, get_dl_link, extract_kwik_link,
    get_anime_info, download_anime_poster, find_closest_episode
)

from core.download import (
    rename_video_with_ffmpeg, fast_upload_file,
    post_anime_with_buttons, post_anime_batch_with_buttons,
    download_anime_batch, download_episode
)

from core.scheduler import (
    setup_scheduler, check_for_new_episodes, process_all_qualities,
    auto_download_latest_episode, process_pending_queue, process_single_episode,
    check_and_process_next_episode, get_currently_processing, set_currently_processing
)

from core.handlers import register_handlers

__all__ = [
    'BASE_DIR', 'LOG_DIR', 'DOWNLOAD_DIR', 'THUMBNAIL_DIR', 'DB_NAME',
    'API_ID', 'API_HASH', 'BOT_TOKEN', 'ADMIN_CHAT_ID', 'MONGO_URI', 'PORT', 'BOT_USERNAME',
    'CHANNEL_ID', 'CHANNEL_USERNAME', 'DUMP_CHANNEL_ID', 'DUMP_CHANNEL_USERNAME',
    'FIXED_THUMBNAIL_URL', 'START_PIC_URL', 'STICKER_ID',
    'HEADERS', 'YTDLP_HEADERS', 'WORKER_BASE_URL', 'ANILIST_API',
    'Config', 'logger',
    
    'mongo_client', 'db',
    'processed_episodes_collection', 'anime_banners_collection',
    'anime_hashtags_collection', 'admins_collection', 'bot_settings_collection',
    'load_json_data', 'save_json_data',
  
    'client', 'pyro_client', 'PYROFORK_AVAILABLE', 'FFMPEG_AVAILABLE',
    'currently_processing', 'processing_lock',
    
    'AnimeQueue', 'QualitySettings', 'BotSettings', 'AutoDownloadState', 'UserState',
    'anime_queue', 'quality_settings', 'bot_settings', 'auto_download_state', 'user_states',
    'EpisodeState', 'EpisodeTracker', 'episode_tracker',
    
    'sanitize_filename', 'create_short_name', 'format_size', 'format_speed', 'format_time', 'format_filename',
    'download_start_pic', 'download_start_pic_if_not_exists',
    'get_fixed_thumbnail', 'is_admin', 'add_admin', 'remove_admin',
    'is_episode_processed', 'update_processed_qualities', 'mark_episode_processed',
    'is_banner_posted', 'mark_banner_posted', 'get_anime_hashtag',
    'encode', 'generate_batch_link', 'generate_single_link',
    'ProgressMessage', 'UploadProgressBar',
    'safe_edit', 'safe_respond', 'safe_send_message',
    
    'search_anime', 'get_episode_list', 'get_latest_releases', 'get_all_episodes',
    'get_download_links', 'get_dl_link', 'extract_kwik_link',
    'get_anime_info', 'download_anime_poster', 'find_closest_episode',
    
    'rename_video_with_ffmpeg', 'fast_upload_file',
    'post_anime_with_buttons', 'post_anime_batch_with_buttons',
    'download_anime_batch', 'download_episode',
    
    'setup_scheduler', 'check_for_new_episodes', 'process_all_qualities',
    'auto_download_latest_episode', 'process_pending_queue', 'process_single_episode',
    'check_and_process_next_episode', 'get_currently_processing', 'set_currently_processing',
    
    'register_handlers'
]
