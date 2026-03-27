from __future__ import annotations
import logging
import subprocess
import asyncio

from telethon import TelegramClient

from core.config import (
    API_ID, API_HASH, BOT_TOKEN, SESSION_FILE,
    FFMPEG_PATH
)

logger = logging.getLogger(__name__)

client = TelegramClient(str(SESSION_FILE), API_ID, API_HASH)

currently_processing = False
processing_lock = asyncio.Lock()

PYROFORK_AVAILABLE = False
pyro_client = None

try:
    from pyrogram import Client as PyroClient
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    PYROFORK_AVAILABLE = True
    logger.info("Pyrofork imported successfully for fast uploads")
except ImportError:
    PYROFORK_AVAILABLE = False
    logger.warning("Pyrofork not available. Using standard Telethon uploads.")

if PYROFORK_AVAILABLE:
    try:
        pyro_client = PyroClient(
            "AnimePahe",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN
        )
        logger.info("Pyrofork client initialized for fast uploads")
    except Exception as e:
        logger.error(f"Failed to initialize Pyrofork client: {e}")
        pyro_client = None

FFMPEG_AVAILABLE = False
try:
    subprocess.run([FFMPEG_PATH, "-version"], check=True, capture_output=True)
    FFMPEG_AVAILABLE = True
    logger.info("FFmpeg is available")
except (subprocess.CalledProcessError, FileNotFoundError):
    logger.warning("FFmpeg is not available. Some features may not work.")


def install_ffmpeg():
    try:
        subprocess.run([FFMPEG_PATH, "-version"], check=True, capture_output=True)
        return True
    except:
        try:
            logger.info("Attempting to install FFmpeg with apt-get...")
            subprocess.run(["apt-get", "update"], check=True)
            subprocess.run(["apt-get", "install", "-y", "ffmpeg"], check=True)
            subprocess.run([FFMPEG_PATH, "-version"], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"Failed to install FFmpeg with apt-get: {e}")
            try:
                logger.info("Attempting to install FFmpeg with yum...")
                subprocess.run(["yum", "install", "-y", "ffmpeg"], check=True)
                subprocess.run([FFMPEG_PATH, "-version"], check=True, capture_output=True)
                return True
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.error(f"Failed to install FFmpeg with yum: {e}")
                return False


if not FFMPEG_AVAILABLE and not install_ffmpeg():
    logger.error("FFmpeg is not available. Video conversion will be skipped.")
else:
    FFMPEG_AVAILABLE = True


def install_ytdlp():
    try:
        subprocess.run(["pip", "install", "yt-dlp"], check=True)
        return True
    except:
        return False

try:
    import yt_dlp
except ImportError:
    if install_ytdlp():
        import yt_dlp
