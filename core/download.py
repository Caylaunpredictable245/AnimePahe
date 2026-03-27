from __future__ import annotations
import os
import re
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

import requests
import aiohttp
from telethon.errors import FloodWaitError
from telethon.tl.custom import Button
from telethon import types
from telethon.tl.types import PeerChannel

from core.config import *
from core.client import client, FFMPEG_AVAILABLE, pyro_client, PYROFORK_AVAILABLE
from core.state import (
    quality_settings, bot_settings, auto_download_state, anime_queue
)
from core.utils import (
    sanitize_filename, format_filename, format_size, format_speed, format_time,
    get_fixed_thumbnail, get_anime_hashtag, mark_banner_posted,
    is_episode_processed, update_processed_qualities, mark_episode_processed,
    ProgressMessage, UploadProgressBar, safe_respond, safe_send_message,
    generate_batch_link
)
from core.anime_api import (
    search_anime, get_episode_list, get_all_episodes, get_latest_releases,
    get_download_links, extract_kwik_link, get_dl_link, get_anime_info,
    find_closest_episode
)

logger = logging.getLogger(__name__)

try:
    import yt_dlp
except ImportError:
    logger.error("yt-dlp not installed")

async def resolve_channel(client, target):
    entity = await client.get_entity(target)
    if not isinstance(entity, types.Channel):
        raise RuntimeError(f"Target is not a channel: {target}")
    return PeerChannel(entity.id)

async def rename_video_with_ffmpeg(input_path: str, output_path: str) -> bool:
    if not FFMPEG_AVAILABLE:
        logger.warning("FFmpeg not available. Skipping video conversion.")
        return False
        
    try:
        cmd = [
            FFMPEG_PATH,
            '-i', input_path,
            '-c', 'copy',
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return True
        else:
            logger.warning(f"FFmpeg error: {stderr.decode()}")
            return False
    except Exception as e:
        logger.warning(f"Error renaming video with FFmpeg: {e}")
        return False


async def fast_upload_file(file_path, caption, thumb_path=None, progress_callback=None):
    global pyro_client, client
    
    dump_msg_id = None
    upload_success = False
    target_channel = DUMP_CHANNEL_ID or DUMP_CHANNEL_USERNAME
    
    if not target_channel:
        logger.warning("No dump channel configured")
        return None
    
    UPLOAD_TIMEOUT = 600
    
    if PYROFORK_AVAILABLE and pyro_client:
        try:
            if not pyro_client.is_connected:
                try:
                    await asyncio.wait_for(pyro_client.start(), timeout=30)
                    logger.info("Started Pyrofork client for fast upload")
                except asyncio.TimeoutError:
                    logger.warning("Pyrofork client start timed out, falling back to Telethon")
                    raise Exception("Pyrofork start timeout")
            
            logger.info(f"Uploading with Pyrofork: {os.path.basename(file_path)}")
            
            pyro_msg = await asyncio.wait_for(
                pyro_client.send_document(
                    chat_id=target_channel,
                    document=file_path,
                    caption=caption,
                    thumb=thumb_path,
                    file_name=os.path.basename(file_path),
                    progress=progress_callback,
                    force_document=True
                ),
                timeout=UPLOAD_TIMEOUT
            )
            
            dump_msg_id = pyro_msg.id
            upload_success = True
            logger.info(f"Fast upload completed using Pyrofork: {dump_msg_id}")
            
        except asyncio.TimeoutError:
            logger.error(f"Pyrofork upload timed out after {UPLOAD_TIMEOUT}s, falling back to Telethon")
            upload_success = False
        except Exception as e:
            logger.error(f"Pyrofork upload failed: {e}")
            upload_success = False
    
    if not upload_success:
        try:
            logger.info(f"Uploading with Telethon: {os.path.basename(file_path)}")
            
            msg = await client.send_file(
                target_channel,
                file_path,
                caption=caption,
                thumb=thumb_path,
                force_document=True,
                attributes=None,
                supports_streaming=False,
                part_size_kb=512,
                progress_callback=progress_callback,
                link_preview=False
            )
            
            dump_msg_id = msg.id
            upload_success = True
            logger.info(f"Upload completed using Telethon: {dump_msg_id}")
            
        except FloodWaitError as e:
            logger.error(f"Flood wait during upload: {e.seconds} seconds")
            await asyncio.sleep(e.seconds + 5)
            try:
                msg = await client.send_file(
                    target_channel,
                    file_path,
                    caption=caption,
                    thumb=thumb_path,
                    force_document=True,
                    attributes=None,
                    supports_streaming=False,
                    part_size_kb=512,
                    progress_callback=progress_callback,
                    link_preview=False
                )
                dump_msg_id = msg.id
                upload_success = True
            except Exception as retry_error:
                logger.error(f"Upload retry failed: {retry_error}")
        except Exception as e:
            logger.error(f"Telethon upload failed: {e}")
    
    return dump_msg_id if upload_success else None



def get_optimal_part_size(file_size_bytes: int) -> int:
    MB = 1024 * 1024
    
    if file_size_bytes < 100 * MB:
        return 256
    elif file_size_bytes < 500 * MB:
        return 512
    else:
        return 512


def calculate_upload_timeout(file_size_bytes: int, min_speed_kbps: int = 100) -> int:
    MB = 1024 * 1024
    KB = 1024
    
    min_speed_bytes = min_speed_kbps * KB
    
    base_time = file_size_bytes / min_speed_bytes
    
    buffered_time = base_time * 1.5
    
    total_time = buffered_time + 60
    
    return max(300, min(3600, int(total_time)))


async def robust_upload_file(
    file_path: str,
    caption: str,
    thumb_path: str = None,
    max_retries: int = 3,
    progress_callback = None
) -> Optional[int]:
    target_channel = DUMP_CHANNEL_ID or DUMP_CHANNEL_USERNAME
    
    if not target_channel:
        logger.error("No dump channel configured for upload")
        return None
    
    if not os.path.exists(file_path):
        logger.error(f"File does not exist: {file_path}")
        return None
    
    file_size = os.path.getsize(file_path)
    if file_size < 1000:
        logger.error(f"File too small (corrupt?): {file_path} ({file_size} bytes)")
        return None
    
    part_size_kb = get_optimal_part_size(file_size)
    upload_timeout = calculate_upload_timeout(file_size)
    is_large_file = file_size > 400 * 1024 * 1024
    
    if is_large_file:
        upload_timeout = max(upload_timeout, 3600)
        logger.info(f"Large file detected ({format_size(file_size)}), using extended timeout: {upload_timeout}s")
    
    logger.info(f"Upload settings for {format_size(file_size)}: "
                f"part_size={part_size_kb}KB, timeout={upload_timeout}s, max_retries={max_retries}")
    
    last_error = None
    consecutive_failures = 0
    flood_wait_count = 0
    max_flood_waits = 5
    
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Upload attempt {attempt}/{max_retries}: {os.path.basename(file_path)} ({format_size(file_size)})")
            
            msg = await asyncio.wait_for(
                client.send_file(
                    target_channel,
                    file_path,
                    caption=caption,
                    thumb=thumb_path,
                    force_document=True,
                    attributes=None,
                    supports_streaming=False,
                    part_size_kb=part_size_kb,
                    progress_callback=progress_callback,
                    link_preview=False
                ),
                timeout=upload_timeout
            )
            
            if msg and msg.id:
                logger.info(f"Upload SUCCESS: {os.path.basename(file_path)} -> msg_id={msg.id} (attempt {attempt})")
                return msg.id
            else:
                last_error = "Invalid message returned"
                consecutive_failures += 1
                logger.error(f"Upload attempt {attempt} returned invalid message: {msg}")
                
        except asyncio.TimeoutError:
            last_error = f"Upload timed out after {upload_timeout}s"
            consecutive_failures += 1
            logger.error(f"Upload attempt {attempt}/{max_retries} TIMEOUT: {last_error}")
            
        except FloodWaitError as e:
            flood_wait_count += 1
            last_error = f"FloodWait: {e.seconds}s"
            logger.warning(f"Upload attempt {attempt} FloodWait: {e.seconds}s (flood #{flood_wait_count})")
            
            if flood_wait_count >= max_flood_waits:
                logger.error(f"Too many FloodWait errors ({flood_wait_count}), aborting upload")
                consecutive_failures = max_retries
                break
            
            await asyncio.sleep(e.seconds + 5)
            continue
            
        except Exception as e:
            last_error = str(e)
            consecutive_failures += 1
            logger.error(f"Upload attempt {attempt}/{max_retries} FAILED: {e}")
        
        if consecutive_failures >= max_retries:
            break
        
        if attempt < max_retries:
            wait_time = 10 * (2 ** (attempt - 1))
            logger.info(f"Waiting {wait_time}s before retry {attempt + 1}...")
            await asyncio.sleep(wait_time)
    
    logger.error(
        f"Upload FAILED after {max_retries} attempts for {os.path.basename(file_path)} "
        f"({format_size(file_size)}). Last error: {last_error}. "
        f"Consecutive failures: {consecutive_failures}, FloodWaits: {flood_wait_count}"
    )
    return None


async def post_anime_to_dedicated_channel(client, anime_title, anime_info, episode_number, audio_type, quality_files, dedicated_channel_id, dedicated_channel_username):
    from core.database import get_anime_channel

    try:
        anime_id = anime_info.get('id')
        if not anime_id:
            logger.error(f"No anime ID found for {anime_title}")
            return None
        
        banner_url = f"https://img.anili.st/media/{anime_id}"
        banner_path = os.path.join(THUMBNAIL_DIR, f"{sanitize_filename(anime_title)}_banner_dedicated.jpg")

        banner_downloaded = False
        for attempt in range(3):
            try:
                connector = aiohttp.TCPConnector(limit=1, force_close=True)
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(banner_url, ssl=False) as response:
                        if response.status == 200:
                            with open(banner_path, 'wb') as f:
                                f.write(await response.read())
                            banner_downloaded = True
                            break
                        else:
                            logger.warning(f"Attempt {attempt + 1}: Banner download returned status {response.status}")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to download banner: {e}")
                await asyncio.sleep(2)
                continue
        
        if not banner_downloaded:
            logger.warning(f"Could not download banner for {anime_title}, will post without image")
        
        english_title = anime_info.get('title', {}).get('english') or anime_info.get('title', {}).get('romaji')
        romaji_title = anime_info.get('title', {}).get('romaji')
        
        hashtag = get_anime_hashtag(anime_title)
        
        main_channel_username = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        
        qualities_str = " | ".join(quality_files.keys())
        
        dedicated_caption = (
            f"<blockquote><b><i>✦ {english_title} | {romaji_title} ✦</i></b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<blockquote><b>➥ Episode: {episode_number if episode_number else 'N/A'}</b>\n"
            f"<b>➥ Quality: {qualities_str}</b>\n"
            f"<b>➥ Audio: {audio_type}</b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b><blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{main_channel_username}'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 - 𝗔𝗿𝗰</a></blockquote></b>"
        )
        
        buttons = []
        for quality, file_ids in quality_files.items():
            batch_link = await generate_batch_link(file_ids, quality)
            if batch_link:
                buttons.append(Button.url(quality, batch_link))
        
        keyboard = []
        for i in range(0, len(buttons), 2):
            row = buttons[i:i+2]
            keyboard.append(row)
        
        if not keyboard:
            keyboard = None
        
        try:
            target_raw = dedicated_channel_id or dedicated_channel_username
            target_channel = await resolve_channel(client, target_raw)
            
            if banner_downloaded and os.path.exists(banner_path):
                dedicated_msg = await client.send_file(
                    target_channel,
                    banner_path,
                    caption=dedicated_caption,
                    parse_mode='html',
                    buttons=keyboard
                )
            else:
                dedicated_msg = await client.send_message(
                    target_channel,
                    dedicated_caption,
                    parse_mode='html',
                    buttons=keyboard,
                    link_preview=False
                )
            logger.info(f"Posted to dedicated channel for {anime_title}: {target_channel}")
        except Exception as e:
            logger.error(f"Error posting to dedicated channel: {e}")
            return None
        
        if CHANNEL_ID and CHANNEL_USERNAME:
            try:
                main_channel_username = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
                
                
                notification_caption = (
                    f"<blockquote><b><i>✦ {english_title} | {romaji_title} ✦</i></b></blockquote>\n"
                    f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
                    f"<blockquote><b>➥ Episode: {episode_number if episode_number else 'N/A'}</b>\n"
                    f"<b>➥ Quality: {qualities_str}</b>\n"
                    f"<b>➥ Audio: {audio_type}</b></blockquote>\n"
                    f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
                    f"<b><blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{main_channel_username}'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 - 𝗔𝗿𝗰</a></blockquote></b>"
                )
                
                join_button = Button.url("𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗡𝗼𝘄", f"https://t.me/{dedicated_channel_username}" if dedicated_channel_username else "")
                
                main_keyboard = []
                if join_button.url:
                    main_keyboard.append([join_button])

                main_channel = await resolve_channel(client, CHANNEL_ID)
                
                if banner_downloaded and os.path.exists(banner_path):
                    await client.send_file(
                        main_channel,
                        banner_path,
                        caption=notification_caption,
                        parse_mode='html',
                        buttons=main_keyboard if main_keyboard else None,
                        link_preview=False
                    )
                else:
                    await client.send_message(
                        main_channel,
                        notification_caption,
                        parse_mode='html',
                        buttons=main_keyboard if main_keyboard else None,
                        link_preview=False
                    )
                logger.info(f"Sent notification to main channel for {anime_title}")
            except Exception as e:
                logger.error(f"Error sending notification to main channel: {e}")

        
        mark_banner_posted(anime_title)
        return dedicated_msg
    
    except Exception as e:
        logger.error(f"Error posting to dedicated channel: {e}")
        return None
    finally:
        try:
            if os.path.exists(banner_path):
                os.remove(banner_path)
        except:
            pass



async def _post_fallback_message(client, anime_title, episode_number, audio_type, quality_files):
    try:
        main_channel_username = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        hashtag = get_anime_hashtag(anime_title)
        qualities_str = " | ".join(quality_files.keys()) if quality_files else "N/A"
        
        caption = (
            f"<blockquote><b><i>✦ {english_title} | {romaji_title} ✦</i></b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<blockquote><b>➥ Episode: {episode_number if episode_number else 'N/A'}</b>\n"
            f"<b>➥ Quality: {qualities_str}</b>\n"
            f"<b>➥ Audio: {audio_type}</b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b><blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{main_channel_username}'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 - 𝗔𝗿𝗰</a></blockquote></b>"
        )
        
        buttons = []
        if quality_files:
            for quality, file_ids in quality_files.items():
                try:
                    batch_link = await generate_batch_link(file_ids, quality)
                    if batch_link:
                        buttons.append(Button.url(quality, batch_link))
                except Exception as e:
                    logger.error(f"Error generating batch link for {quality}: {e}")
        
        keyboard = []
        for i in range(0, len(buttons), 2):
            row = buttons[i:i+2]
            keyboard.append(row)
        
        if not keyboard:
            keyboard = None
        
        target_raw = CHANNEL_ID or CHANNEL_USERNAME
        target_channel = await resolve_channel(client, target_raw)
        if target_channel:
            msg = await client.send_message(
                target_channel,
                caption,
                parse_mode='html',
                buttons=keyboard,
                link_preview=False
            )
            logger.info(f"Posted fallback message for {anime_title}")
            mark_banner_posted(anime_title)
            return msg
        else:
            logger.error("No channel configured for fallback message")
            return None
            
    except Exception as e:
        logger.error(f"Error in fallback posting: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


async def post_anime_with_buttons(client, anime_title, anime_info, episode_number, audio_type, quality_files):
    from core.database import get_anime_channel
    
    try:
        try:
            anime_channel = await get_anime_channel(anime_title)
            if anime_channel:
                dedicated_channel_id = anime_channel.get('channel_id')
                dedicated_channel_username = anime_channel.get('channel_username')
                return await post_anime_to_dedicated_channel(
                    client, anime_title, anime_info, episode_number, audio_type, 
                    quality_files, dedicated_channel_id, dedicated_channel_username
                )
        except Exception as e:
            logger.error(f"Error checking/posting to dedicated channel: {e}")
        
        if not CHANNEL_ID and not CHANNEL_USERNAME:
            logger.warning("No main channel configured. Banner not posted.")
            return None
        
        if not anime_info:
            logger.warning(f"No anime info available for {anime_title}, posting with fallback")
            return await _post_fallback_message(client, anime_title, episode_number, audio_type, quality_files)
        
        anime_id = anime_info.get('id')
        if not anime_id:
            logger.warning(f"No anime ID found for {anime_title}, posting with fallback")
            return await _post_fallback_message(client, anime_title, episode_number, audio_type, quality_files)
    except Exception as e:
        logger.error(f"Error in post_anime_with_buttons setup: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            return await _post_fallback_message(client, anime_title, episode_number, audio_type, quality_files)
        except Exception as fallback_error:
            logger.error(f"Fallback posting also failed: {fallback_error}")
            return None
    
    banner_path = None
    try:
        banner_url = f"https://img.anili.st/media/{anime_id}"
        
        banner_path = os.path.join(THUMBNAIL_DIR, f"{sanitize_filename(anime_title)}_banner.jpg")
        
        banner_downloaded = False
        for attempt in range(3):
            try:
                connector = aiohttp.TCPConnector(limit=1, force_close=True)
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(banner_url, ssl=False) as response:
                        if response.status == 200:
                            with open(banner_path, 'wb') as f:
                                f.write(await response.read())
                            banner_downloaded = True
                            break
                        else:
                            logger.warning(f"Attempt {attempt + 1}: Banner download returned status {response.status}")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to download banner: {e}")
                await asyncio.sleep(2)
                continue
        
        if not banner_downloaded:
            logger.warning(f"Could not download banner for {anime_title}, will post without image")
        
        title_info = anime_info.get('title', {}) or {}
        english_title = title_info.get('english') or title_info.get('romaji') or anime_title
        romaji_title = title_info.get('romaji') or anime_title
        
        hashtag = get_anime_hashtag(anime_title)
        
        main_channel_username = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        
        qualities_str = " | ".join(quality_files.keys()) if quality_files else "N/A"
        caption = (
            f"<blockquote><b><i>✦ {english_title} | {romaji_title} ✦</i></b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<blockquote><b>➥ Episode: {episode_number if episode_number else 'N/A'}</b>\n"
            f"<b>➥ Quality: {qualities_str}</b>\n"
            f"<b>➥ Audio: {audio_type}</b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b><blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{main_channel_username}'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 - 𝗔𝗿𝗰</a></blockquote></b>"
        )

        buttons = []
        if quality_files:
            for quality, file_ids in quality_files.items():
                try:
                    batch_link = await generate_batch_link(file_ids, quality)
                    if batch_link:
                        buttons.append(Button.url(quality, batch_link))
                except Exception as e:
                    logger.error(f"Error generating batch link for {quality}: {e}")

        keyboard = []
        for i in range(0, len(buttons), 2):
            row = buttons[i:i+2]
            keyboard.append(row)

        if not keyboard:
            keyboard = None

        msg = None
        try:
            if banner_downloaded and os.path.exists(banner_path):
                if CHANNEL_ID:
                    msg = await client.send_file(
                        CHANNEL_ID,
                        banner_path,
                        caption=caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                elif CHANNEL_USERNAME:
                    msg = await client.send_file(
                        CHANNEL_USERNAME,
                        banner_path,
                        caption=caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                logger.info(f"Posted banner with buttons for {anime_title}")
            else:
                if CHANNEL_ID:
                    msg = await client.send_message(
                        CHANNEL_ID,
                        caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                elif CHANNEL_USERNAME:
                    msg = await client.send_message(
                        CHANNEL_USERNAME,
                        caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                logger.info(f"Posted text message (no banner) for {anime_title}")

            try:
                await client.send_message(
                    CHANNEL_ID if CHANNEL_ID else CHANNEL_USERNAME,
                    file=STICKER_ID
                )
                logger.info("Sent sticker after banner")
            except Exception as e:
                logger.error(f"Error sending sticker: {e}")
            
            mark_banner_posted(anime_title)
            return msg
            
        except FloodWaitError as e:
            logger.warning(f"FloodWait during posting: {e.seconds} seconds, waiting...")
            await asyncio.sleep(e.seconds + 5)
            try:
                target = CHANNEL_ID if CHANNEL_ID else CHANNEL_USERNAME
                msg = await client.send_message(target, caption, parse_mode='html', buttons=keyboard, link_preview=False)
                mark_banner_posted(anime_title)
                return msg
            except Exception as retry_error:
                logger.error(f"Retry after FloodWait failed: {retry_error}")
                return None
        except Exception as e:
            logger.error(f"Error posting banner with buttons: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    except Exception as e:
        logger.error(f"Critical error in post_anime_with_buttons: {e}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            return await _post_fallback_message(client, anime_title, episode_number, audio_type, quality_files)
        except:
            return None
    finally:
        try:
            if banner_path and os.path.exists(banner_path):
                os.remove(banner_path)
        except:
            pass


async def post_anime_batch_with_buttons(client, anime_title, anime_info, quality_files, episode_number=None, audio_type=None):
    try:
        if not CHANNEL_ID and not CHANNEL_USERNAME:
            logger.warning("No main channel configured. Banner not posted.")
            return None
        
        if not anime_info:
            logger.warning(f"No anime info for batch post of {anime_title}")
            return await _post_batch_fallback(client, anime_title, quality_files)
        
        anime_id = anime_info.get('id')
        if not anime_id:
            logger.warning(f"No anime ID found for {anime_title}")
            return await _post_batch_fallback(client, anime_title, quality_files)
    except Exception as e:
        logger.error(f"Error in post_anime_batch_with_buttons setup: {e}")
        return None
    
    banner_path = None
    try:
        banner_url = f"https://img.anili.st/media/{anime_id}"
        
        banner_path = os.path.join(THUMBNAIL_DIR, f"{sanitize_filename(anime_title)}_banner.jpg")
        
        banner_downloaded = False
        for attempt in range(3):
            try:
                connector = aiohttp.TCPConnector(limit=1, force_close=True)
                timeout = aiohttp.ClientTimeout(total=30)
                async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                    async with session.get(banner_url, ssl=False) as response:
                        if response.status == 200:
                            with open(banner_path, 'wb') as f:
                                f.write(await response.read())
                            banner_downloaded = True
                            break
                        else:
                            logger.warning(f"Attempt {attempt + 1}: Banner download returned status {response.status}")
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1}: Failed to download banner: {e}")
                await asyncio.sleep(2)
                continue
        
        if not banner_downloaded:
            logger.warning(f"Could not download banner for {anime_title}, will post without image")

        title_info = anime_info.get('title', {}) or {}
        english_title = title_info.get('english') or title_info.get('romaji') or anime_title
        romaji_title = title_info.get('romaji') or anime_title
        
        hashtag = get_anime_hashtag(anime_title)
        
        main_channel_username = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        total_episodes = 0
        if quality_files:
            for quality, file_ids in quality_files.items():
                total_episodes = max(total_episodes, len(file_ids) if file_ids else 0)

        qualities_str = " | ".join(quality_files.keys()) if quality_files else "N/A"
        audio_str = audio_type if audio_type else "N/A"
        caption = (
            f"<blockquote><b><i>✦ {english_title} | {romaji_title} ✦</i></b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<blockquote><b>➥ Episode: {total_episodes if total_episodes else 'N/A'}</b>\n"
            f"<b>➥ Quality: {qualities_str}</b>\n"
            f"<b>➥ Audio: {audio_str}</b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b><blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{main_channel_username}'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 - 𝗔𝗿𝗰</a></blockquote></b>"
        )

        buttons = []
        if quality_files:
            for quality, file_ids in quality_files.items():
                try:
                    batch_link = await generate_batch_link(file_ids, quality)
                    if batch_link:
                        buttons.append(Button.url(quality, batch_link))
                except Exception as e:
                    logger.error(f"Error generating batch link for {quality}: {e}")
        
        keyboard = []
        for i in range(0, len(buttons), 2):
            row = buttons[i:i+2]
            keyboard.append(row)
        
        if not keyboard:
            keyboard = None
        
        msg = None
        try:
            if banner_downloaded and os.path.exists(banner_path):
                if CHANNEL_ID:
                    msg = await client.send_file(
                        CHANNEL_ID,
                        banner_path,
                        caption=caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                elif CHANNEL_USERNAME:
                    msg = await client.send_file(
                        CHANNEL_USERNAME,
                        banner_path,
                        caption=caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                logger.info(f"Posted batch banner with buttons for {anime_title}")
            else:
                if CHANNEL_ID:
                    msg = await client.send_message(
                        CHANNEL_ID,
                        caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                elif CHANNEL_USERNAME:
                    msg = await client.send_message(
                        CHANNEL_USERNAME,
                        caption,
                        parse_mode='html',
                        buttons=keyboard,
                        link_preview=False
                    )
                logger.info(f"Posted batch text message (no banner) for {anime_title}")
            
            try:
                await client.send_message(
                    CHANNEL_ID if CHANNEL_ID else CHANNEL_USERNAME,
                    file=STICKER_ID
                )
                logger.info("Sent sticker after banner")
            except Exception as e:
                logger.error(f"Error sending sticker: {e}")
            
            mark_banner_posted(anime_title)
            return msg
            
        except FloodWaitError as e:
            logger.warning(f"FloodWait during batch posting: {e.seconds} seconds")
            await asyncio.sleep(e.seconds + 5)
            try:
                target = CHANNEL_ID if CHANNEL_ID else CHANNEL_USERNAME
                msg = await client.send_message(target, caption, parse_mode='html', buttons=keyboard, link_preview=False)
                mark_banner_posted(anime_title)
                return msg
            except Exception as retry_error:
                logger.error(f"Retry after FloodWait failed: {retry_error}")
                return None
        except Exception as e:
            logger.error(f"Error posting batch banner with buttons: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    except Exception as e:
        logger.error(f"Critical error in post_anime_batch_with_buttons: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
    finally:
        try:
            if banner_path and os.path.exists(banner_path):
                os.remove(banner_path)
        except:
            pass


async def _post_batch_fallback(client, anime_title, quality_files, episode_number=None, audio_type=None):
    try:
        main_channel_username = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        hashtag = get_anime_hashtag(anime_title)
        
        total_episodes = 0
        if quality_files:
            for quality, file_ids in quality_files.items():
                total_episodes = max(total_episodes, len(file_ids) if file_ids else 0)
        
        qualities_str = " | ".join(quality_files.keys()) if quality_files else "N/A"
        audio_str = audio_type if audio_type else "N/A"
        
        english_title = "Unknown"
        romaji_title = "Unknown"
        
        caption = (
            f"<blockquote><b><i>✦ {english_title} | {romaji_title} ✦</i></b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<blockquote><b>➥ Episode: {episode_number if episode_number else 'N/A'}</b>\n"
            f"<b>➥ Quality: {qualities_str}</b>\n"
            f"<b>➥ Audio: {audio_str}</b></blockquote>\n"
            f"<b>━━━━━━━━━━━━━━━━━━━━━</b>\n"
            f"<b><blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{main_channel_username}'>𝗢𝗻𝗴𝗼𝗶𝗻𝗴 - 𝗔𝗿𝗰</a></blockquote></b>"
        )
        
        buttons = []
        if quality_files:
            for quality, file_ids in quality_files.items():
                try:
                    batch_link = await generate_batch_link(file_ids, quality)
                    if batch_link:
                        buttons.append(Button.url(quality, batch_link))
                except Exception as e:
                    logger.error(f"Error generating batch link: {e}")
        
        keyboard = []
        for i in range(0, len(buttons), 2):
            row = buttons[i:i+2]
            keyboard.append(row)
        
        if not keyboard:
            keyboard = None
        
        target = CHANNEL_ID if CHANNEL_ID else CHANNEL_USERNAME
        if target:
            msg = await client.send_message(target, caption, parse_mode='html', buttons=keyboard, link_preview=False)
            mark_banner_posted(anime_title)
            return msg
        return None
        
    except Exception as e:
        logger.error(f"Error in batch fallback posting: {e}")
        return None



async def download_anime_batch(event, anime_session, anime_title):
    logger.info(f"Starting batch download for {anime_title}")
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    try:
        progress = ProgressMessage(client, event.chat_id,
            f"<blockquote><b>✦ 𝗙𝗘𝗧𝗖𝗛𝗜𝗡𝗚 𝗘𝗣𝗜𝗦𝗢𝗗𝗘𝗦 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
            f"・ Sᴛᴀᴛᴜs: ᴘʀᴏᴄᴇssɪɴɢ</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode='html'
        )
        if not await progress.send():
            await safe_respond(event, "<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɪɴɪᴛɪᴀʟɪᴢᴇ ᴘʀᴏɢʀᴇss ᴛʀᴀᴄᴋɪɴɢ</b></blockquote>", parse_mode='html')
            return False
        
        await progress.update(
            f"<blockquote><b>✦ 𝗙𝗘𝗧𝗖𝗛𝗜𝗡𝗚 𝗘𝗣𝗜𝗦𝗢𝗗𝗘𝗦 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
            f"・ Sᴛᴀᴛᴜs: ᴘʀᴏᴄᴇssɪɴɢ</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode='html'
        )
        episodes = await get_all_episodes(anime_session)
        if not episodes:
            logger.error(f"Failed to get episode list for {anime_title}")
            await progress.update("<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ᴇᴘɪsᴏᴅᴇ ʟɪsᴛ</b><blockquote>", parse_mode='html')
            return False
        
        total_episodes = len(episodes)
        logger.info(f"Found {total_episodes} episodes for {anime_title}")
        
        enabled_qualities = quality_settings.enabled_qualities
        sorted_qualities = sorted(enabled_qualities, key=lambda x: int(x[:-1]))
        total_qualities = len(sorted_qualities)
        
        quality_files = {}
        for quality in sorted_qualities:
            quality_files[quality] = []
        
        for quality_idx, quality in enumerate(sorted_qualities):
            quality_progress = quality_idx + 1
            await progress.update(
                f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                f"・ Tᴏᴛᴀʟ ᴇᴘɪsᴏᴅᴇs: {total_episodes}\n"
                f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_progress}/{total_qualities})</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )
            
            for ep_idx, episode in enumerate(episodes):
                episode_number = episode['episode']
                episode_session = episode['session']
                episode_title = episode['title']
                
                await progress.update(
                    f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number} - {episode_title} | ({ep_idx+1}/{total_episodes})\n"
                    f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_progress}/{total_qualities})</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode="html"
                )
                
                download_links = get_download_links(anime_session, episode_session)
                if not download_links:
                    logger.error(f"No download links found for {anime_title} Episode {episode_number}")
                    continue
                
                is_dub = any('eng' in link['text'].lower() for link in download_links)
                audio_type = "Dub" if is_dub else "Sub"

                quality_link = None
                for link in download_links:
                    if quality in link['text']:
                        quality_link = link
                        break
                
                if not quality_link:
                    logger.error(f"Quality {quality} not found for {anime_title} Episode {episode_number}")
                    continue

                base_name = format_filename(anime_title, episode_number, quality, audio_type)
                main_channel_username = CHANNEL_USERNAME if CHANNEL_USERNAME else BOT_USERNAME
                full_caption = f"**{base_name} {main_channel_username}.mkv**"
                filename = sanitize_filename(full_caption)
                download_path = os.path.join(DOWNLOAD_DIR, filename)
                
                kwik_link = extract_kwik_link(quality_link['href'])
                if not kwik_link:
                    logger.error(f"Failed to extract kwik link for {quality}")
                    continue
                
                direct_link = get_dl_link(kwik_link)
                if not direct_link:
                    logger.error(f"Failed to get direct link for {quality}")
                    continue
                
                try:
                    ydl_opts = {
                        'outtmpl': download_path,
                        'quiet': True,
                        'no_warnings': True,
                        'http_headers': YTDLP_HEADERS,
                        'downloader_args': {'chunk_size': 10485760},
                        'nocheckcertificate': True,
                        'compat_opts': ['no-keep-video'],
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([direct_link])
                    
                    if not os.path.exists(download_path) or os.path.getsize(download_path) < 1000:
                        logger.error(f"Downloaded file is too small or doesn't exist for {quality}")
                        continue

                    if FFMPEG_AVAILABLE:
                        final_path = os.path.join(DOWNLOAD_DIR, f"[E{episode_number:02d}] {anime_title} [{quality}].mkv")
                        if await rename_video_with_ffmpeg(download_path, final_path):
                            os.remove(download_path)
                            download_path = final_path
                    
                    caption = full_caption
                    
                    try:
                        thumb = await get_fixed_thumbnail()
                        
                        upload_progress = UploadProgressBar(client, event.chat_id, full_caption)
                        
                        dump_msg_id = None
                        if DUMP_CHANNEL_ID:
                            try:
                                msg = await client.send_file(
                                    DUMP_CHANNEL_ID,
                                    download_path,
                                    caption=caption,
                                    thumb=thumb,
                                    force_document=True,
                                    attributes=None,
                                    supports_streaming=False,
                                    progress_callback=upload_progress.update,
                                    part_size_kb=512,
                                    link_preview=False
                                )

                                await upload_progress.finish()
                                
                                dump_msg_id = msg.id
                                logger.info(f"Sent to dump channel {DUMP_CHANNEL_ID}")
                            except Exception as e:
                                logger.error(f"Failed to send to dump channel: {e}")
                        elif DUMP_CHANNEL_USERNAME:
                            try:
                                msg = await client.send_file(
                                    DUMP_CHANNEL_USERNAME,
                                    download_path,
                                    caption=caption,
                                    thumb=thumb,
                                    force_document=True,
                                    attributes=None,
                                    supports_streaming=False,
                                    progress_callback=upload_progress.update,
                                    part_size_kb=512,
                                    link_preview=False
                                )
                                
                                await upload_progress.finish()
                                
                                dump_msg_id = msg.id
                                logger.info(f"Sent to dump channel {DUMP_CHANNEL_USERNAME}")
                            except Exception as e:
                                logger.error(f"Failed to send to dump channel: {e}")
                        else:
                            logger.warning("No dump channel configured. File not uploaded.")
                        
                        if dump_msg_id:
                            quality_files[quality].append(dump_msg_id)
                        
                        logger.info(f"Successfully uploaded {anime_title} Episode {episode_number} {quality}")
                        
                    except FloodWaitError as e:
                        logger.error(f"Flood wait error: {e.seconds} seconds")
                        await asyncio.sleep(e.seconds + 5)
                    except Exception as e:
                        logger.error(f"Error sending video: {e}")
                    
                    try:
                        os.remove(download_path)
                    except:
                        pass
                
                except Exception as e:
                    logger.error(f"Error processing {quality} for episode {episode_number}: {e}")
        
        for episode in episodes:
            episode_number = episode['episode']
            mark_episode_processed(anime_title, episode_number, sorted_qualities)
        
        if quality_files and any(quality_files.values()):
            anime_info = await get_anime_info(anime_title)
            if anime_info:
                await post_anime_batch_with_buttons(client, anime_title, anime_info, quality_files)
        
        await progress.update(
            f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
            f"・ Sᴛᴀᴛᴜs: ᴄᴏᴍᴘʟᴇᴛᴇᴅ</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode='html'
        )
        return True
    
    except Exception as e:
        logger.error(f"Error in batch download for {anime_title}: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ ɪɴ ʙᴀᴛᴄʜ ᴅᴏᴡɴʟᴏᴀᴅ:</b> {str(e)}</blockquote>", parse_mode='html')
        return False



async def download_episode(event, anime_title, anime_session, episode_number, episode_session, quality_link):
    user_id = event.chat_id
    
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    
    
    progress = ProgressMessage(client, user_id, f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n──────────────────\n<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n・ Eᴘɪsᴏᴅᴇ: {episode_number}</blockquote>\n──────────────────\n<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>")
    if not await progress.send():
        await safe_respond(event, "<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ɪɴɪᴛɪᴀʟɪᴢᴇ ᴘʀᴏɢʀᴇss ᴛʀᴀᴄᴋɪɴɢ</b></blockquote>", parse_mode='html')
        return
    
    resolution_match = re.search(r"\b(\d{3,4}p)\b", quality_link['text'])
    if not resolution_match:
        await progress.update("<blockquote><b>ᴄᴏᴜʟᴅ ɴᴏᴛ ᴅᴇᴛᴇʀᴍɪɴᴇ ʀᴇsᴏʟᴜᴛɪᴏɴ ғᴏʀ ᴛʜᴇ sᴇʟᴇᴄᴛᴇᴅ ǫᴜᴀʟɪᴛʏ.</b></blockquote>", parse_mode='html')
        return
    
    resolution = resolution_match.group(1)
    is_dub = 'eng' in quality_link['text'].lower()
    type_str = "Dub" if is_dub else "Sub"
    
    base_name = format_filename(anime_title, episode_number, resolution, type_str)
    main_channel_username = CHANNEL_USERNAME if CHANNEL_USERNAME else BOT_USERNAME
    full_caption = f"**{base_name} {main_channel_username}.mkv**"
    filename = sanitize_filename(full_caption)
    download_path = os.path.join(DOWNLOAD_DIR, filename)
    
    await progress.update(f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n──────────────────\n<blockquote>・ Aɴɪᴍᴇ:{filename}\n・ sᴛᴀᴛᴜs: ᴘʀᴏᴄᴇssɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ...</blockquote>\n──────────────────\n<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>", parse_mode='html')
    
    kwik_link = extract_kwik_link(quality_link['href'])
    if not kwik_link:
        await progress.update(f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴇxᴛʀᴀᴄᴛ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ.</b></blockquote>", parse_mode='html')
        return
    
    try:
        direct_link = get_dl_link(kwik_link)
        if not direct_link:
            await progress.update(f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ᴅɪʀᴇᴄᴛ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ.</b></blockquote>", parse_mode='html')
            return
    except Exception as e:
        await progress.update(f"<blockquote><b>ᴇʀʀᴏʀ ɢᴇɴᴇʀᴀᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋ:</b> {str(e)}<blockquote>", parse_mode='html')
        return
    
    await progress.update(f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n──────────────────\n<blockquote>・ sᴛᴀᴛᴜs: sᴛᴀʀᴛɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ...</blockquote>\n──────────────────\n<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>", parse_mode='html')
    
    try:
        last_update = time.time()
        download_start = time.time()
        
        def progress_hook(d):
            nonlocal last_update
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update >= 5:
                    downloaded_bytes = d.get('downloaded_bytes')
                    total_bytes = d.get('total_bytes')
                    speed = d.get('speed')
                    
                    downloaded = downloaded_bytes if downloaded_bytes is not None else 0
                    total = total_bytes if total_bytes is not None else 1
                    speed_val = speed if speed is not None else 0
                    
                    try:
                        downloaded = int(downloaded)
                        total = int(total)
                        speed_val = float(speed_val)
                    except (ValueError, TypeError):
                        downloaded = 0
                        total = 1
                        speed_val = 0.0
                    
                    if total > 0:
                        percent = min(100, (downloaded / total) * 100)
                    else:
                        percent = 0
                    
                    progress_text = (
                        f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {filename}\n"
                        f"・ Pʀᴏɢʀᴇss: {percent:.1f}%\n"
                        f"・ Sɪᴢᴇ: {format_size(downloaded)}/{format_size(total)}\n"
                        f"・ Sᴘᴇᴇᴅ: {format_speed(speed_val)}</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>"
                    )
                    
                    try:
                        asyncio.create_task(progress.update(progress_text, parse_mode="html"))
                    except:
                        pass
                    
                    last_update = current_time
        
        ydl_opts = {
            'outtmpl': download_path,
            'quiet': True,
            'no_warnings': True,
            'http_headers': YTDLP_HEADERS,
            'downloader_args': {'chunk_size': 10485760},
            'progress_hooks': [progress_hook],
            'nocheckcertificate': True,
            'compat_opts': ['no-keep-video'],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([direct_link])
        
        if not os.path.exists(download_path) or os.path.getsize(download_path) < 1000:
            raise Exception("Downloaded file is too small or doesn't exist")
        
        download_time = time.time() - download_start
        file_size = os.path.getsize(download_path)
        avg_speed = file_size / download_time if download_time > 0 else 0
        
        await progress.update(
            f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Tɪᴍᴇ: {download_time:.1f}s\n"
            f"・ Sɪᴢᴇ: {format_size(file_size)}\n"
            f"・ Aᴠɢ Sᴘᴇᴇᴅ: {format_speed(avg_speed)}\n"
            f"・ Sᴛᴀᴛᴜs: ᴘʀᴇᴘᴀʀɪɴɢ ᴜᴘʟᴏᴀᴅ...</blockquote>"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode="html"
        )
    except Exception as e:
        logger.error(f"yt-dlp failed: {str(e)}")
        
        try:
            session = requests.Session()
            session.headers.update(YTDLP_HEADERS)
            response = session.get(direct_link, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update = start_time
            last_downloaded = 0
            
            with open(download_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        current_time = time.time()
                        if current_time - last_update >= 5:
                            time_diff = current_time - last_update
                            bytes_diff = downloaded - last_downloaded
                            speed = bytes_diff / time_diff if time_diff > 0 else 0
                            
                            if total_size > 0:
                                percent = min(100, (downloaded / total_size) * 100)
                                progress_text = (
                                    f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>・ Aɴɪᴍᴇ: {filename}\n"
                                    f"・ Pʀᴏɢʀᴇss: {percent:.1f}%\n"
                                    f"・ Sɪᴢᴇ: {format_size(downloaded)}\n"
                                    f"・ Sᴘᴇᴇᴅ:  {format_speed(speed)}</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                )
                            else:
                                progress_text = (
                                    f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>・ Aɴɪᴍᴇ: {filename}\n"
                                    f"・ Sɪᴢᴇ: {format_size(downloaded)}\n"
                                    f"・ Sᴘᴇᴇᴅ:  {format_speed(speed)}</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                )
                            
                            try:
                                await progress.update(progress_text, parse_mode="html")
                            except:
                                pass
                            
                            last_update = current_time
                            last_downloaded = downloaded
            
            if os.path.getsize(download_path) < 1000:
                raise Exception("Downloaded file is too small")
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            await progress.update(
                f"<blockquote><b>ᴅᴏᴡɴʟᴏᴀᴅ ғᴀɪʟᴇᴅ:</b> {str(e)}</blockquote>", parse_mode="html"
            )
            return
    
    await progress.update(
        f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 ✦</blockquote>\n"
        f"──────────────────\n"
        f"</blockquote>・ Sᴛᴀᴛᴜs: sᴛᴀʀᴛɪɴɢ ᴜᴘʟᴏᴀᴅ...</blockquote>\n"
        f"──────────────────\n"
        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
        parse_mode="html"
    )
    
    upload_progress = UploadProgressBar(client, user_id, full_caption)
    
    try:
        file_size = os.path.getsize(download_path)
        caption = full_caption
        
        try:
            thumb = await get_fixed_thumbnail()
            
            dump_msg_id = None
            if DUMP_CHANNEL_ID:
                try:
                    msg = await client.send_file(
                        DUMP_CHANNEL_ID,
                        download_path,
                        caption=caption,
                        thumb=thumb,
                        force_document=True,
                        attributes=None,
                        supports_streaming=False,
                        progress_callback=upload_progress.update,
                        part_size_kb=512,
                        link_preview=False
                    )
                    
                    await upload_progress.finish()
                    
                    dump_msg_id = msg.id
                    channel_msg = f"\n<b>Also posted to dump channel</b>"
                except Exception as e:
                    logger.error(f"Failed to send to dump channel: {e}")
                    channel_msg = f"\n<b>Failed to post to dump channel:</b> <i>{str(e)}</i>"
            elif DUMP_CHANNEL_USERNAME:
                try:
                    msg = await client.send_file(
                        DUMP_CHANNEL_USERNAME,
                        download_path,
                        caption=caption,
                        thumb=thumb,
                        force_document=True,
                        attributes=None,
                        supports_streaming=False,
                        progress_callback=upload_progress.update,
                        part_size_kb=512,
                        link_preview=False
                    )
                    
                    await upload_progress.finish()
                    
                    dump_msg_id = msg.id
                    channel_msg = f"\n<b>Also posted to dump channel</b>"
                except Exception as e:
                    logger.error(f"Failed to send to dump channel: {e}")
                    channel_msg = f"\n<b>Failed to post to dump channel:</b> <i>{str(e)}</i>"
            else:
                channel_msg = ""
            
            await progress.update(f"<b>Successfully sent your video!</b>{channel_msg}")
        except FloodWaitError as e:
            logger.error(f"Flood wait during initial upload: {e.seconds} seconds")
            
            await asyncio.sleep(e.seconds + 5)
            

            if DUMP_CHANNEL_ID:
                try:
                    msg = await client.send_file(
                        DUMP_CHANNEL_ID,
                        download_path,
                        caption=caption,
                        thumb=thumb,
                        force_document=True,
                        attributes=None,
                        supports_streaming=False,
                        part_size_kb=512
                    )
                    
                    dump_msg_id = msg.id
                    channel_msg = f"\n<b>Also posted to dump channel</b>"
                except Exception as e:
                    logger.error(f"Failed to send to dump channel: {e}")
                    channel_msg = f"\n<b>Failed to post to dump channel:</b> <i>{str(e)}</i>"
            elif DUMP_CHANNEL_USERNAME:
                try:
                    msg = await client.send_file(
                        DUMP_CHANNEL_USERNAME,
                        download_path,
                        caption=caption,
                        thumb=thumb,
                        force_document=True,
                        attributes=None,
                        supports_streaming=False,
                        part_size_kb=512
                    )
                    
                    dump_msg_id = msg.id
                    channel_msg = f"\n<b>Also posted to dump channel</b>"
                except Exception as e:
                    logger.error(f"Failed to send to dump channel: {e}")
                    channel_msg = f"\n<b>ғᴀɪʟᴇᴅ ᴛᴏ ᴘᴏsᴛ ᴛᴏ ᴅᴜᴍᴘ ᴄʜᴀɴɴᴇʟ:</b> {str(e)}"
            else:
                channel_msg = ""
            
            await safe_send_message(client, user_id, f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ sᴇɴᴛ ʏᴏᴜʀ ᴠɪᴅᴇᴏ ᴀғᴛᴇʀ ʀᴇᴛʀʏ!</b>{channel_msg}</blockquote>", parse_mode='html')
        except Exception as e:
            logger.error(f"Error sending video: {str(e)}")
            try:
                await safe_send_message(client, user_id, f"<blockquote><b>ᴇʀʀᴏʀ sᴇɴᴅɪɴɢ ᴠɪᴅᴇᴏ:</b> {str(e)}</blockquote>", parse_mode='html')
            except FloodWaitError:
                logger.error("Flood wait when sending error message")
    except Exception as e:
        logger.error(f"Error in upload process: {str(e)}")
        try:
            await safe_send_message(client, user_id, f"<blockquote><b>ᴇʀʀᴏʀ ɪɴ ᴜᴘʟᴏᴀᴅ ᴘʀᴏᴄᴇss:</b> {str(e)}</blockquote>", parse_mode='html')
        except FloodWaitError:
            logger.error("Flood wait when sending error message")
    
    try:
        os.remove(download_path)
    except:
        pass
