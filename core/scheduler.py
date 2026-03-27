from __future__ import annotations
import os
import time
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import schedule
from zoneinfo import ZoneInfo

from core.config import (
    DOWNLOAD_DIR, YTDLP_HEADERS, ADMIN_CHAT_ID,
    CHANNEL_USERNAME, BOT_USERNAME, CHANNEL_NAME,
    DUMP_CHANNEL_ID, DUMP_CHANNEL_USERNAME
)
from core.client import client, FFMPEG_AVAILABLE, currently_processing
from core.state import (
    auto_download_state, quality_settings, anime_queue,
    episode_tracker, EpisodeState
)
from core.utils import (
    sanitize_filename, format_filename, format_size, format_speed,
    get_fixed_thumbnail, is_episode_processed, update_processed_qualities, mark_episode_processed,
    ProgressMessage, UploadProgressBar, safe_edit
)
from core.anime_api import (
    search_anime, get_all_episodes, get_latest_releases,
    get_download_links, extract_kwik_link, get_dl_link, get_anime_info,
    find_closest_episode, find_best_link_for_quality, get_available_qualities_with_mapping
)
from core.download import (
    rename_video_with_ffmpeg, post_anime_with_buttons, robust_upload_file
)

logger = logging.getLogger(__name__)

try:
    import yt_dlp
except ImportError:
    logger.error("yt-dlp not installed")

from telethon.errors import FloodWaitError


_currently_processing = False
_scheduler_lock = asyncio.Lock() if asyncio else None


def get_currently_processing():
    global _currently_processing
    return _currently_processing


def set_currently_processing(value: bool):
    global _currently_processing
    _currently_processing = value


def _get_scheduler_lock():
    global _scheduler_lock
    if _scheduler_lock is None:
        try:
            _scheduler_lock = asyncio.Lock()
        except RuntimeError:
            pass
    return _scheduler_lock


async def auto_download_latest_episode():
    global _currently_processing
    
    logger.info("Starting auto download process...")
    
    if _currently_processing:
        logger.info("Already processing an episode. Skipping auto check.")
        return False
    
    _currently_processing = True
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    progress = None
    if ADMIN_CHAT_ID:
        progress = ProgressMessage(client, ADMIN_CHAT_ID, "<b>Auto processing started...</b>")
        await progress.send()
    
    try:
        if auto_download_state.last_checked:
            last_check = datetime.fromisoformat(auto_download_state.last_checked)
            time_since_last_check = (datetime.now() - last_check).total_seconds()
            
            cooldown_period = auto_download_state.interval / 2
            if time_since_last_check < cooldown_period:
                logger.info(f"Skipping auto check, last check was {time_since_last_check:.1f} seconds ago")
                return False
        
        if progress:
            await progress.update("<b><blockquote>ᴄʜᴇᴄᴋɪɴɢ ғᴏʀ ɴᴇᴡ ᴇᴘɪsᴏᴅᴇs...</blockquote></b>", parse_mode='html')
        
        latest_data = get_latest_releases(page=1)
        if not latest_data or 'data' not in latest_data:
            logger.error("Failed to get latest releases")
            if progress:
                await progress.update("<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ʟᴀᴛᴇsᴛ ʀᴇʟᴇᴀsᴇ</blockquote></b>", parse_mode='html')
            return False
        
        latest_anime = latest_data['data'][0]
        anime_title = latest_anime.get('anime_title', 'Unknown Anime')
        episode_number = latest_anime.get('episode', 0)
        
        logger.info(f"Latest airing anime: {anime_title} Episode {episode_number}")
        
        if progress:
            await progress.update(
                f"<b><blockquote>✦ 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title} \n"
                f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"・ Sᴛᴀᴛᴜs: Cʜᴇᴄᴋɪɴɢ</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )

        if is_episode_processed(anime_title, episode_number):
            logger.info(f"Episode {episode_number} of {anime_title} already processed. Skipping.")
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗘𝗗 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title} \n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Sᴛᴀᴛᴜs: Pʀᴏᴄᴇssᴇᴅ</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            return True
        
        search_results = await search_anime(anime_title)
        if not search_results:
            logger.error(f"Anime not found: {anime_title}")
            if progress:
                await progress.update(f"<b><blockquote>ᴀɴɪᴍᴇ ɴᴏᴛ ғᴏᴜɴᴅ: {anime_title}</b></blockquote>", parse_mode='html')
            return False
        
        anime_info = search_results[0]
        anime_session = anime_info['session']
        
        episodes = await get_all_episodes(anime_session)
        if not episodes:
            logger.error(f"Failed to get episode list for {anime_title}")
            if progress:
                await progress.update(f"<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ᴇᴘɪsᴏᴅᴇ ʟɪsᴛ ғᴏʀ: {anime_title}</b></blockquote>", parse_mode='html')
            return False
        
        target_episode = None
        for ep in episodes:
            try:
                if int(ep['episode']) == episode_number:
                    target_episode = ep
                    break
            except (ValueError, TypeError):
                continue
        
        if not target_episode:
            logger.warning(f"Episode {episode_number} not found for {anime_title}. Looking for closest available.")
            target_episode = find_closest_episode(episodes, episode_number)
            if target_episode:
                actual_episode = int(target_episode['episode'])
                logger.info(f"Found closest episode: {actual_episode}")
                episode_number = actual_episode
            else:
                logger.error(f"No episodes found for {anime_title}")
                if progress:
                    await progress.update(f"<b><blockquote>ɴᴏ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ ғᴏʀ: {anime_title}<b><blockquote>", parse_mode='html')
                return False
        
        episode_session = target_episode['session']
        
        download_links = get_download_links(anime_session, episode_session)
        if not download_links:
            logger.error(f"No download links found for {anime_title} Episode {episode_number}")
            if progress:
                await progress.update(f"<b><blockquote>ɴᴏ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋs ғᴏᴜɴᴅ ғᴏʀ: ᴀɴɪᴍᴇ: {anime_title} | ᴇᴘɪsᴏᴅᴇ: {episode_number}<b><blockquote>", parse_mode='htmls')
            return False
        
        enabled_qualities = quality_settings.enabled_qualities

        if progress:
            await progress.update(f"<b><blockquote>ᴄʜᴇᴄᴋɪɴɢ ǫᴜᴀʟɪᴛʏ ᴀᴠᴀɪʟᴀʙɪʟɪᴛʏ ғᴏʀ: ᴀɴɪᴍᴇ: {anime_title} | ᴇᴘɪsᴏᴅᴇ: {episode_number}<b><blockquote>", parse_mode='html')
        
        quality_mapping = get_available_qualities_with_mapping(download_links, enabled_qualities)
        
        available_qualities = [q for q, link in quality_mapping.items() if link is not None]
        missing_qualities = [q for q, link in quality_mapping.items() if link is None]
        
        logger.info(f"Quality mapping result - Available: {available_qualities}, Missing: {missing_qualities}")
        logger.info(f"Download links available: {[link['text'] for link in download_links]}")
        
        is_dub = any('eng' in link['text'].lower() for link in download_links)
        audio_type = "Dub" if is_dub else "Sub"
        
        if missing_qualities:
            logger.warning(
                f"SKIPPING {anime_title} Ep{episode_number}: not all selected qualities available yet. "
                f"Available: {available_qualities}, Missing: {missing_qualities}"
            )
            logger.info(f"Source links: {[link['text'] for link in download_links]}")
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗪𝗔𝗜𝗧𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Aᴠᴀɪʟᴀʙʟᴇ: {', '.join(available_qualities) if available_qualities else 'None'}\n"
                    f"・ Mɪssɪɴɢ: {', '.join(missing_qualities)}\n"
                    f"・ Sᴛᴀᴛᴜs: Wᴀɪᴛɪɴɢ ғᴏʀ ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇs</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            
            return False
        
        if not available_qualities:
            logger.warning(f"No qualities available (even with adaptive mapping) for {anime_title} Episode {episode_number}")
            
            queue_info = {
                'title': anime_title,
                'episode': episode_number,
                'session': anime_session,
                'episode_session': episode_session,
                'available_qualities': [],
                'missing_qualities': enabled_qualities,
                'audio_type': audio_type
            }
            
            anime_queue.add_to_pending(queue_info)
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗤𝗨𝗘𝗨𝗘 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Aᴠᴀɪʟᴀʙʟᴇ:  {', '.join(available_qualities)}\n"
                    f"・ Mɪssɪɴɢ: {', '.join(missing_qualities)}\n"
                    f"・ Qᴜᴇᴜᴇ sɪᴢᴇ: {len(anime_queue.pending_queue)}\n"
                    f"・ Sᴛᴀᴛᴜs: Wᴀɪᴛɪɴɢ</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            
            return await check_and_process_next_episode(progress)
        
        logger.info(f"All qualities available for {anime_title} Episode {episode_number}: {available_qualities}")
        
        if progress:
            await progress.update(
                f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"・ Aᴠᴀɪʟᴀʙʟᴇ:  {', '.join(available_qualities)}\n"
                f"・ Sᴛᴀᴛᴜs: Dᴏᴡɴʟᴏᴀᴅɪɴɢ</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )
        
        sorted_qualities = sorted(available_qualities, key=lambda x: int(x[:-1]))
        
        downloaded_qualities = []
        quality_files = {}
        
        for quality_idx, quality in enumerate(sorted_qualities):
            try:
                logger.info(f"Downloading {anime_title} Episode {episode_number} {quality}")
                
                if progress:
                    await progress.update(
                        f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                        f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                        f"・ Aᴠᴀɪʟᴀʙʟᴇ:  {', '.join(available_qualities)}\n"
                        f"・ Qᴜᴀʟɪᴛʏ: {quality} - ({quality_idx + 1}/{len(sorted_qualities)})\n"
                        f"・ Aᴜᴅɪᴏ:  {audio_type}\n"
                        f"・ Sᴛᴀᴛᴜs: Fɪɴᴅɪɴɢ ʟɪɴᴋs</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                        parse_mode='html'
                    )
                
                quality_link = quality_mapping.get(quality)
                
                if not quality_link:
                    logger.warning(f"Quality {quality} not available for {anime_title} Episode {episode_number}, skipping")
                    continue
                
                base_name = format_filename(anime_title, episode_number, quality, "Sub" if not is_dub else "Dub")
                main_channel_username = CHANNEL_USERNAME if CHANNEL_USERNAME else BOT_USERNAME
                full_caption = f"**{base_name} {main_channel_username}.mkv**"
                filename = sanitize_filename(full_caption)
                download_path = os.path.join(DOWNLOAD_DIR, filename)

                if progress:
                    await progress.update(
                        f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                        f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                        f"・ Aᴠᴀɪʟᴀʙʟᴇ:  {', '.join(available_qualities)}\n"
                        f"・ Qᴜᴀʟɪᴛʏ: {quality} - ({quality_idx + 1}/{len(sorted_qualities)})\n"
                        f"・ Aᴜᴅɪᴏ:  {audio_type}\n"
                        f"・ Sᴛᴀᴛᴜs: Exᴛʀᴀᴄᴛɪɴɢ ᴅɪʀᴇᴄᴛ ʟɪɴᴋs...</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                        parse_mode='html'
                    )
                
                kwik_link = extract_kwik_link(quality_link['href'])
                if not kwik_link:
                    logger.error(f"Failed to extract kwik link for {quality}")
                    continue
                
                direct_link = get_dl_link(kwik_link)
                if not direct_link:
                    logger.error(f"Failed to get direct link for {quality}")
                    continue
                
                if progress:
                    await progress.update(
                        f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                        f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                        f"・ Aᴠᴀɪʟᴀʙʟᴇ:  {', '.join(available_qualities)}\n"
                        f"・ Qᴜᴀʟɪᴛʏ: {quality} - ({quality_idx + 1}/{len(sorted_qualities)})\n"
                        f"・ Aᴜᴅɪᴏ:  {audio_type}\n"
                        f"・ Sᴛᴀᴛᴜs: Oᴘᴛɪᴍɪᴢᴇᴅ ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ...</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                        parse_mode='html'
                    )
                
                last_update = time.time()
                download_start = time.time()
                
                def progress_hook(d):
                    nonlocal last_update
                    if d['status'] == 'downloading':
                        current_time = time.time()
                        if current_time - last_update >= 3:
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
                            
                            if progress:
                                progress_text = (
                                    f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                                    f"・ Aᴠᴀɪʟᴀʙʟᴇ:  {', '.join(available_qualities)}\n"
                                    f"・ Qᴜᴀʟɪᴛʏ: {quality} - ({quality_idx + 1}/{len(sorted_qualities)})\n"
                                    f"・ Aᴜᴅɪᴏ:  {audio_type}\n"
                                    f"・ Sᴛᴀᴛᴜs: Dᴏᴡɴʟᴏᴀᴅɪɴɢ...</blockquote>\n"
                                    f"<blockquote>・ Pʀᴏɢʀᴇss: {percent:.1f}%\n"
                                    f"・ Sɪᴢᴇ: {format_size(downloaded)}/{format_size(total)}\n"
                                    f"・ Sᴘᴇᴇᴅ: {format_speed(speed_val)}%</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                )
                                
                                try:
                                    asyncio.create_task(progress.update(progress_text, parse_mode='html'))
                                except:
                                    pass
                            
                            last_update = current_time
                
                ydl_opts_optimized = {
                    'outtmpl': download_path,
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': YTDLP_HEADERS,
                    'progress_hooks': [progress_hook],
                    'nocheckcertificate': True,
                    'compat_opts': ['no-keep-video'],
                    'concurrent_fragment_downloads': 16,
                    'fragment_retries': 10,
                    'retries': 10,
                    'downloader_args': {
                        'chunk_size': 16777216,
                        'connections': 16,
                        'continue_dl': True
                    },
                    'socket_timeout': 30,
                    'buffersize': 16384,
                }
                
                download_success = False
                try:
                    ydl_opts_aria = {
                        'outtmpl': download_path,
                        'quiet': True,
                        'no_warnings': True,
                        'http_headers': YTDLP_HEADERS,
                        'progress_hooks': [progress_hook],
                        'nocheckcertificate': True,
                        'compat_opts': ['no-keep-video'],
                        'external_downloader': 'aria2c',
                        'external_downloader_args': {
                            'aria2c': [
                                '--max-connection-per-server=16',
                                '--max-concurrent-downloads=8', 
                                '--split=8',
                                '--min-split-size=1M',
                                '--max-download-limit=0',
                                '--file-allocation=none',
                                '--continue=true',
                                '--auto-file-renaming=false',
                                '--allow-overwrite=true',
                                '--max-tries=5',
                                '--retry-wait=3',
                                '--timeout=60',
                                '--connect-timeout=30'
                            ]
                        }
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts_aria) as ydl:
                        ydl.download([direct_link])
                    download_success = True
                    logger.info(f"Downloaded {quality} using aria2c successfully")
                    
                except Exception as aria_error:
                    logger.warning(f"Aria2c not available or failed: {aria_error}")
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts_optimized) as ydl:
                            ydl.download([direct_link])
                        download_success = True
                        logger.info(f"Downloaded {quality} using optimized yt-dlp")
                    except Exception as fallback_error:
                        logger.warning(f"Optimized download failed: {fallback_error}")
                        ydl_opts_basic = {
                            'outtmpl': download_path,
                            'quiet': True,
                            'no_warnings': True,
                            'http_headers': YTDLP_HEADERS,
                            'progress_hooks': [progress_hook],
                            'nocheckcertificate': True,
                            'compat_opts': ['no-keep-video'],
                            'downloader_args': {'chunk_size': 10485760},
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts_basic) as ydl:
                            ydl.download([direct_link])
                        download_success = True
                
                if not os.path.exists(download_path) or os.path.getsize(download_path) < 1000:
                    logger.error(f"Downloaded file is too small or doesn't exist for {quality}")
                    continue
                
                if FFMPEG_AVAILABLE:
                    final_path = os.path.join(DOWNLOAD_DIR, f"[E{episode_number:02d}] - {anime_title} [{quality}].mkv")
                    if await rename_video_with_ffmpeg(download_path, final_path):
                        os.remove(download_path)
                        download_path = final_path
                
                caption = full_caption
                
                thumb = await get_fixed_thumbnail()
                
                dump_msg_id = await robust_upload_file(
                    file_path=download_path,
                    caption=caption,
                    thumb_path=thumb,
                    max_retries=3
                )
                
                if dump_msg_id:
                    if quality not in quality_files:
                        quality_files[quality] = []
                    quality_files[quality].append(dump_msg_id)
                    
                    update_processed_qualities(anime_title, episode_number, quality)
                    downloaded_qualities.append(quality)
                    logger.info(f"Successfully uploaded {quality} version: msg_id={dump_msg_id}")
                    
                    try:
                        os.remove(download_path)
                    except:
                        pass
                else:
                    logger.error(f"Upload FAILED for {quality} - keeping file for retry")
                
            except Exception as e:
                logger.error(f"Error processing {quality}: {e}")
        
        failed_qualities = [q for q in sorted_qualities if q not in downloaded_qualities]
        
        if failed_qualities:
            logger.error(
                f"EPISODE MARKED FAILED: {anime_title} Ep{episode_number} - "
                f"{len(failed_qualities)} qualities failed: {failed_qualities}. "
                f"Successful: {downloaded_qualities}. No post created. No re-download."
            )
            
            for q in failed_qualities:
                try:
                    base_name = format_filename(anime_title, episode_number, q, audio_type)
                    main_channel_username = CHANNEL_USERNAME if CHANNEL_USERNAME else BOT_USERNAME
                    potential_filename = sanitize_filename(f"**{base_name} {main_channel_username}.mkv**")
                    potential_path = os.path.join(DOWNLOAD_DIR, potential_filename)
                    if os.path.exists(potential_path):
                        os.remove(potential_path)
                        logger.info(f"Cleaned up failed file: {potential_path}")
                except Exception as cleanup_err:
                    logger.warning(f"Cleanup error for {q}: {cleanup_err}")
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗙𝗔𝗜𝗟𝗘𝗗 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Sᴜᴄᴄᴇss: {', '.join(downloaded_qualities) if downloaded_qualities else 'None'}\n"
                    f"・ Fᴀɪʟᴇᴅ: {', '.join(failed_qualities)}\n"
                    f"・ Sᴛᴀᴛᴜs: Fᴀɪʟᴇᴅ ᴀғᴛᴇʀ 3 ʀᴇᴛʀɪᴇs - sᴋɪᴘᴘᴇᴅ</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            return False
        
        if quality_files and len(downloaded_qualities) == len(sorted_qualities):
            anime_info = await get_anime_info(anime_title)
            await post_anime_with_buttons(client, anime_title, anime_info, episode_number, audio_type, quality_files)
            
            logger.info(f"All {len(downloaded_qualities)} qualities processed for {anime_title} Episode {episode_number}")
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Qᴜᴀʟɪᴛɪᴇs: {', '.join(downloaded_qualities)}\n"
                    f"・ Sᴛᴀᴛᴜs: Pᴏsᴛᴇᴅ ✓</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            return True
        else:
            logger.error(f"Unexpected state: quality_files={bool(quality_files)}, downloaded={len(downloaded_qualities)}, expected={len(sorted_qualities)}")
            return False
    
    except Exception as e:
        logger.error(f"Error in auto download process: {e}")
        if progress:
            await progress.update(
                f"<b>Error in auto download process:</b> <i>{str(e)}</i>",
                parse_mode='html'
            )
        return False
    finally:
        _currently_processing = False


async def check_and_process_next_episode(progress=None):
    try:
        logger.info("Checking for other new episodes to process...")
        channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        
        latest_data = get_latest_releases(page=1)
        if not latest_data or 'data' not in latest_data:
            return False
        
        for idx, anime_data in enumerate(latest_data['data']):
            if idx >= 5:
                break
                
            anime_title = anime_data.get('anime_title', 'Unknown Anime')
            episode_number = anime_data.get('episode', 0)
            
            if anime_queue.is_processed(anime_title, episode_number):
                continue
            
            episode_id = f"{anime_title}_{episode_number}"
            if episode_id in [item['id'] for item in anime_queue.pending_queue]:
                continue
            
            logger.info(f"Found unprocessed episode: {anime_title} Episode {episode_number}")
            
            if progress:
                await progress.update(
                f"<b><blockquote>✦ 𝗘𝗣𝗜𝗦𝗢𝗗𝗘 𝗖𝗛𝗘𝗖𝗞𝗜𝗡𝗚 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title} \n"
                f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"・ Sᴛᴀᴛᴜs: Cʜᴇᴄᴋɪɴɢ</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )
            
            success = await process_single_episode(anime_title, episode_number, progress)
            if success:
                return True
        
        return await process_pending_queue(progress)
        
    except Exception as e:
        logger.error(f"Error checking next episode: {e}")
        return False


async def process_pending_queue(progress=None):
    try:
        channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        pending_item = anime_queue.get_next_pending()
        if not pending_item:
            logger.info("No items in pending queue")
            return False
        
        logger.info(f"Processing from queue: {pending_item['id']}")
        
        if progress:
            await progress.update(
                f"<b><blockquote>✦ 𝗤𝗨𝗘𝗨𝗘 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {pending_item['title']}\n"
                f"・ Eᴘɪsᴏᴅᴇ: {pending_item['episode']}\n"
                f"・ Qᴜᴇᴜᴇ sɪᴢᴇ: {len(anime_queue.pending_queue)}\n"
                f"・ Sᴛᴀᴛᴜs: Pʀᴏᴄᴇssɪɴɢ</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )
        
        success = await process_single_episode(
            pending_item['title'],
            pending_item['episode'],
            progress,
            from_queue=True
        )
        
        if success:
            anime_queue.remove_from_pending(pending_item['id'])
            logger.info(f"Successfully processed from queue: {pending_item['id']}")
        else:
            pending_item['last_checked'] = datetime.now().isoformat()
            anime_queue.save_queue()
        
        return success
        
    except Exception as e:
        logger.error(f"Error processing pending queue: {e}")
        return False


async def process_single_episode(anime_title, episode_number, progress=None, from_queue=False):
    global _currently_processing
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    try:
        if _currently_processing:
            logger.info("Already processing an episode. Adding to queue.")
            return False
        
        _currently_processing = True

        search_results = await search_anime(anime_title)
        if not search_results:
            logger.error(f"Anime not found: {anime_title}")
            return False
        
        anime_info = search_results[0]
        anime_session = anime_info['session']
        
        episodes = await get_all_episodes(anime_session)
        if not episodes:
            logger.error(f"Failed to get episode list for {anime_title}")
            return False
        
        target_episode = None
        for ep in episodes:
            try:
                if int(ep['episode']) == episode_number:
                    target_episode = ep
                    break
            except (ValueError, TypeError):
                continue
        
        if not target_episode:
            logger.error(f"Episode {episode_number} not found for {anime_title}")
            return False
        
        episode_session = target_episode['session']

        download_links = get_download_links(anime_session, episode_session)
        if not download_links:
            logger.error(f"No download links found for {anime_title} Episode {episode_number}")
            return False
        
        enabled_qualities = quality_settings.enabled_qualities
        
        quality_mapping = get_available_qualities_with_mapping(download_links, enabled_qualities)
        available_qualities = [q for q, link in quality_mapping.items() if link is not None]
        missing_qualities = [q for q, link in quality_mapping.items() if link is None]
        
        if missing_qualities:
            logger.warning(
                f"SKIPPING {anime_title} Ep{episode_number} in process_single_episode: "
                f"not all selected qualities available. Available: {available_qualities}, Missing: {missing_qualities}"
            )
            
            if not from_queue:
                queue_info = {
                    'title': anime_title,
                    'episode': episode_number,
                    'session': anime_session,
                    'episode_session': episode_session,
                    'available_qualities': available_qualities,
                    'missing_qualities': missing_qualities,
                    'audio_type': "Dub" if any('eng' in link['text'].lower() for link in download_links) else "Sub"
                }
                anime_queue.add_to_pending(queue_info)
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗪𝗔𝗜𝗧𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Aᴠᴀɪʟᴀʙʟᴇ: {', '.join(available_qualities) if available_qualities else 'None'}\n"
                    f"・ Mɪssɪɴɢ: {', '.join(missing_qualities)}\n"
                    f"・ Sᴛᴀᴛᴜs: Wᴀɪᴛɪɴɢ ғᴏʀ ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇs</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            
            return False
        
        anime_queue.mark_as_processed(anime_title, episode_number)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing episode: {e}")
        return False
    finally:
        _currently_processing = False


async def check_for_new_episodes(client):
    global _currently_processing
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    progress = None
    
    if not auto_download_state.enabled:
        return
    
    scheduler_lock = _get_scheduler_lock()
    if scheduler_lock:
        if scheduler_lock.locked():
            logger.info("Scheduler lock held by another task. Skipping this check.")
            return
        
        acquired = scheduler_lock.locked() == False
        if not acquired:
            logger.info("Could not acquire scheduler lock. Skipping this check.")
            return
    
    if _currently_processing:
        logger.info("Already processing an episode. Skipping auto check.")
        return
    
    async with scheduler_lock if scheduler_lock else asyncio.Lock():
        logger.info("Checking for new episodes and pending queue...")
        
        if anime_queue.pending_queue:
            logger.info(f"Processing {len(anime_queue.pending_queue)} pending episodes first...")
            await process_pending_queue()
        
        try:
            if auto_download_state.last_checked:
                last_check = datetime.fromisoformat(auto_download_state.last_checked)
                time_since_last_check = (datetime.now() - last_check).total_seconds()
                
                cooldown_period = auto_download_state.interval / 2
                if time_since_last_check < cooldown_period:
                    logger.info(f"Skipping auto check, last check was {time_since_last_check:.1f} seconds ago")
                    return
            
            latest_data = get_latest_releases(page=1)
            if not latest_data or 'data' not in latest_data:
                logger.error("Failed to get latest releases")
                return
            
            unprocessed_anime = []
            for anime_data in latest_data['data']:
                anime_title = anime_data.get('anime_title', 'Unknown Anime')
                episode_number = anime_data.get('episode', 0)
                
                if is_episode_processed(anime_title, episode_number):
                    logger.debug(f"Skipping {anime_title} Ep{episode_number}: already processed (old system)")
                    continue
                
                if episode_tracker.is_posted(anime_title, episode_number):
                    logger.debug(f"Skipping {anime_title} Ep{episode_number}: already POSTED")
                    continue
                
                if episode_tracker.is_processing(anime_title, episode_number):
                    logger.debug(f"Skipping {anime_title} Ep{episode_number}: currently PROCESSING")
                    continue
                
                unprocessed_anime.append(anime_data)
                logger.info(f"Found unprocessed: {anime_title} Episode {episode_number}")
            
            if not unprocessed_anime:
                logger.info("No new unprocessed anime found.")
                auto_download_state.last_checked = datetime.now().isoformat()
                return
            
            logger.info(f"Found {len(unprocessed_anime)} unprocessed anime to process sequentially")
            
            if ADMIN_CHAT_ID:
                progress = ProgressMessage(client, ADMIN_CHAT_ID, f"<b><blockquote>ғᴏᴜɴᴅ {len(unprocessed_anime)} ɴᴇᴡ ᴀɴɪᴍᴇ ᴛᴏ ᴘʀᴏᴄᴇss...</blockquote></b>", parse_mode='html')
                await progress.send()
            
            processed_count = 0
            failed_count = 0
            skipped_count = 0
            
            for idx, anime_data in enumerate(unprocessed_anime):
                anime_title = anime_data.get('anime_title', 'Unknown Anime')
                episode_number = anime_data.get('episode', 0)
                
                if not episode_tracker.try_start_processing(anime_title, episode_number):
                    logger.info(f"Skipping {anime_title} Ep{episode_number}: could not acquire processing lock")
                    skipped_count += 1
                    continue
                
                logger.info(f"Processing anime {idx + 1}/{len(unprocessed_anime)}: {anime_title} Episode {episode_number}")
                
                if progress:
                    await progress.update(
                        f"<b><blockquote>✦ 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                        f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                        f"・ Pʀᴏɢʀᴇss: {idx + 1}/{len(unprocessed_anime)}\n"
                        f"・ Sᴛᴀᴛᴜs: Pʀᴏᴄᴇssɪɴɢ</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                        parse_mode='html'
                    )
                
                try:
                    success = await process_specific_anime(anime_data, progress)
                    
                    if success:
                        processed_count += 1
                        logger.info(f"Successfully processed: {anime_title} Episode {episode_number}")
                    else:
                        failed_count += 1
                        logger.warning(f"Failed to process: {anime_title} Episode {episode_number}")
                        episode_tracker.release_processing(anime_title, episode_number, success=False)
                        
                except Exception as e:
                    failed_count += 1
                    logger.error(f"Error processing {anime_title} Episode {episode_number}: {e}")
                    episode_tracker.release_processing(anime_title, episode_number, success=False)
                    continue
            
            auto_download_state.last_checked = datetime.now().isoformat()
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘𝗗 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Pʀᴏᴄᴇssᴇᴅ: {processed_count}\n"
                    f"・ Fᴀɪʟᴇᴅ: {failed_count}\n"
                    f"・ Sᴋɪᴘᴘᴇᴅ: {skipped_count}\n"
                    f"・ Tᴏᴛᴀʟ: {len(unprocessed_anime)}</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            
            logger.info(f"Batch processing complete: {processed_count} processed, {failed_count} failed, {skipped_count} skipped")
            
        except Exception as e:
            logger.error(f"Error checking for new episodes: {str(e)}")
            if progress:
                await progress.update(
                    f"<b><blockquote>ᴇʀʀᴏʀ ᴘʀᴏᴄᴇssɪɴɢ ᴀɴɪᴍᴇ:</b> {str(e)}</blockquote>",
                    parse_mode='html'
                )


async def process_specific_anime(anime_data: dict, progress=None) -> bool:
    global _currently_processing
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    
    if _currently_processing:
        logger.info("Already processing, skipping this anime for now")
        return False
    
    _currently_processing = True
    
    anime_title = anime_data.get('anime_title', 'Unknown Anime')
    episode_number = anime_data.get('episode', 0)
    post_created = False
    
    files_to_cleanup = []
    
    try:
        search_results = await search_anime(anime_title)
        if not search_results:
            logger.error(f"Anime not found: {anime_title}")
            return False
        
        anime_info = search_results[0]
        anime_session = anime_info['session']
        
        episodes = await get_all_episodes(anime_session)
        if not episodes:
            logger.error(f"Failed to get episode list for {anime_title}")
            return False
        
        target_episode = None
        for ep in episodes:
            try:
                if int(ep['episode']) == episode_number:
                    target_episode = ep
                    break
            except (ValueError, TypeError):
                continue
        
        if not target_episode:
            target_episode = find_closest_episode(episodes, episode_number)
            if target_episode:
                episode_number = int(target_episode['episode'])
            else:
                logger.error(f"No episodes found for {anime_title}")
                return False
        
        episode_session = target_episode['session']
        
        download_links = get_download_links(anime_session, episode_session)
        if not download_links:
            logger.error(f"No download links found for {anime_title} Episode {episode_number}")
            return False
        
        enabled_qualities = quality_settings.enabled_qualities
        
        quality_mapping = get_available_qualities_with_mapping(download_links, enabled_qualities)
        
        available_qualities = [q for q, link in quality_mapping.items() if link is not None]
        missing_from_source = [q for q in enabled_qualities if q not in available_qualities]
        
        if not available_qualities:
            logger.error(f"No suitable qualities found for {anime_title} Episode {episode_number}")
            logger.info(f"Available links: {[link['text'] for link in download_links]}")
            logger.info(f"Enabled qualities: {enabled_qualities}")
            return False
        
        if missing_from_source:
            logger.warning(
                f"SKIPPING {anime_title} Ep{episode_number}: not all selected qualities available yet. "
                f"Available: {available_qualities}, Missing: {missing_from_source}"
            )
            logger.info(f"Source links: {[link['text'] for link in download_links]}")
            logger.info(f"Enabled qualities: {enabled_qualities}")
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗪𝗔𝗜𝗧𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Aᴠᴀɪʟᴀʙʟᴇ: {', '.join(available_qualities)}\n"
                    f"・ Mɪssɪɴɢ: {', '.join(missing_from_source)}\n"
                    f"・ Sᴛᴀᴛᴜs: Wᴀɪᴛɪɴɢ ғᴏʀ ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇs</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            return False
        
        logger.info(f"=== QUALITY PROCESSING PLAN for {anime_title} Ep{episode_number} ===")
        logger.info(f"Enabled qualities: {enabled_qualities}")
        logger.info(f"Available via mapping: {available_qualities}")
        
        is_dub = any('eng' in link['text'].lower() for link in download_links)
        audio_type = "Dub" if is_dub else "Sub"
        
        sorted_qualities = sorted(available_qualities, key=lambda x: int(x[:-1]))
        
        quality_results = {}
        quality_files = {}
        
        for quality_idx, quality in enumerate(sorted_qualities):
            quality_results[quality] = {
                'downloaded': False,
                'uploaded': False,
                'msg_id': None,
                'error': None
            }
            
            download_path = None
            
            try:
                logger.info(f"Processing {quality} ({quality_idx + 1}/{len(sorted_qualities)}) for {anime_title} Ep{episode_number}")
                
                quality_link = quality_mapping[quality]
                if not quality_link:
                    quality_results[quality]['error'] = "No link available"
                    logger.error(f"Quality {quality} link not available")
                    continue
                
                if progress:
                    await progress.update(
                        f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                        f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                        f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_idx + 1}/{len(sorted_qualities)})\n"
                        f"・ Sᴏᴜʀᴄᴇ: {quality_link['text'][:40]}...</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                        parse_mode='html'
                    )
                
                base_name = format_filename(anime_title, episode_number, quality, "Sub" if not is_dub else "Dub")
                main_channel_username = CHANNEL_USERNAME if CHANNEL_USERNAME else BOT_USERNAME
                full_caption = f"**{base_name} {main_channel_username}.mkv**"
                filename = sanitize_filename(full_caption)
                download_path = os.path.join(DOWNLOAD_DIR, filename)
                
                kwik_link = extract_kwik_link(quality_link['href'])
                if not kwik_link:
                    quality_results[quality]['error'] = "Failed to extract kwik link"
                    logger.error(f"Failed to extract kwik link for {quality}")
                    continue
                
                direct_link = get_dl_link(kwik_link)
                if not direct_link:
                    quality_results[quality]['error'] = "Failed to get direct link"
                    logger.error(f"Failed to get direct link for {quality}")
                    continue
                
                ydl_opts = {
                    'outtmpl': download_path,
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': YTDLP_HEADERS,
                    'nocheckcertificate': True,
                    'compat_opts': ['no-keep-video'],
                    'retries': 5,
                    'fragment_retries': 10,
                }
                
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([direct_link])
                except Exception as dl_error:
                    quality_results[quality]['error'] = f"Download error: {str(dl_error)}"
                    logger.error(f"Download error for {quality}: {dl_error}")
                    continue
                
                if not os.path.exists(download_path):
                    quality_results[quality]['error'] = "Downloaded file does not exist"
                    logger.error(f"Downloaded file does not exist for {quality}")
                    continue
                
                file_size = os.path.getsize(download_path)
                if file_size < 1000:
                    quality_results[quality]['error'] = f"Downloaded file too small ({file_size} bytes)"
                    logger.error(f"Downloaded file too small for {quality}: {file_size} bytes")
                    try:
                        os.remove(download_path)
                    except:
                        pass
                    continue
                
                quality_results[quality]['downloaded'] = True
                episode_tracker.mark_quality_downloaded(anime_title, episode_number, quality)
                logger.info(f"Download SUCCESS for {quality}: {format_size(file_size)}")
                
                if FFMPEG_AVAILABLE:
                    final_path = os.path.join(DOWNLOAD_DIR, f"[E{episode_number:02d}] - {anime_title} [{quality}].mkv")
                    if await rename_video_with_ffmpeg(download_path, final_path):
                        try:
                            os.remove(download_path)
                        except:
                            pass
                        download_path = final_path
                
                files_to_cleanup.append(download_path)
                
                if progress:
                    await progress.update(
                        f"<b><blockquote>✦ 𝗨𝗣𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                        f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                        f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_idx + 1}/{len(sorted_qualities)})\n"
                        f"・ Sɪᴢᴇ: {format_size(file_size)}\n"
                        f"・ Sᴛᴀᴛᴜs: Uᴘʟᴏᴀᴅɪɴɢ...</blockquote>\n"
                        f"──────────────────\n"
                        f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                        parse_mode='html'
                    )
                
                thumb = await get_fixed_thumbnail()
                
                dump_msg_id = await robust_upload_file(
                    file_path=download_path,
                    caption=full_caption,
                    thumb_path=thumb,
                    max_retries=3
                )
                
                if dump_msg_id:
                    quality_results[quality]['uploaded'] = True
                    quality_results[quality]['msg_id'] = dump_msg_id
                    
                    if quality not in quality_files:
                        quality_files[quality] = []
                    quality_files[quality].append(dump_msg_id)
                    
                    episode_tracker.mark_quality_uploaded(anime_title, episode_number, quality, dump_msg_id)
                    update_processed_qualities(anime_title, episode_number, quality)
                    
                    logger.info(f"Upload SUCCESS for {quality}: msg_id={dump_msg_id}")
                    
                    try:
                        os.remove(download_path)
                        files_to_cleanup.remove(download_path)
                    except:
                        pass
                else:
                    quality_results[quality]['error'] = "Upload failed after retries"
                    logger.error(f"Upload FAILED for {quality} - file kept for manual retry")
                
            except Exception as e:
                quality_results[quality]['error'] = f"Exception: {str(e)}"
                logger.error(f"Error processing quality {quality}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        successful_qualities = [q for q, r in quality_results.items() if r['uploaded']]
        failed_qualities = [q for q, r in quality_results.items() if not r['uploaded']]
        
        logger.info(f"=== QUALITY RESULTS for {anime_title} Ep{episode_number} ===")
        logger.info(f"Successful: {successful_qualities}")
        logger.info(f"Failed: {failed_qualities}")
        for q, r in quality_results.items():
            if r['error']:
                logger.info(f"  {q}: {r['error']}")
        
        if failed_qualities:
            upload_failed_qualities = [q for q, r in quality_results.items() if r['downloaded'] and not r['uploaded']]
            download_failed_qualities = [q for q, r in quality_results.items() if not r['downloaded']]
            
            logger.error(
                f"EPISODE MARKED FAILED: {anime_title} Ep{episode_number} - "
                f"Upload failures: {upload_failed_qualities}, Download failures: {download_failed_qualities}. "
                f"No post created. No re-download. Scheduler will skip this episode."
            )
            
            episode_tracker.release_processing(anime_title, episode_number, success=False)
            
            for f_path in files_to_cleanup:
                try:
                    if os.path.exists(f_path):
                        os.remove(f_path)
                        logger.info(f"Cleaned up failed upload file: {f_path}")
                except Exception as cleanup_err:
                    logger.warning(f"Could not cleanup file {f_path}: {cleanup_err}")
            
            if progress:
                await progress.update(
                    f"<b><blockquote>✦ 𝗙𝗔𝗜𝗟𝗘𝗗 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Uᴘʟᴏᴀᴅ Fᴀɪʟᴇᴅ: {', '.join(upload_failed_qualities) if upload_failed_qualities else 'None'}\n"
                    f"・ Dᴏᴡɴʟᴏᴀᴅ Fᴀɪʟᴇᴅ: {', '.join(download_failed_qualities) if download_failed_qualities else 'None'}\n"
                    f"・ Sᴛᴀᴛᴜs: Fᴀɪʟᴇᴅ ᴀғᴛᴇʀ 3 ʀᴇᴛʀɪᴇs - sᴋɪᴘᴘᴇᴅ</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            
            return False
        
        if not quality_files:
            logger.error(f"No qualities uploaded successfully for {anime_title} Ep{episode_number}")
            return False
        
        logger.info(f"ALL {len(successful_qualities)} qualities uploaded successfully - creating post")
        
        episode_tracker.mark_completed(anime_title, episode_number)
        
        max_post_retries = 3
        for retry in range(max_post_retries):
            try:
                anilist_info = await get_anime_info(anime_title)
                await post_anime_with_buttons(
                    client, 
                    anime_title, 
                    anilist_info,
                    episode_number, 
                    audio_type, 
                    quality_files
                )
                post_created = True
                logger.info(f"Successfully posted banner for {anime_title} Episode {episode_number}")
                break
            except FloodWaitError as e:
                logger.warning(f"Flood wait during post (attempt {retry+1}/{max_post_retries}): {e.seconds}s")
                await asyncio.sleep(e.seconds + 5)
            except Exception as e:
                logger.error(f"Error posting banner (attempt {retry+1}/{max_post_retries}): {e}")
                if retry < max_post_retries - 1:
                    await asyncio.sleep(5)
        
        if not post_created:
            logger.error(f"CRITICAL: Failed to create post for {anime_title} Episode {episode_number} after {max_post_retries} attempts!")
            return False
        
        episode_tracker.mark_posted(anime_title, episode_number)
        
        if progress:
            await progress.update(
                f"<b><blockquote>✦ 𝗖𝗢𝗠𝗣𝗟𝗘𝗧𝗘 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"・ Qᴜᴀʟɪᴛɪᴇs: {', '.join(successful_qualities)}\n"
                f"・ Sᴛᴀᴛᴜs: Pᴏsᴛᴇᴅ ✓</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )
        
        logger.info(f"=== SUCCESS: {anime_title} Ep{episode_number} fully processed ===")
        return True
            
    except Exception as e:
        logger.error(f"Error in process_specific_anime: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        _currently_processing = False


async def process_all_qualities(client):
    global _currently_processing
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    if _currently_processing:
        logger.info("Already processing an episode. Skipping auto check.")
        return
    
    logger.info("Processing latest airing anime with all qualities...")
    
    try:
        latest_data = get_latest_releases(page=1)
        if not latest_data or 'data' not in latest_data:
            logger.error("Failed to get latest releases")
            return

        latest_anime = latest_data['data'][0]
        anime_title = latest_anime.get('anime_title', 'Unknown Anime')
        episode_number = latest_anime.get('episode', 0)

        if is_episode_processed(anime_title, episode_number):
            logger.info(f"Episode {episode_number} of {anime_title} already processed. Skipping.")
            return
        
        if ADMIN_CHAT_ID:
            progress = ProgressMessage(client, ADMIN_CHAT_ID, f"<b></blockquote>ᴘʀᴏᴄᴇssɪɴɢ ʟᴀᴛᴇsᴛ ᴀɪʀɪɴɢ ᴀɴɪᴍᴇ ᴡɪᴛʜ ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇs...</b></blockquote>", parse_mode='html')
            if not await progress.send():
                logger.error("Failed to send progress message")
                return
            
            await progress.update(
                f"<b><blockquote>✦ 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"・ Sᴛᴀᴛᴜs: Pʀᴏᴄᴇssɪɴɢ</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                parse_mode='html'
            )
        
        success = await auto_download_latest_episode()
        
        if success:
            logger.info("Successfully processed latest episode with all qualities")
            if progress:
                await progress.update(
                    f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ ᴘʀᴏᴄᴇssᴇᴅ: ᴀɴɪᴍᴇ {anime_title} | ᴇᴘɪsᴏᴅᴇ {episode_number} ᴡɪᴛʜ ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇs</b></blockquote>",
                    parse_mode='html'
                )
        else:
            logger.error("Failed to process latest episode with all qualities")
            if progress:
                await progress.update(
                    f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴘʀᴏᴄᴇss: ᴀɴɪᴍᴇ {anime_title} | ᴇᴘɪsᴏᴅᴇ {episode_number} ᴡɪᴛʜ ᴀʟʟ ǫᴜᴀʟɪᴛɪᴇs</b></blockquote>",
                    parse_mode='html'
                )
    except Exception as e:
        logger.error(f"Error processing latest airing anime: {str(e)}")
        if progress:
            await progress.update(
                f"<b><blockquote>ᴇʀʀᴏʀ ᴘʀᴏᴄᴇssɪɴɢ ʟᴀᴛᴇsᴛ ᴀɪʀɪɴɢ ᴀɴɪᴍᴇ:</b> {str(e)}</blockquote>",
                parse_mode='html'
            )


async def process_daily_requests(client):
    global _currently_processing
    
    from core.database import (
        get_all_pending_requests, mark_request_processed, 
        get_processed_request_results, add_processed_request_result
    )
    from core.download import post_anime_batch_with_buttons
    
    logger.info("Processing daily requests...")
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    
    _currently_processing = True
    logger.info("Request processing started - auto-processing PAUSED")
    
    try:
        pending_requests = await get_all_pending_requests()
        
        if not pending_requests:
            logger.info("No pending requests to process")
            return
        
        logger.info(f"Found {len(pending_requests)} pending requests to process")
        
        for idx, request in enumerate(pending_requests, 1):
            try:
                request_text = request.get('text')
                request_id = request.get('_id')
                user_id = request.get('user_id')
                
                logger.info(f"Processing request {idx}/{len(pending_requests)}: {request_text}")
                
                if ADMIN_CHAT_ID:
                    progress = ProgressMessage(client, ADMIN_CHAT_ID, 
                        f"<b><blockquote>ᴘʀᴏᴄᴇssɪɴɢ ʀᴇǫᴜᴇsᴛ ({idx}/{len(pending_requests)})...</b></blockquote>",
                        parse_mode='html'
                    )
                    if not await progress.send():
                        logger.error("Failed to send progress message")
                        continue
                else:
                    progress = None
                
                search_results = await search_anime(request_text)
                
                if not search_results:
                    logger.warning(f"No results found for request: {request_text}")
                    if progress:
                        await progress.update(
                            f"<b><blockquote>ɴᴏ ʀᴇsᴜʟᴛs ғᴏᴜɴᴅ ғᴏʀ: {request_text}</b></blockquote>",
                            parse_mode='html'
                        )
                    mark_request_processed(request_id)
                    continue
                
                processed_results = await get_processed_request_results(request_text)
                logger.info(f"Previously processed results for '{request_text}': {processed_results}")
                
                remaining_results = []
                for result in search_results:
                    anime_title = result.get('title', result.get('anime_title'))
                    if anime_title not in processed_results:
                        remaining_results.append(result)
                
                if not remaining_results:
                    logger.info(f"All search results for '{request_text}' have been processed")
                    if progress:
                        await progress.update(
                            f"<b><blockquote>ᴀʟʟ ʀᴇsᴜʟᴛs ғᴏʀ '{request_text}' ʜᴀᴠᴇ ʙᴇᴇɴ ᴘʀᴏᴄᴇssᴇᴅ</b></blockquote>",
                            parse_mode='html'
                        )
                    mark_request_processed(request_id)
                    continue
                
                if progress:
                    await progress.update(
                        f"<b><blockquote>ғᴏᴜɴᴅ {len(remaining_results)} ɴᴇᴡ ʀᴇsᴜʟᴛs ғᴏʀ: {request_text}\n"
                        f"ᴘʀᴏᴄᴇssɪɴɢ...</b></blockquote>",
                        parse_mode='html'
                    )
                
                processed_any = False
                for result_idx, anime_result in enumerate(remaining_results[:1], 1):
                    try:
                        anime_title = anime_result.get('title', anime_result.get('anime_title'))
                        anime_session = anime_result.get('session')
                        
                        if progress:
                            await progress.update(
                                f"<b><blockquote>ᴘʀᴏᴄᴇssɪɴɢ:</b>\n"
                                f"{anime_title}</blockquote>",
                                parse_mode='html'
                            )
                        
                        logger.info(f"Processing result: {anime_title}")
                        
                        episodes = await get_all_episodes(anime_session)
                        if not episodes:
                            logger.warning(f"No episodes found for {anime_title}")
                            continue
                        
                        total_episodes = len(episodes)
                        logger.info(f"Found {total_episodes} episodes for {anime_title}")
                        
                        anime_info = await get_anime_info(anime_title)
                        
                        enabled_qualities = quality_settings.enabled_qualities
                        sorted_qualities = sorted(enabled_qualities, key=lambda x: int(x[:-1]))
                        
                        all_quality_files = {q: [] for q in sorted_qualities}
                        
                        first_ep_links = get_download_links(anime_session, episodes[0].get('session'))
                        is_dub = any('eng' in link['text'].lower() for link in first_ep_links) if first_ep_links else False
                        audio_type = "Dub" if is_dub else "Sub"
                        
                        thumb = await get_fixed_thumbnail()
                        
                        for quality_idx, quality in enumerate(sorted_qualities):
                            quality_progress = quality_idx + 1
                            
                            if progress:
                                await progress.update(
                                    f"<b><blockquote>✦ 𝗥𝗘𝗤𝗨𝗘𝗦𝗧 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 ✦</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                    f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_progress}/{len(sorted_qualities)})\n"
                                    f"・ Eᴘɪsᴏᴅᴇs: {total_episodes}\n"
                                    f"・ Sᴛᴀᴛᴜs: Sᴛᴀʀᴛɪɴɢ {quality} ʙᴀᴛᴄʜ...</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                    parse_mode='html'
                                )
                            
                            for ep_idx, episode in enumerate(episodes):
                                episode_number = int(episode.get('episode', 0))
                                episode_session = episode.get('session')
                                
                                try:
                                    if progress:
                                        await progress.update(
                                            f"<b><blockquote>✦ 𝗥𝗘𝗤𝗨𝗘𝗦𝗧 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 ✦</blockquote>\n"
                                            f"──────────────────\n"
                                            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                            f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_progress}/{len(sorted_qualities)})\n"
                                            f"・ Eᴘɪsᴏᴅᴇ: {episode_number} ({ep_idx+1}/{total_episodes})\n"
                                            f"・ Sᴛᴀᴛᴜs: Dᴏᴡɴʟᴏᴀᴅɪɴɢ...</blockquote>\n"
                                            f"──────────────────\n"
                                            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                            parse_mode='html'
                                        )
                                    
                                    download_links = get_download_links(anime_session, episode_session)
                                    if not download_links:
                                        logger.warning(f"No download links for {anime_title} Episode {episode_number}")
                                        continue
                                    
                                    quality_mapping = get_available_qualities_with_mapping(download_links, [quality])
                                    quality_link = quality_mapping.get(quality)
                                    
                                    if not quality_link:
                                        logger.warning(f"Quality {quality} not available for Episode {episode_number}")
                                        continue
                                    
                                    kwik_link = extract_kwik_link(quality_link['href'])
                                    if not kwik_link:
                                        continue
                                    
                                    direct_link = get_dl_link(kwik_link)
                                    if not direct_link:
                                        continue
                                    
                                    base_name = format_filename(anime_title, episode_number, quality, audio_type)
                                    main_channel_username = CHANNEL_USERNAME if CHANNEL_USERNAME else BOT_USERNAME
                                    full_caption = f"**{base_name} {main_channel_username}.mkv**"
                                    filename = sanitize_filename(f"{base_name}.mkv")
                                    download_path = os.path.join(DOWNLOAD_DIR, filename)
                                    
                                    if progress:
                                        await progress.update(
                                            f"<b><blockquote>✦ 𝗥𝗘𝗤𝗨𝗘𝗦𝗧 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 ✦</blockquote>\n"
                                            f"──────────────────\n"
                                            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                            f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_progress}/{len(sorted_qualities)})\n"
                                            f"・ Eᴘɪsᴏᴅᴇ: {episode_number} ({ep_idx+1}/{total_episodes})\n"
                                            f"・ Sᴛᴀᴛᴜs: Dᴏᴡɴʟᴏᴀᴅɪɴɢ {quality}...</blockquote>\n"
                                            f"──────────────────\n"
                                            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                            parse_mode='html'
                                        )
                                    
                                    ydl_opts = {
                                        'outtmpl': download_path,
                                        'quiet': True,
                                        'no_warnings': True,
                                        'http_headers': YTDLP_HEADERS,
                                        'nocheckcertificate': True,
                                    }
                                    
                                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                        ydl.download([direct_link])
                                    
                                    if not os.path.exists(download_path) or os.path.getsize(download_path) < 1000:
                                        logger.error(f"Downloaded file is too small: {download_path}")
                                        continue
                                    
                                    if progress:
                                        await progress.update(
                                            f"<b><blockquote>✦ 𝗥𝗘𝗤𝗨𝗘𝗦𝗧 𝗣𝗥𝗢𝗖𝗘𝗦𝗦𝗜𝗡𝗚 ✦</blockquote>\n"
                                            f"──────────────────\n"
                                            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                            f"・ Qᴜᴀʟɪᴛʏ: {quality} ({quality_progress}/{len(sorted_qualities)})\n"
                                            f"・ Eᴘɪsᴏᴅᴇ: {episode_number} ({ep_idx+1}/{total_episodes})\n"
                                            f"・ Sᴛᴀᴛᴜs: Uᴘʟᴏᴀᴅɪɴɢ {quality}...</blockquote>\n"
                                            f"──────────────────\n"
                                            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                            parse_mode='html'
                                        )
                                    
                                    dump_msg_id = await robust_upload_file(
                                        file_path=download_path,
                                        caption=full_caption,
                                        thumb_path=thumb,
                                        max_retries=3
                                    )
                                    
                                    if dump_msg_id:
                                        all_quality_files[quality].append(dump_msg_id)
                                        logger.info(f"Uploaded Episode {episode_number} [{quality}] - msg_id: {dump_msg_id}")
                                    else:
                                        logger.error(f"Upload FAILED after 3 retries: Episode {episode_number} [{quality}] - skipping")
                                    
                                    try:
                                        os.remove(download_path)
                                    except:
                                        pass
                                
                                except Exception as e:
                                    logger.error(f"Error processing Episode {episode_number} [{quality}]: {e}")
                                    import traceback
                                    logger.error(traceback.format_exc())
                            
                            logger.info(f"Completed all episodes for quality {quality}: {len(all_quality_files[quality])} uploaded")
                        
                        final_quality_files = {q: ids for q, ids in all_quality_files.items() if ids}
                        
                        if final_quality_files and anime_info:
                            logger.info(f"Creating final channel post for {anime_title}")
                            logger.info(f"Quality files: {final_quality_files}")
                            
                            if progress:
                                await progress.update(
                                    f"<b><blockquote>✦ 𝗙𝗜𝗡𝗔𝗟𝗜𝗭𝗜𝗡𝗚 ✦</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                    f"・ Eᴘɪsᴏᴅᴇs: {total_episodes}\n"
                                    f"・ Sᴛᴀᴛᴜs: Cʀᴇᴀᴛɪɴɢ ғɪɴᴀʟ ᴘᴏsᴛ...</blockquote>\n"
                                    f"──────────────────\n"
                                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                                    parse_mode='html'
                                )
                            
                            await post_anime_batch_with_buttons(
                                client, anime_title, anime_info, final_quality_files, total_episodes, audio_type
                            )
                            
                            await add_processed_request_result(request_text, anime_title)
                            processed_any = True
                            logger.info(f"Successfully processed ALL {total_episodes} episodes of '{anime_title}'")
                        else:
                            logger.warning(f"No files uploaded for {anime_title}")
                        
                    except Exception as e:
                        logger.error(f"Error processing result: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                
                if processed_any:
                    mark_request_processed(request_id)
                    
                    if progress:
                        await progress.update(
                            f"<b><blockquote>✦ ᴄᴏᴍᴘʟᴇᴛᴇᴅ ✦</blockquote>\n"
                            f"──────────────────\n"
                            f"<blockquote>・ Rᴇǫᴜᴇsᴛ: {request_text}\n"
                            f"・ Sᴛᴀᴛᴜs: ᴄᴏᴍᴘʟᴇᴛᴇᴅ</blockquote>\n"
                            f"──────────────────\n"
                            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                            parse_mode='html'
                        )
                else:
                    logger.warning(f"Failed to process any results for request '{request_text}'")
                    if progress:
                        await progress.update(
                            f"<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ᴘʀᴏᴄᴇss ʀᴇǫᴜᴇsᴛ: {request_text}</b></blockquote>",
                            parse_mode='html'
                        )
                
            except Exception as e:
                logger.error(f"Error processing request {idx}: {e}")
                import traceback
                logger.error(traceback.format_exc())
        
        logger.info("Daily request processing completed")
        
    except Exception as e:
        logger.error(f"Error in process_daily_requests: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        _currently_processing = False
        logger.info("Request processing finished - auto-processing RESUMED")


# IST Timezone (UTC+5:30)
IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")


def convert_ist_to_utc(ist_time_str: str) -> str:
    try:
        hour, minute = map(int, ist_time_str.split(':'))
        
        today = datetime.now(IST).date()
        ist_datetime = datetime(today.year, today.month, today.day, hour, minute, tzinfo=IST)
        
        utc_datetime = ist_datetime.astimezone(UTC)
        
        return utc_datetime.strftime('%H:%M')
    except Exception as e:
        logger.error(f"Error converting IST to UTC: {e}")
        return ist_time_str


def get_current_ist_time() -> str:
    return datetime.now(IST).strftime('%H:%M')


_request_time_job_tag = "daily_request_processing"


def setup_scheduler(client):
    def schedule_check():
        asyncio.create_task(check_for_new_episodes(client))
    
    def schedule_queue_check():
        asyncio.create_task(process_pending_queue())
    
    def schedule_daily_requests():
        asyncio.create_task(process_daily_requests(client))
        logger.info(f"Triggered daily request processing at {get_current_utc_time()} UTC / {get_current_ist_time()} IST")
    
    async def setup_daily_request_scheduler():
        from core.database import get_request_process_time
        
        try:
            ist_time_str = await get_request_process_time()
            
            if ist_time_str and ist_time_str != "00:00":
                utc_time_str = convert_ist_to_utc(ist_time_str)
                
                schedule.clear(_request_time_job_tag)
                
                schedule.every().day.at(utc_time_str).do(schedule_daily_requests).tag(_request_time_job_tag)
                
                logger.info(f"𝗗𝗮𝗶𝗹𝘆 𝗿𝗲𝗾𝘂𝗲𝘀𝘁 𝗽𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝘀𝗰𝗵𝗲𝗱𝘂𝗹𝗲𝗱 𝗮𝘁 {ist_time_str} IST ({utc_time_str} UTC)")
            else:
                logger.info("No daily request processing time configured")
        except Exception as e:
            logger.error(f"Error setting up daily request scheduler: {e}")
    
    def reschedule():
        for job in schedule.get_jobs():
            if _request_time_job_tag not in job.tags:
                schedule.cancel_job(job)
        
        interval = auto_download_state.interval
        schedule.every(interval).seconds.do(schedule_check)
        logger.info(f"𝙎𝙩𝙖𝙧𝙩𝙞𝙣𝙜 𝙎𝙘𝙝𝙚𝙙𝙪𝙡𝙚𝙧")
    
    reschedule()
    
    asyncio.create_task(setup_daily_request_scheduler())
    
    orig_setter = auto_download_state.__class__.interval.fset
    def interval_setter(self, seconds):
        orig_setter(self, seconds)
        reschedule()
    
    auto_download_state.__class__.interval = auto_download_state.__class__.interval.setter(interval_setter)
    
    async def scheduler_loop():
        while True:
            schedule.run_pending()
            await asyncio.sleep(1)
    
    asyncio.create_task(scheduler_loop())


async def reschedule_daily_requests(ist_time_str: str):
    try:
        utc_time_str = convert_ist_to_utc(ist_time_str)
        
        schedule.clear(_request_time_job_tag)
        
        def schedule_daily_requests_job():
            from core.client import client
            asyncio.create_task(process_daily_requests(client))
            logger.info(f"Triggered daily request processing at {get_current_utc_time()} UTC / {get_current_ist_time()} IST")
        
        schedule.every().day.at(utc_time_str).do(schedule_daily_requests_job).tag(_request_time_job_tag)
        
        logger.info(f"𝗥𝗲𝘀𝗰𝗵𝗲𝗱𝘂𝗹𝗲𝗱 𝗱𝗮𝗶𝗹𝘆 𝗿𝗲𝗾𝘂𝗲𝘀𝘁 𝗽𝗿𝗼𝗰𝗲𝘀𝘀𝗶𝗻𝗴 𝘁𝗼 {ist_time_str} IST ({utc_time_str} UTC)")
        return True
    except Exception as e:
        logger.error(f"Error rescheduling daily requests: {e}")
        return False
