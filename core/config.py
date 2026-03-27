from __future__ import annotations
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from typing import Any

if not load_dotenv():
    logging.warning("No .env file found or failed to load environment variables")

env_file = Path(".env")
if not env_file.exists():
    logging.warning(f"No .env file found at {env_file.absolute()}")
elif not env_file.read_text().strip():
    logging.warning(f".env file exists but is empty at {env_file.absolute()}")

BASE_DIR = Path.cwd()
LOG_DIR = BASE_DIR / "logs"
DOWNLOAD_DIR = BASE_DIR / "anime_downloads"
THUMBNAIL_DIR = BASE_DIR / "thumbnails"
DB_NAME = "AnimePahe"

for directory in [LOG_DIR, DOWNLOAD_DIR, THUMBNAIL_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "bot.log"
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_FILE))
    ]
)
logger = logging.getLogger(__name__)


class Config:
    ABC=1

def get_env_var(key: str, default: Any = None, required: bool = True) -> Any:
    value = os.environ.get(key, default)
    
    if required and (value is None or (isinstance(value, str) and value.strip() == "")):
        env_file = Path(".env")
        if not env_file.exists():
            raise ValueError(
                f"Environment variable {key} is required but not set.\n"
                f"Please create a .env file in {env_file.absolute()}"
            )
        else:
            raise ValueError(
                f"Environment variable {key} is required but not set.\n"
                f"Please add {key}=your_value to your .env file"
            )
    
    logger.debug(f"Loaded environment variable: {key}")
    return value


logger.info("Loading essential configuration...")
try:
    API_ID = int(get_env_var("API_ID"))
    API_HASH = get_env_var("API_HASH")
    BOT_TOKEN = get_env_var("BOT_TOKEN")
    ADMIN_CHAT_ID = int(get_env_var("ADMIN_CHAT_ID"))
    MONGO_URI = get_env_var("MONGO_URI", required=False)
    PORT = int(get_env_var("PORT", "8090"))
    BOT_USERNAME = get_env_var("BOT_USERNAME", "BlakiteX9AnimeBot")
    logger.info("Successfully loaded all environment variables")
except ValueError as e:
    logger.error(f"Environment variable error: {e}")
    raise

DB_NAME = get_env_var("DB_NAME", "AnimePahe", required=False)
def get_admins_from_env():
    raw = get_env_var("ADMIN_CHAT_ID")
    return [int(x.strip()) for x in raw.split(",") if x.strip()]

ADMINS = get_admins_from_env()
OWNER_ID = ADMINS[0]
CHANNEL_ID = get_env_var("CHANNEL_ID", required=False)
CHANNEL_NAME = get_env_var("CHANNEL_NAME", required=False)
CHANNEL_USERNAME = get_env_var("CHANNEL_USERNAME", required=False)
DUMP_CHANNEL_ID = get_env_var("DUMP_CHANNEL_ID", required=False)
DUMP_CHANNEL_USERNAME = get_env_var("DUMP_CHANNEL_USERNAME", required=False)

if CHANNEL_ID:
    try:
        CHANNEL_ID = int(CHANNEL_ID)
        logger.info(f"Channel ID configured: {CHANNEL_ID}")
    except ValueError:
        logger.warning("Invalid CHANNEL_ID provided - must be a number. Falling back to username if available.")
        CHANNEL_ID = None

if CHANNEL_USERNAME:
    if not CHANNEL_USERNAME.startswith('@'):
        CHANNEL_USERNAME = f"{CHANNEL_USERNAME}"
    logger.info(f"Channel username configured: {CHANNEL_USERNAME}")

if DUMP_CHANNEL_ID:
    try:
        DUMP_CHANNEL_ID = int(DUMP_CHANNEL_ID)
        logger.info(f"Dump Channel ID configured: {DUMP_CHANNEL_ID}")
    except ValueError:
        logger.warning("Invalid DUMP_CHANNEL_ID provided - must be a number. Falling back to username if available.")
        DUMP_CHANNEL_ID = None

if DUMP_CHANNEL_USERNAME:
    if not DUMP_CHANNEL_USERNAME.startswith('@'):
        DUMP_CHANNEL_USERNAME = f"@{DUMP_CHANNEL_USERNAME}"
    logger.info(f"Dump channel username configured: {DUMP_CHANNEL_USERNAME}")

if not CHANNEL_ID and not CHANNEL_USERNAME:
    logger.warning("No main channel ID or username configured. Files will only be sent to dump channel.")

if not DUMP_CHANNEL_ID and not DUMP_CHANNEL_USERNAME:
    logger.warning("No dump channel ID or username configured. Files will only be sent to users directly.")

FIXED_THUMBNAIL_URL = get_env_var(
    "FIXED_THUMBNAIL_PIC",
    "https://i.postimg.cc/y8TrLtdQ/photo-6093802189613632649-y.jpg",
    required=False
)

START_PIC_URL = get_env_var(
    "START_PIC_URL",
    "https://imgs.search.brave.com/9n5_FAipMAH3ic1LtbHx3btylHNWppO2rl4gXnRjr1g/rs:fit:860:0:0:0/g:ce/aHR0cHM6Ly93YWxs/cGFwZXJjYXZlLmNv/bS93cC93cDE4MzM1/NTIuanBn",
    required=False
)

STICKER_ID = get_env_var(
    "STICKER_ID",
    "CAACAgUAAxkBAAEQJ6hpV0JDpDDOI68yH7lV879XbIWiFwACGAADQ3PJEs4sW1y9vZX3OAQ",
    required=False
)

DELETE_TIMER = int(get_env_var("DELETE_TIMER", 1800, required=False))
AUTO_DOWNLOAD_STATE_FILE = BASE_DIR / "auto_download_state.json"
QUALITY_SETTINGS_FILE = BASE_DIR / "quality_settings.json"
SESSION_FILE = BASE_DIR / "anime_bot.session"
JSON_DATA_FILE = BASE_DIR / "anime_data.json"
FFMPEG_PATH = "ffmpeg"

HEADERS = {
    'authority': 'animepahe.si',
    'accept': 'application/json, text/javascript, */*; q=0.01',
    'accept-language': 'en-US,en;q=0.9',
    'cookie': '__ddg2_=;',
    'dnt': '1',
    'sec-ch-ua': '"Not A(Brand";v="99", "Google Chrome";v="124", "Chromium";v="124"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-origin',
    'x-requested-with': 'XMLHttpRequest',
    'referer': 'https://animepahe.si/',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
}

YTDLP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Referer': 'https://kwik.cx/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'same-origin',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0'
}

WORKER_BASE_URL = get_env_var(
    "WORKER_BASE_URL",
    "https://pahe-babu.raviguj4554.workers.dev/?d=",
    required=False
)

PAHE_LINKS_WORKER_URL = get_env_var(
    "PAHE_LINKS_WORKER_URL",
    "https://pahelinks.raviguj4554.workers.dev/",
    required=False
)

ANILIST_API = "https://graphql.anilist.co"

SEARCH, SELECT_ANIME, SELECT_EPISODE, SELECT_QUALITY, DOWNLOADING = range(5)
AUTO_DISABLED, AUTO_ENABLED = range(2)

HELP_TEXT='''<b>
<blockquote>✦ 𝗛𝗘𝗟𝗣𝗘𝗥 ✦</blockquote>
──────────────────
<blockquote>シ 𝗖𝗢𝗠𝗠𝗔𝗡𝗗𝗦:</blockquote>
<blockquote expandable><code>/cancel</code> - ᴄᴀɴᴄᴇʟ ᴄᴜʀʀᴇɴᴛ ᴏᴘᴇʀᴀᴛɪᴏɴ
<code>/latest</code> - ɢᴇᴛ ʟᴀᴛᴇsᴛ ᴀɪʀɪɴɢ ᴀɴɪᴍᴇ
<code>/airing</code> - ɢᴇᴛ ᴄᴜʀʀᴇɴᴛʟʏ ᴀɪʀɪɴɢ ᴀɴɪᴍᴇ
<code>/del_timer</code> - sᴇᴛ ғɪʟᴇ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇʀ
<code>/addchnl [id] [name]</code> - sᴇᴛ ᴀ ᴘᴀʀᴛɪᴄᴜʟᴀʀ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟ
<code>/removechnl [id] [name]</code> - ʀᴇᴍᴏᴠᴇ ᴀ ᴘᴀʀᴛɪᴄᴜʟᴀʀ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟ
<code>/listchnl</code> - sʜᴏᴡ ᴀʟʟ ᴘᴀʀᴛɪᴄᴜʟᴀʀ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟs ᴀs ᴀ ʟɪsᴛ
<code>/set_request_time [HH:MM]</code> - sᴇᴛ ᴅᴀɪʟʏ ʀᴇǫᴜᴇsᴛ ᴘʀᴏᴄᴇssɪɴɢ ᴛɪᴍᴇ (IST)
<code>/set_max_requests [number]</code> - sᴇᴛ ᴍᴀxɪᴍᴜᴍ ɴᴜᴍʙᴇʀ ᴏғ ᴄᴏɴᴄᴜʀʀᴇɴᴛ ʀᴇǫᴜᴇsᴛs
<code>/view_requests</code> - sʜᴏᴡ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs
<code>/set_request_group [group_id]</code> - sᴇᴛ ᴛʜᴇ ʀᴇǫᴜᴇsᴛ ɢʀᴏᴜᴘ
<code>/request [anime name]</code> or <code>#request [anime name]</code> - ʀᴇǫᴜᴇsᴛ ᴀɴ ᴀɴɪᴍᴇ ᴛᴏ ʙᴇ ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ
<code>/addtask [number]</code> - ᴅᴏᴡɴʟᴏᴀᴅ sᴘᴇᴄɪғɪᴄ ᴀɴɪᴍᴇ ғʀᴏᴍ ʟᴀᴛᴇsᴛ ᴀɪʀɪɴɢ ʟɪsᴛ
<code>/redownload [number]</code> - ғᴏʀᴄᴇ ʀᴇᴅᴏᴡɴʟᴏᴀᴅ ᴀ sᴘᴇᴄɪғɪᴄ ᴀɴɪᴍᴇ
<code>/add_admin [user_id]</code> - ᴀᴅᴅ ᴀ ɴᴇᴡ ᴀᴅᴍɪɴ
<code>/remove_admin [user_id]</code> - ʀᴇᴍᴏᴠᴇ ᴀɴ ᴀᴅᴍɪɴ</blockquote expandable>
──────────────────
<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/GenAnimeOngoing'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 𝗔𝗻𝗶𝗺𝗲 - 𝗪𝗶𝗻𝘁𝗲𝗿 𝟮𝟬𝟮𝟲</a></blockquote></b>'''
