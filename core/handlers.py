from __future__ import annotations
import os
import re
import time
import base64
import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
from bs4 import BeautifulSoup
from telethon import events, types
from telethon.tl import functions
from telethon.tl.custom import Button
from telethon.tl.types import PeerUser
from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import WebpageMediaEmptyError

from core.config import *
from core.client import *
from core.state import *
from core.utils import *
from core.anime_api import *
from core.download import *
from core.scheduler import *
import base64

try:
    import yt_dlp
except ImportError:
    logger.error("yt-dlp not installed")

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = BASE_DIR / "anime_downloads"

currently_processing = False

async def delete_message_after(message, seconds):
    await asyncio.sleep(seconds)
    try:
        await client.delete_messages(message.chat_id, [message.id])
        logger.info(f"Deleted message {message.id} from chat {message.chat_id}")
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

async def download_anime_by_index(event, index: int, force_redownload: bool = False):
    global currently_processing
    channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
    logger.info(f"Downloading anime at index {index} from latest airing list...")
    
    if currently_processing:
        await safe_respond(event, "<b><blockquote>ᴀʟʀᴇᴀᴅʏ ᴘʀᴏᴄᴇssɪɴɢ ᴀɴᴏᴛʜᴇʀ ᴀɴɪᴍᴇ. ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ.</b></blockquote>", parse_mode='html')
        return False
    
    currently_processing = True
    try:
        progress = ProgressMessage(client, event.chat_id, f"<b><blockquote>ᴀᴅᴅɪɴɢ ᴛᴀsᴋ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴɪᴍᴇ ᴀᴛ ɪɴᴅᴇx {index}...</b></blockquote>", parse_mode='html')
        if not await progress.send():
            await safe_respond(
                event,
                "<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɪɴɪᴛɪᴀʟɪᴢᴇ ᴘʀᴏɢʀᴇss ᴛʀᴀᴄᴋɪɴɢ</b></blockquote>",
                parse_mode='html'
            )
            return False
        
        await progress.update("<b><blockquote>ғᴇᴛᴄʜɪɴɢ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ʟɪsᴛ...</b></blockquote>", parse_mode='html')
        latest_data = get_latest_releases(page=1)
        if not latest_data or 'data' not in latest_data:
            logger.error("Failed to get latest releases")
            await progress.update("<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ʟᴀᴛᴇsᴛ ʀᴇʟᴇᴀsᴇs</b></blockquote>", parse_mode='html')
            return False
        
        if index < 1 or index > len(latest_data['data']):
            logger.error(f"Invalid index: {index}. Must be between 1 and {len(latest_data['data'])}")
            await progress.update(f"<b><blockquote>ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx: {index}. ᴍᴜsᴛ ʙᴇ ʙᴇᴛᴡᴇᴇɴ 1 ᴀɴᴅ {len(latest_data['data'])}</b></blockquote>", parse_mode='html')
            return False
        
        anime_data = latest_data['data'][index - 1]
        anime_title = anime_data.get('anime_title', 'Unknown Anime')
        episode_number = anime_data.get('episode', 0)
        
        logger.info(f"Selected anime: {anime_title} Episode {episode_number}")
        await progress.update(
            f"<b><blockquote>✦ 𝗙𝗘𝗧𝗖𝗛𝗜𝗡𝗚 𝗗𝗘𝗧𝗔𝗜𝗟𝗦 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
            f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
            f"・ Sᴛᴀᴛᴜs: Fᴇᴛᴄʜɪɴɢ ᴀɴɪᴍᴇ ᴅᴇᴛᴀɪʟs...</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode='html'
        )
        
        search_results = await search_anime(anime_title)
        if not search_results:
            logger.error(f"Anime not found: {anime_title}")
            await progress.update(f"<b><blockquote>ᴀɴɪᴍᴇ ɴᴏᴛ ғᴏᴜɴᴅ: {anime_title}</b></blockquote>", parse_mode='html')
            return False
        
        anime_info = search_results[0]
        anime_session = anime_info['session']
        await progress.update(
            f"<b><blockquote>✦ 𝗙𝗘𝗧𝗖𝗛𝗜𝗡𝗚 𝗘𝗣𝗜𝗦𝗢𝗗𝗘 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
            f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
            f"・ Sᴛᴀᴛᴜs: Fᴇᴛᴄʜɪɴɢ ᴇᴘɪsᴏᴅᴇ ʟɪsᴛ...</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode='html'
        )
        episodes = await get_all_episodes(anime_session)
        if not episodes:
            logger.error(f"Failed to get episode list for {anime_title}")
            await progress.update(f"<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ᴇᴘɪsᴏᴅᴇ ʟɪsᴛ ғᴏʀ {anime_title}</b></blockquote>", parse_mode='html')
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
                await progress.update(
                    f"<b><blockquote>✦ 𝗖𝗟𝗢𝗦𝗘𝗦𝗧 𝗘𝗣𝗜𝗦𝗢𝗗𝗘 𝗙𝗢𝗨𝗡𝗗 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Sᴛᴀᴛᴜs: ᴄʟᴏsᴇsᴛ {actual_episode}</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
            else:
                logger.error(f"No episodes found for {anime_title}")
                await progress.update(f"<b><blockquote>ɴᴏ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ ғᴏʀ {anime_title}</b></blockquote>", parse_mode='html')
                return False
        
        episode_session = target_episode['session']
        
        await progress.update(
            f"<b><blockquote>✦ 𝗙𝗘𝗧𝗖𝗛𝗜𝗡𝗚 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 𝗟𝗜𝗡𝗞𝗦 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
            f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
            f"・ Sᴛᴀᴛᴜs: Pʀᴏᴄᴇssɪɴɢ</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
            parse_mode='html'
        )

        download_links = get_download_links(anime_session, episode_session)
        if not download_links:
            logger.error(f"No download links found for {anime_title} Episode {episode_number}")
            await progress.update(f"<b><blockquote>ɴᴏ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋs ғᴏᴜɴᴅ ғᴏʀ {anime_title} | ᴇᴘɪsᴏᴅᴇ {episode_number}<b></blockquote>", parse_mode='html')
            return False
        
        enabled_qualities = quality_settings.enabled_qualities

        is_dub = any('eng' in link['text'].lower() for link in download_links)
        audio_type = "Dub" if is_dub else "Sub"
        
        quality_mapping = get_available_qualities_with_mapping(download_links, enabled_qualities)
        available_qualities = [q for q, link in quality_mapping.items() if link is not None]
        
        if not available_qualities:
            logger.error(f"No suitable qualities found for {anime_title} Episode {episode_number}")
            logger.info(f"Available links: {[link['text'] for link in download_links]}")
            await progress.update(
                f"<b><blockquote>ɴᴏ sᴜɪᴛᴀʙʟᴇ ǫᴜᴀʟɪᴛɪᴇs ғᴏᴜɴᴅ ғᴏʀ {anime_title} | ᴇᴘɪsᴏᴅᴇ {episode_number}</b></blockquote>",
                parse_mode='html'
            )
            return False
        
        logger.info(f"Available qualities (adaptive mapping): {available_qualities}")
        
        sorted_qualities = sorted(available_qualities, key=lambda x: int(x[:-1]))
        
        downloaded_qualities = []
        quality_files = {}
        
        for quality in sorted_qualities:
            try:
                logger.info(f"Downloading {anime_title} Episode {episode_number} {quality}")
                
                quality_link = quality_mapping.get(quality)
                
                if not quality_link:
                    logger.warning(f"Quality {quality} not available, skipping")
                    continue
                

                await progress.update(
                    f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                    f"・ Sᴛᴀᴛᴜs: Pʀᴏᴄᴇssɪɴɢ {quality}</blockquote>\n"
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
                    logger.error(f"Failed to extract kwik link for {quality}")
                    continue
                
                direct_link = get_dl_link(kwik_link)
                if not direct_link:
                    logger.error(f"Failed to get direct link for {quality}")
                    continue
                
                logger.info(f"Downloading {anime_title} Episode {episode_number} {quality}")

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
                                f"<b><blockquote>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                                f"──────────────────\n"
                                f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                                f"・ Eᴘɪsᴏᴅᴇ: {episode_number}\n"
                                f"・ Pʀᴏᴄᴇssɪɴɢ: {quality}: {percent:.1f}%\n"
                                f"・ Sɪᴢᴇ: {format_size(downloaded)}/{format_size(total)}\n"
                                f"・ Sᴘᴇᴇᴅ: {format_speed(speed_val)}</blockquote>\n"
                                f"──────────────────\n"
                                f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>"
                            )
                            
                            try:
                                asyncio.create_task(progress.update(progress_text, parse_mode='html'))
                            except:
                                pass
                            
                            last_update = current_time
                
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
                    await progress.update(f"Downloaded file is too small or doesn't exist for {quality}", parse_mode='html')
                    continue
                
                download_time = time.time() - download_start
                file_size = os.path.getsize(download_path)
                avg_speed = file_size / download_time if download_time > 0 else 0
                
                await progress.update(
                    f"Selected: {anime_title} Episode {episode_number}\n\n"
                    f"Download completed for {quality}!\n"
                    f"Time: {download_time:.1f}s\n"
                    f"Size: {format_size(file_size)}\n"
                    f"Avg Sᴘᴇᴇᴅ: {format_speed(avg_speed)}\n\n"
                    f"Preparing upload..."
                )
                
                if FFMPEG_AVAILABLE:
                    final_path = os.path.join(DOWNLOAD_DIR, f"[E{episode_number:02d}] {anime_title} [{quality}].mkv")
                    if await rename_video_with_ffmpeg(download_path, final_path):
                        os.remove(download_path)
                        download_path = final_path
                
                await progress.update(f"Selected: {anime_title} Episode {episode_number}\n\nUploading {quality} to Telegram...", parse_mode='html')
                
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
                        if quality not in quality_files:
                            quality_files[quality] = []
                        quality_files[quality].append(dump_msg_id)

                    update_processed_qualities(anime_title, episode_number, quality)
                    downloaded_qualities.append(quality)
                    logger.info(f"Successfully uploaded {quality} version")
                    
                except FloodWaitError as e:
                    logger.error(f"Flood wait error: {e.seconds} seconds")
                    await progress.update(f"Flood wait: {e.seconds} seconds. Waiting...", parse_mode='html')
                    await asyncio.sleep(e.seconds + 5)
                    
                    try:
                        if DUMP_CHANNEL_ID:
                            msg = await client.send_file(
                                DUMP_CHANNEL_ID,
                                download_path,
                                caption=caption,
                                thumb=thumb,
                                force_document=True,
                                attributes=None,
                                supports_streaming=False,
                                part_size_kb=512,
                                link_preview=False
                            )
                            
                            dump_msg_id = msg.id
                            logger.info(f"Sent to dump channel {DUMP_CHANNEL_ID}")
                        elif DUMP_CHANNEL_USERNAME:
                            msg = await client.send_file(
                                DUMP_CHANNEL_USERNAME,
                                download_path,
                                caption=caption,
                                thumb=thumb,
                                force_document=True,
                                attributes=None,
                                supports_streaming=False,
                                part_size_kb=512,
                                link_preview=False
                            )
                            
                            dump_msg_id = msg.id
                            logger.info(f"Sent to dump channel {DUMP_CHANNEL_USERNAME}")
                    except Exception as e:
                        logger.error(f"Error sending video after flood wait: {e}")
                except Exception as e:
                    logger.error(f"Eʀʀᴏʀ sᴇɴᴅɪɴɢ ᴠɪᴅᴇᴏ: {e}")
                
                try:
                    os.remove(download_path)
                except:
                    pass
                
            except Exception as e:
                logger.error(f"Error processing {quality}: {e}")
        
        if quality_files:
            anime_info = await get_anime_info(anime_title)
            if anime_info:
                await post_anime_with_buttons(client, anime_title, anime_info, episode_number, audio_type, quality_files)
        
        if is_episode_processed(anime_title, episode_number):
            logger.info(f"All qualities processed for {anime_title} Episode {episode_number}")
            await progress.update(
                f"<b><blockquote>sᴜᴄᴄᴇssғᴜʟʟʏ ᴘʀᴏᴄᴇssᴇᴅ:</blockquote>\n"
                f"<blockquote>ᴀɴɪᴍᴇ: {anime_title}\n"
                f"ᴇᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ: {', '.join(downloaded_qualities)}</b></blockquote>\n",
                parse_mode='html'
            )
            return True
        else:
            logger.error(f"Not all qualities downloaded for {anime_title} Episode {episode_number}")
            await progress.update(
                f"<b><blockquote>ᴘᴀʀᴛɪᴀʟʟʏ ᴘʀᴏᴄᴇssᴇᴅ:</blockquote>\n"
                f"<blockquote>ᴀɴɪᴍᴇ: {anime_title}\n"
                f"ᴇᴘɪsᴏᴅᴇ: {episode_number}\n"
                f"ᴅᴏᴡɴʟᴏᴀᴅᴇᴅ: {', '.join(downloaded_qualities)}\n"
                f"ᴍɪssɪɴɢ: {', '.join(set(enabled_qualities) - set(downloaded_qualities))}</b></blockquote>",
                parse_mode='html'
            )
            return False
    
    except Exception as e:
        logger.error(f"Error in download_anime_by_index: {e}")
        await safe_edit(event, f"<b><blockquote>ᴇʀʀᴏʀ: {str(e)}</b></blockquote>", parse_mode='html')
        return False
    finally:
        currently_processing = False



def register_handlers():
    @client.on(events.NewMessage(pattern=r'^/start(?:\s+(.*))?$'))
    async def start_handler(event):
        user_id = event.sender_id
        chnl_name = CHANNEL_NAME
        chnl_user = CHANNEL_USERNAME.lstrip("@")
        user = await event.get_sender()
        mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"
    
        param = event.pattern_match.group(1)

        if param:
            try:
            
                base64_string = param
                string = await decode(base64_string)
                argument = string.split("-")
            
                if len(argument) == 3:
                    try:
                        start = int(int(argument[1]) / abs(DUMP_CHANNEL_ID))
                        end = int(int(argument[2]) / abs(DUMP_CHANNEL_ID))
                    except (ValueError, ZeroDivisionError):
                        await event.respond("Invalid link format.")
                        return
                    
                    if start <= end:
                        ids = list(range(start, end + 1))
                    else:
                        ids = []
                        i = start
                        while i >= end:
                            ids.append(i)
                            i -= 1
                
                elif len(argument) == 2:
                    try:
                        ids = [int(int(argument[1]) / abs(DUMP_CHANNEL_ID))]
                    except (ValueError, ZeroDivisionError):
                        await event.respond("Invalid link format.")
                        return
                else:
                    await event.respond("Invalid link format.")
                    return

                dump_channel = (
                    bot_settings.get("dump_channel_id")
                    or bot_settings.get("dump_channel_username")
                )
                if not dump_channel:
                    await event.respond("Dump channel not configured.")
                    return
    
                try:
                    processing_msg = await event.respond("<b><blockquote>Pʀᴏᴄᴇssɪɴɢ...</b></blockquote>", parse_mode='html')
                    
                    try:
                        messages = await event.client.get_messages(dump_channel, ids=ids)
                    except Exception as e:
                        logger.error(f"Error fetching messages: {e}")
                        await event.respond("Something went wrong while fetching files.")
                        return
                    
                    if not isinstance(messages, list):
                        messages = [messages]
    
                    delete_timer = bot_settings.get("file_delete_timer", 600)
                    minutes = delete_timer // 60
    
                    track_msgs = []
                    file_count = 0
                    
                    for msg in messages:
                        if msg and msg.media:
                            file_count += 1
                            try:
                                sent_msg = await event.client.send_file(
                                    event.chat_id,
                                    file=msg.media,
                                    caption=msg.message,
                                    force_document=False,
                                    link_preview=False
                                )
                                
                                if delete_timer and delete_timer > 0:
                                    track_msgs.append(sent_msg)
                                
                            except Exception as e:
                                logger.error(f"Error sending file: {e}")
                                continue
    
                    try:
                        await processing_msg.delete()
                    except:
                        pass
    
                    if file_count > 0:
                        final_msg = await event.client.send_message(
                            event.chat_id, 
                            f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ sᴇɴᴛ {file_count} ғɪʟᴇ(s)!</b></blockquote>\n"
                            f"<blockquote><b>ғɪʟᴇs ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ {minutes} ᴍɪɴs. ᴘʟᴇᴀsᴇ sᴀᴠᴇ ᴏʀ ғᴏʀᴡᴀʀᴅ ᴛʜᴇᴍ ʙᴇғᴏʀᴇ ᴛʜᴇʏ ɢᴇᴛ ᴅᴇʟᴇᴛᴇᴅ.</b></blockquote>",
                            parse_mode='html',
                            link_preview=False
                        )
                        
                        if delete_timer and delete_timer > 0:
                            track_msgs.append(final_msg)
                            for sent_msg in track_msgs:
                                asyncio.create_task(delete_message_after(event.client, sent_msg, delete_timer))
                    else:
                        await event.respond("No files found for this request.")
                        
                except Exception as e:
                    logger.error(f"Error sending files: {e}")
                    try:
                        await processing_msg.delete()
                    except:
                        pass
    
            except Exception as e:
                logger.error(f"Error in start_with_param: {e}")
                await event.respond("An error occurred while processing your request.")
    
        else:
            try:
                start_pic_path = bot_settings.get("start_pic", None)
                if start_pic_path and os.path.exists(start_pic_path):
                    start_media = start_pic_path
                else:
                    import aiohttp
                    temp_pic_path = os.path.join(THUMBNAIL_DIR, "start_pic_temp.jpg")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(START_PIC_URL) as response:
                            if response.status == 200:
                                with open(temp_pic_path, 'wb') as f:
                                    f.write(await response.read())
                                start_media = temp_pic_path
                            else:
                                logger.error(f"Failed to download start picture: {response.status}")
                                raise Exception("Failed to download start picture")
    
                caption_text=(
                    f"<blockquote><b>🍁 Hᴇʏ, {mention}!</b></blockquote>\n"
                    f"<blockquote><b><i>I'ᴍ ᴀ ᴀᴜᴛᴏ ᴀɴɪᴍᴇ ʙᴏᴛ. ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴏɴɢᴏɪɴɢ ᴀɴᴅ ғɪɴɪsʜᴇᴅ ᴀɴɪᴍᴇ ғʀᴏᴍ ᴀɴɪᴍᴇᴘᴀʜᴇ.ʀᴜ ᴀɴᴅ ᴜᴘʟᴏᴀᴅ ᴛʜᴏsᴇ ғɪʟᴇs ᴏɴ ʏᴏᴜʀ ᴄʜᴀɴᴇʟ ᴅɪʀᴇᴄᴛʟʏ...</i></b>\n</blockquote>"
                    f"<blockquote><b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ - <a href='https://t.me/{chnl_user}'>{chnl_name}</a></blockquote></b>"
                )
                
                if is_admin(event.chat_id):
                        buttons = [
                            [Button.inline("𝗔𝘂𝘁𝗼 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", b"auto_settings"), Button.inline("𝗛𝗲𝗹𝗽", b"show_help")],
                        ]
                else:
                    buttons = [
                        [Button.url("𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", "https://t.me/KamiKaito"),
                         Button.url("𝗠𝗮𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/GenAnimeOngoing")],
                        [Button.url("𝗕𝗮𝗰𝗸𝘂𝗽 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/OngoingAnimeBackup")]
                    ]
    
                try:
                    await event.client.send_file(
                        event.chat_id,
                        start_media,
                        caption=caption_text,
                        parse_mode='HTML',
                        buttons=buttons,
                        link_preview=False
                    )
                except Exception as photo_error:
                    logger.error(f"Primary send_file failed: {photo_error}")
                    raise
            except Exception as e:
                logger.error(f"Error sending start message with media: {e}")
                try:
                    if is_admin(event.chat_id):
                        buttons = [
                            [Button.inline("𝗔𝘂𝘁𝗼 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", b"auto_settings"), Button.inline("𝗛𝗲𝗹𝗽", b"show_help")],
                        ]
                    else:
                        buttons = [
                            [Button.url("𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", "https://t.me/KamiKaito"),
                            Button.url("𝗠𝗮𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/GenAnimeOngoing")],
                            [Button.url("𝗕𝗮𝗰𝗸𝘂𝗽 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/OngoingAnimeBackup")]
                        ]
                    await safe_respond(event, f"<blockquote><b>🍁 Hᴇʏ, {mention}!</b></blockquote>\n<blockquote><b><i>I'ᴍ ᴀ ᴀᴜᴛᴏ ᴀɴɪᴍᴇ ʙᴏᴛ. ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴏɴɢᴏɪɴɢ ᴀɴᴅ ғɪɴɪsʜᴇᴅ ᴀɴɪᴍᴇ ғʀᴏᴍ ᴀɴɪᴍᴇᴘᴀʜᴇ.ʀᴜ ᴀɴᴅ ᴜᴘʟᴏᴀᴅ ᴛʜᴏsᴇ ғɪʟᴇs ᴏɴ ʏᴏᴜʀ ᴄʜᴀɴᴇʟ ᴅɪʀᴇᴄᴛʟʏ...</i></b>\n<blockquote><b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ - <a href='https://t.me/{chnl_user}'>{chnl_name}</a></blockquote></b>", buttons=buttons, parse_mode='html')
                except Exception as e2:
                    logger.error(f"Error sending fallback message: {e2}")
                    await event.respond(f"Error: {e2}")


    @client.on(events.NewMessage(pattern='/cancel'))
    async def cancel(event):
        if not is_admin(event.chat_id):
            return
        await safe_respond(event, "<blockquote><b>ᴏᴘᴇʀᴀᴛɪᴏɴ ᴄᴀɴᴄᴇʟʟᴇᴅ. sᴇɴᴅ /sᴛᴀʀᴛ ᴛᴏ ʙᴇɢɪɴ ᴀɢᴀɪɴ.</b></blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/add_admin'))
    async def add_admin_command(event):
        if not is_admin(event.chat_id):
            return
        
        if event.chat_id != ADMIN_CHAT_ID:
            await safe_respond(event, "<blockquote><b>ᴏᴡɴᴇʀ ᴏɴʟʏ!</b></blockquote>", parse_mode='html')
            return
        
        parts = event.text.split()
        if len(parts) < 2:
            await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴜsᴇʀ ID ᴛᴏ ᴀᴅᴅ ᴀs ᴀᴅᴍɪɴ.</b>\n\n<b>ᴜsᴀɢᴇ::</b> <code>/add_admin [user_id]</code></blockquote>", parse_mode='html')
            return
        
        try:
            user_id = int(parts[1])
            
            try:
                user = await client.get_entity(user_id)
                username = user.username if hasattr(user, 'username') else None
                name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
            except:
                username = None
                name = f"ᴜsᴇʀ {user_id}"
            
            if add_admin(user_id, username):
                await safe_respond(event, f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ ᴀᴅᴅᴇᴅ</b> <i>{name}</i> <b>ᴀs ᴀᴅᴍɪɴ.</b></blockquote>", parse_mode='html')
            else:
                await safe_respond(event, f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴀᴅᴅ</b> <i>{name}</i> <b>ᴀs ᴀᴅᴍɪɴ.</b></blockquote>", parse_mode='html')
        except ValueError:
            await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ᴜsᴇʀ ID.</b>\n<b>ᴜsᴀɢᴇ:</b> <code>/add_admin [user_id]</code></blockquote>", parse_mode='html')
        except Exception as e:
            logger.error(f"Error adding admin: {e}")
            await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ ᴀᴅᴅɪɴɢ ᴀᴅᴍɪɴ:</b> {str(e)}</blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/remove_admin'))
    async def remove_admin_command(event):
        if not is_admin(event.chat_id):
            return
        
        if event.chat_id != ADMIN_CHAT_ID:
            await safe_respond(event, "<blockquote><b>ᴏᴡɴᴇʀ ᴏɴʟʏ!</b></blockquote>", parse_mode='html')
            return
        
        parts = event.text.split()
        if len(parts) < 2:
            await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴜsᴇʀ ID ᴛᴏ ʀᴇᴍᴏᴠᴇ ғʀᴏᴍ ᴀᴅᴍɪɴ.</b>\n\n<b>ᴜsᴀɢᴇ:</b> <code>/remove_admin [user_id]</code></blockquote>", parse_mode='html')
            return
        
        try:
            user_id = int(parts[1])
            
            try:
                user = await client.get_entity(user_id)
                username = user.username if hasattr(user, 'username') else None
                name = f"{user.first_name} {user.last_name}" if user.last_name else user.first_name
            except:
                username = None
                name = f"ᴜsᴇʀ {user_id}"
            
            if remove_admin(user_id):
                await safe_respond(event, f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ ʀᴇᴍᴏᴠᴇᴅ</b> <i>{name}</i> <b>ғʀᴏᴍ ᴀᴅᴍɪɴ.</b></blockquote>", parse_mode='html')
            else:
                await safe_respond(event, f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ʀᴇᴍᴏᴠᴇ</b> <i>{name}</i> <b>ғʀᴏᴍ ᴀᴅᴍɪɴ.</b></blockquote>", parse_mode='html')
        except ValueError:
            await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ᴜsᴇʀ ID.</b>\n\n<b>ᴜsᴀɢᴇ:</b> <code>/remove_admin [user_id]</code></blockquote>", parse_mode='html')
        except Exception as e:
            logger.error(f"Error removing admin: {e}")
            await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ ʀᴇᴍᴏᴠɪɴɢ ᴀᴅᴍɪɴ:</b>  {str(e)}</blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/del_timer'))
    async def del_timer_command(event):
        if not is_admin(event.chat_id):
            return
        
        parts = event.text.split()
        if len(parts) == 1:
            current_timer = bot_settings.get("file_delete_timer", 600)
            await safe_respond(event, f"<blockquote><b>ᴄᴜʀʀᴇɴᴛ ғɪʟᴇ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇʀ: {current_timer} sᴇᴄᴏɴᴅs ({current_timer/60:.1f} ᴍɪɴᴜᴛᴇs)</b></blockquote>", parse_mode='html')
        else:
            try:
                seconds = int(parts[1])
                if seconds < 60:
                    await safe_respond(event, "<blockquote><b>ᴛɪᴍᴇʀ ᴍᴜsᴛ ʙᴇ ᴀᴛ ʟᴇᴀsᴛ 60 sᴇᴄᴏɴᴅs.</b></blockquote>", parse_mode='html')
                    return
                bot_settings.set("file_delete_timer", seconds)
                await safe_respond(event, f"<blockquote><b>ғɪʟᴇ ᴅᴇʟᴇᴛᴇ ᴛɪᴍᴇʀ sᴇᴛ ᴛᴏ {seconds} sᴇᴄᴏɴᴅs ({seconds/60:.1f} ᴍɪɴᴜᴛᴇs).</b></blockquote>", parse_mode='html')
            except ValueError:
                await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b></blockquote>", parse_mode='html')



    

    @client.on(events.NewMessage(pattern='/latest'))
    async def latest_command(event):
        if not is_admin(event.chat_id):
            return
        
        try:
            status_msg = await safe_respond(event, "<blockquote><b>ғᴇᴛᴄʜɪɴɢ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ʟɪsᴛ...</blockquote></b>", parse_mode='html')
            
            API_URL = "https://animepahe.si/api?m=airing&page=1"
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, headers=HEADERS) as response:
                    if response.status == 200:
                        data = await response.json()
                        anime_list = data.get('data', [])
                        
                        if not anime_list:
                            await status_msg.edit("<blockquote><b>ɴᴏ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴛ ᴛʜᴇ ᴍᴏᴍᴇɴᴛ.</b></blockquote>", parse_mode='html')
                            return
                        
                        latest_anime_text = "<blockquote><b>Lᴀᴛᴇsᴛ Aɪʀɪɴɢ Aɴɪᴍᴇ:</b></blockquote>\n"
                        for idx, anime in enumerate(anime_list[:10], start=1):
                            title = anime.get('anime_title', 'Unknown Title')
                            anime_session = anime.get('anime_session', '')
                            episode = anime.get('episode', 'N/A')
                            link = f"https://animepahe.si/anime/{anime_session}" if anime_session else "#"
                            
                            latest_anime_text += f"<blockquote><b>{idx}. <a href='{link}'>{title}</a> [E{episode}]</b></blockquote>\n"
                        
                        await status_msg.edit(latest_anime_text, parse_mode='html', link_preview=False)
                    else:
                        await status_msg.edit(f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ғᴇᴛᴄʜ ᴅᴀᴛᴀ.</b> <i>sᴛᴀᴛᴜs ᴄᴏᴅᴇ: {response.status}</i></blockquote>", parse_mode='html')
        
        except Exception as e:
            logger.error(f"Error in latest_command: {e}")
            await safe_respond(event, "<blockquote><b>sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ.</b></blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/airing'))
    async def airing_command(event):
        if not is_admin(event.chat_id):
            return
        
        try:
            status_msg = await safe_respond(event, "<blockquote><b>ғᴇᴛᴄʜɪɴɢ ᴀɪʀɪɴɢ ᴀɴɪᴍᴇ ʟɪsᴛ...</blockquote></b>", parse_mode='html')
            
            API_URL = "https://animepahe.si/anime/airing"
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL, headers=HEADERS) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, "html.parser")
                        anime_list = soup.select(".index-wrapper .index a")
                        
                        if not anime_list:
                            await status_msg.edit("<blockquote><b>ɴᴏ ᴀɪʀɪɴɢ ᴀɴɪᴍᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴛ ᴛʜᴇ ᴍᴏᴍᴇɴᴛ.</b></blockquote>", parse_mode='html')
                            return
                        
                        airing_anime_text = "<blockquote><b>Cᴜʀʀᴇɴᴛʟʏ Aɪʀɪɴɢ Aɴɪᴍᴇ:</b></blockquote>\n"
                        for idx, anime in enumerate(anime_list[:15], start=1):
                            title = anime.get("title", "Unknown Title")
                            href = anime.get("href", "")
                            
                            if href:
                                link = f"https://animepahe.si{href}"
                                airing_anime_text += f"<blockquote><b>{idx}. <a href='{link}'>{title}</a></b></blockquote>\n"
                            else:
                                airing_anime_text += f"<blockquote><b>{idx}. {title}</b></blockquote>\n"
                        
                        await status_msg.edit(airing_anime_text, parse_mode='html', link_preview=False)
                    else:
                        await status_msg.edit(f"<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ғᴇᴛᴄʜ ᴅᴀᴛᴀ.</b> <i>sᴛᴀᴛᴜs ᴄᴏᴅᴇ: {response.status}</i></blockquote>", parse_mode='html')
        
        except Exception as e:
            logger.error(f"Error in airing_command: {e}")
            await safe_respond(event, "<blockquote><b>sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ.</b></blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/addtask'))
    async def add_task(event):
        if not is_admin(event.chat_id):
            return
        
        parts = event.text.split()
        if len(parts) < 2:
            try:
                status_msg = await safe_respond(event, "<blockquote><b>ғᴇᴛᴄʜɪɴɢ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ʟɪsᴛ...</blockquote></b>", parse_mode='html')
                
                API_URL = "https://animepahe.si/api?m=airing&page=1"
                async with aiohttp.ClientSession() as session:
                    async with session.get(API_URL, headers=HEADERS) as response:
                        if response.status == 200:
                            data = await response.json()
                            anime_list = data.get('data', [])
                            
                            if not anime_list:
                                await status_msg.edit("<blockquote><b>ɴᴏ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴛ ᴛʜᴇ ᴍᴏᴍᴇɴᴛ.</b></blockquote>", parse_mode='html')
                                return
                            
                            latest_anime_text = "<blockquote><b>Lᴀᴛᴇsᴛ Aɪʀɪɴɢ Aɴɪᴍᴇ:</b></blockquote>\n"
                            for idx, anime in enumerate(anime_list[:10], start=1):
                                title = anime.get('anime_title', 'Unknown Title')
                                episode = anime.get('episode', 'N/A')
                                latest_anime_text += f"<blockquote><b>{idx}. {title} [E{episode}]</b></blockquote>\n"
                            
                            latest_anime_text += "\n<b><blockquote>ᴜsᴇ /redownload [number] ᴛᴏ ғᴏʀᴄᴇ ʀᴇᴅᴏᴡɴʟᴏᴀᴅ ᴀ sᴘᴇᴄɪғɪᴄ ᴀɴɪᴍᴇ.</b></blockquote>"
                            await status_msg.edit(latest_anime_text, parse_mode='html', link_preview=False)
                        else:
                            await status_msg.edit(f"<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ғᴇᴛᴄʜ ᴅᴀᴛᴀ.\nsᴛᴀᴛᴜs ᴄᴏᴅᴇ: {response.status}</b></blockquote>", parse_mode='html')
            except Exception as e:
                logger.error(f"Error in redownload: {e}")
                await status_msg.edit("<blockquote><b>sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ.</b></blockquote>", parse_mode='html')
            return
        
        try:
            index = int(parts[1])
            if index < 1:
                status_msg = await safe_respond(event, "<blockquote><b>ᴀᴅᴅɪɴɢ ᴛᴀsᴋ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴɪᴍᴇ ᴀᴛ ɪɴᴅᴇx {index}...</b></blockquote>", parse_mode='html')
                await status_msg.edit("<blockquote><b>ɪɴᴅᴇx ᴍᴜsᴛ ʙᴇ ᴀ ᴘᴏsɪᴛɪᴠᴇ ɴᴜᴍʙᴇʀ.</b></blockquote>", parse_mode='html')
                return
            
            status_msg = await safe_respond(event, f"<blockquote><b>ᴀᴅᴅɪɴɢ ᴛᴀsᴋ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ᴀɴɪᴍᴇ ᴀᴛ ɪɴᴅᴇx {index}...</b></blockquote>", parse_mode='html')
            success = await download_anime_by_index(event, index)
        except ValueError:
            status_msg = await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b></blockquote>", parse_mode='html')
        except Exception as e:
            logger.error(f"Error in add_task: {e}")
            status_msg = await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ: </b> {str(e)}</blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/redownload'))
    async def redownload(event):
        if not is_admin(event.chat_id):
            return
    
        parts = event.text.split()
        if len(parts) < 2:
            try:
                status_msg = await safe_respond(event, "<blockquote><b>ғᴇᴛᴄʜɪɴɢ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ʟɪsᴛ...</blockquote></b>", parse_mode='html')
                
                API_URL = "https://animepahe.si/api?m=airing&page=1"
                async with aiohttp.ClientSession() as session:
                    async with session.get(API_URL, headers=HEADERS) as response:
                        if response.status == 200:
                            data = await response.json()
                            anime_list = data.get('data', [])
                            
                            if not anime_list:
                                await status_msg.edit("<blockquote><b>ɴᴏ ʟᴀᴛᴇsᴛ ᴀɴɪᴍᴇ ᴀᴠᴀɪʟᴀʙʟᴇ ᴀᴛ ᴛʜᴇ ᴍᴏᴍᴇɴᴛ.</b></blockquote>", parse_mode='html')
                                return
                            
                            latest_anime_text = "<blockquote><b>Lᴀᴛᴇsᴛ Aɪʀɪɴɢ Aɴɪᴍᴇ:</b></blockquote>\n"
                            for idx, anime in enumerate(anime_list[:10], start=1):
                                title = anime.get('anime_title', 'Unknown Title')
                                episode = anime.get('episode', 'N/A')
                                latest_anime_text += f"<blockquote><b>{idx}. {title} [E{episode}]</b></blockquote>\n"
                            
                            latest_anime_text += "\n<b><blockquote>ᴜsᴇ /redownload [number] ᴛᴏ ғᴏʀᴄᴇ ʀᴇᴅᴏᴡɴʟᴏᴀᴅ ᴀ sᴘᴇᴄɪғɪᴄ ᴀɴɪᴍᴇ.</b></blockquote>"
                            await status_msg.edit(latest_anime_text, parse_mode='html', link_preview=False)
                        else:
                            await status_msg.edit(f"<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ғᴇᴛᴄʜ ᴅᴀᴛᴀ.\nsᴛᴀᴛᴜs ᴄᴏᴅᴇ: {response.status}</b></blockquote>", parse_mode='html')
            except Exception as e:
                logger.error(f"Error in redownload: {e}")
                await status_msg.edit("<blockquote><b>sᴏᴍᴇᴛʜɪɴɢ ᴡᴇɴᴛ ᴡʀᴏɴɢ.</b></blockquote>", parse_mode='html')
            return
    
        try:
            index = int(parts[1])
            if index < 1:
                status_msg = await safe_respond(event, "<blockquote><b>ᴀᴅᴅɪɴɢ ᴛᴀsᴋ ᴛᴏ ʀᴇᴅᴏᴡɴʟᴏᴀᴅ ᴀɴɪᴍᴇ ᴀᴛ ɪɴᴅᴇx {index}...</b></blockquote>", parse_mode='html')
                await status_msg.edit("<blockquote><b>ɪɴᴅᴇx ᴍᴜsᴛ ʙᴇ ᴀ ᴘᴏsɪᴛɪᴠᴇ ɴᴜᴍʙᴇʀ.</b></blockquote>", parse_mode='html')
                return
            
            status_msg = await safe_respond(event, f"<blockquote><b>ᴀᴅᴅɪɴɢ ᴛᴀsᴋ ᴛᴏ ʀᴇᴅᴏᴡɴʟᴏᴀᴅ ᴀɴɪᴍᴇ ᴀᴛ ɪɴᴅᴇx {index}...</b></blockquote>", parse_mode='html')
            success = await download_anime_by_index(event, index, force_redownload=True)
        except ValueError:
            status_msg = await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</b></blockquote>", parse_mode='html')
        except Exception as e:
            logger.error(f"Error in redownload: {e}")
            status_msg = await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ: </b> {str(e)}</blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern=r'^/(addchnl|addchannel)(?:\s+(.+))?$'))
    async def add_anime_channel_handler(event):
        if not is_admin(event.chat_id):
            return
        
        from core.database import add_anime_channel
        
        text = event.pattern_match.group(2)
        if not text:
            await safe_respond(
                event, 
                "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴄʜᴀɴɴᴇʟ ID ᴀɴᴅ ᴀɴɪᴍᴇ ɴᴀᴍᴇ.</b><blockquote>\n"
                "<blockquote><b>ᴜsᴀɢᴇ:</b> <code>/addchnl [channel_id_or_username] [anime_name]</code><blockquote>\n"
                "<blockquote><b>ᴇxᴀᴍᴘʟᴇ:</b> <code>/addchnl -1001234567890 Chitose Is in the Ramune Bottle</code><blockquote>",
                parse_mode='html'
            )
            return
        
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await safe_respond(
                event, 
                "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ʙᴏᴛʜ ᴄʜᴀɴɴᴇʟ ID ᴀɴᴅ ᴀɴɪᴍᴇ ɴᴀᴍᴇ.</b></blockquote>\n"
                "<blockquote><b>ᴜsᴀɢᴇ:</b> <code>/addchnl [channel_id_or_username] [anime_name]</code></blockquote>",
                parse_mode='html'
            )
            return
        
        channel_input = parts[0].strip()
        anime_name = parts[1].strip()
        
        try:
            try:
                channel_id_int = int(channel_input)
                channel = await client.get_entity(channel_id_int)
            except ValueError:
                channel = await client.get_entity(channel_input)
            
            if not hasattr(channel, 'id'):
                await safe_respond(event, "<b><blockquote>ɪɴᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ. ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ᴄʜᴀɴɴᴇʟ ID ᴏʀ ᴜsᴇʀɴᴀᴍᴇ.</blockquote></b>", parse_mode='html')
                return
            
            if not isinstance(channel, types.Channel):
                await safe_respond(
                    event,
                    "<b><blockquote>ᴛʜɪs ɪs ɴᴏᴛ ᴀ ᴄʜᴀɴɴᴇʟ.</blockquote></b>",
                    parse_mode='html'
                )
                return

            full_channel_id = int(f"-100{channel.id}")
            channel_username = getattr(channel, 'username', None)
            
            success = await add_anime_channel(anime_name, full_channel_id, channel_username)
            
            if success:
                channel_mention = f"@{channel_username}" if channel_username else f"<code>{full_channel_id}</code>"
                await safe_respond(
                    event,
                    f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ sᴇᴛ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟ!</b></blockquote>\n"
                    f"<blockquote><b>ᴀɴɪᴍᴇ:</b> {anime_name}\n"
                    f"<b>ᴄʜᴀɴɴᴇʟ:</b> {channel_mention}</blockquote>",
                    parse_mode='html'
                )
                logger.info(f"Added anime channel: {anime_name} -> {full_channel_id}")
            else:
                await safe_respond(event, "<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ᴀᴅᴅ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟ.</blockquote></b>", parse_mode='html')
        
        except Exception as e:
            logger.error(f"Error adding anime channel: {e}")
            await safe_respond(
                event, 
                f"<blockquote><b>ᴇʀʀᴏʀ:</b> {str(e)}</blockquote>\n"
                "<blockquote><b>ᴍᴀᴋᴇ sᴜʀᴇ ᴛʜᴇ ʙᴏᴛ ɪs ᴀ ᴍᴇᴍʙᴇʀ ᴏғ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ᴀɴᴅ ʜᴀs ᴘᴇʀᴍɪssɪᴏɴs ᴛᴏ ᴘᴏsᴛ.</b></blockquote>",
                parse_mode='html'
            )

    @client.on(events.NewMessage(pattern=r'^/removechnl(?:\s+(.+))?$'))
    async def remove_anime_channel_handler(event):
        if not is_admin(event.chat_id):
            return
        
        from core.database import remove_anime_channel
        
        anime_name = event.pattern_match.group(1)
        if not anime_name:
            await safe_respond(
                event,
                "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀɴɪᴍᴇ ɴᴀᴍᴇ.</b>\n"
                "<b>ᴜsᴀɢᴇ:</b> <code>/removechnl [anime_name]</code></blockquote>",
                parse_mode='html'
            )
            return
        
        try:
            success = await remove_anime_channel(anime_name)
            
            if success:
                await safe_respond(
                    event,
                    f"<blockquote><b>sᴜᴄᴄᴇssғᴜʟʟʏ ʀᴇᴍᴏᴠᴇᴅ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟ!</b>\n"
                    f"<b>ᴀɴɪᴍᴇ: {anime_name}</b></blockquote>",
                    parse_mode='html'
                )
                logger.info(f"Removed anime channel: {anime_name}")
            else:
                await safe_respond(
                    event,
                    f"<blockquote><b>ᴀɴɪᴍᴇ ɴᴏᴛ ғᴏᴜɴᴅ ɪɴ ᴄʜᴀɴɴᴇʟ ʟɪsᴛ: {anime_name}</b></blockquote>",
                    parse_mode='html'
                )
        except Exception as e:
            logger.error(f"Error removing anime channel: {e}")
            await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> {str(e)}</blockquote>", parse_mode='html')

    @client.on(events.NewMessage(pattern='/listchnl'))
    async def list_anime_channels_handler(event):
        if not is_admin(event.chat_id):
            return
        
        from core.database import get_all_anime_channels
        
        try:
            channels = await get_all_anime_channels()
            
            if not channels:
                await safe_respond(
                    event,
                    "<blockquote><b>ɴᴏ ᴀɴɪᴍᴇ ᴄʜᴀɴɴᴇʟs ᴄᴏɴғɪɢᴜʀᴇᴅ ʏᴇᴛ.</b></blockquote>\n"
                    "<blockquote><b>ᴜsᴇ</b> <code>/addchnl [channel_id] [anime_name]</code> <b>ᴛᴏ ᴀᴅᴅ ᴏɴᴇ.</b></blockquote>",
                    parse_mode='html'
                )
                return
            
            response = "<b><blockquote>Cᴏɴғɪɢᴜʀᴇᴅ Aɴɪᴍᴇ Cʜᴀɴɴᴇʟs:</blockquote></b>\n"
            for i, item in enumerate(channels, 1):
                anime = item.get('anime_title', 'Unknown')
                ch_id = item.get('channel_id', 'N/A')
                ch_username = item.get('channel_username', 'N/A')
                ch_mention = f"<blockquote>@{ch_username}</blockquote>" if ch_username and ch_username != 'N/A' else f"</blockquote><code>{ch_id}</code><blockquote>"
                response += f"<blockquote><b>{i}.</b> <i>{anime}</i>\n   ➜ {ch_mention}\n</blockquote>"
            
            response += "\n<blockquote><b>Usᴇ</b> <code>/removechnl [anime_name]</code> <b>ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴀ ᴄʜᴀɴɴᴇʟ.</blockquote></b>"
            
            await safe_respond(event, response, parse_mode='html')
        except Exception as e:
            logger.error(f"Error listing anime channels: {e}")
            await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> {str(e)}</blockquote>", parse_mode='html')

    @client.on(events.CallbackQuery(data=b"close_menu"))
    async def close_menu_callback(event):
        await event.delete()

    @client.on(events.CallbackQuery(data=b"show_help"))
    async def show_help_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        buttons = [
            [Button.inline("𝗕𝗮𝗰𝗸", b"back_to_main")]
        ]

        help_text = HELP_TEXT
        
        await safe_edit(event, help_text, buttons=buttons, parse_mode='html')

    @client.on(events.CallbackQuery(data=b"auto_settings"))
    async def auto_settings_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')
        enabled = auto_download_state.enabled
        interval = auto_download_state.interval
        last_checked = auto_download_state.last_checked
        
        status_text = (
            "<blockquote><b>✦ 𝗔𝗨𝗧𝗢 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦: ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Sᴛᴀᴛᴜs: {'Eɴᴀʙʟᴇᴅ' if enabled else 'Dɪsᴀʙʟᴇᴅ'}\n"
            f"・ Cʜᴇᴄᴋ Iɴᴛᴇʀᴠᴀʟ: {interval} Sᴇᴄᴏɴᴅs\n"
            f"・ Lᴀsᴛ Cʜᴇᴄᴋᴇᴅ: {last_checked or 'Nᴇᴠᴇʀ'}</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>"
        )
        
        if enabled:
            btn1 = Button.inline("𝗗𝗶𝘀𝗮𝗯𝗹𝗲 𝗔𝘂𝘁𝗼 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱", b"auto_disable")
        else:
            btn1 = Button.inline("𝗘𝗻𝗮𝗯𝗹𝗲 𝗔𝘂𝘁𝗼 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱", b"auto_enable")
        
        buttons = [
            [btn1, Button.inline("𝗖𝗵𝗲𝗰𝗸 𝗡𝗼𝘄", b"auto_check_now")],
            [Button.inline("𝗤𝘂𝗮𝗹𝗶𝘁𝘆 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", b"quality_settings")],
            [Button.inline("𝗖𝗵𝗮𝗻𝗴𝗲 𝗜𝗻𝘁𝗲𝗿𝘃𝗮𝗹", b"auto_interval"), Button.inline("𝗕𝗮𝗰𝗸", b"back_to_main")]
        ]
        
        await safe_edit(event, status_text, buttons=buttons, parse_mode='html')

    @client.on(events.CallbackQuery(data=b"auto_enable"))
    async def auto_enable_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        auto_download_state.enabled = True
        await safe_edit(event, 
            "<b><blockquote>ᴀᴜᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ʜᴀs ʙᴇᴇɴ ᴇɴᴀʙʟᴇᴅ.</b></blockquote>", 
            buttons=[[Button.inline("𝗕𝗮𝗰𝗸", b"auto_settings")]], 
            parse_mode='html'
        )

    @client.on(events.CallbackQuery(data=b"auto_disable"))
    async def auto_disable_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        auto_download_state.enabled = False
        await safe_edit(event, 
            "<b><blockquote>ᴀᴜᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ ʜᴀs ʙᴇᴇɴ ᴅɪsᴀʙʟᴇᴅ.</blockquote></b>", 
            buttons=[[Button.inline("𝗕𝗮𝗰𝗸", b"auto_settings")]], 
            parse_mode='html'
        )

    @client.on(events.CallbackQuery(data=b"auto_check_now"))
    async def auto_check_now_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        await safe_edit(event, "<b><blockquote>ᴄʜᴇᴄᴋɪɴɢ ғᴏʀ ɴᴇᴡ ᴇᴘɪsᴏᴅᴇs...</blockquote></b>", parse_mode='html')
        
        asyncio.create_task(check_for_new_episodes(client))
        
        await asyncio.sleep(10)
        await safe_edit(event, 
            "<b><blockquote>ᴄʜᴇᴄᴋ ɪɴɪᴛɪᴀᴛᴇᴅ.</b></blockquote>", 
            buttons=[[Button.inline("𝗕𝗮𝗰𝗸", b"auto_settings")]], 
            parse_mode='html'
        )

    @client.on(events.CallbackQuery(data=b"auto_interval"))
    async def auto_interval_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        current_interval = auto_download_state.interval
        await safe_edit(event, 
            f"<b><blockquote>ᴄᴜʀʀᴇɴᴛ ᴄʜᴇᴄᴋ ɪɴᴛᴇʀᴠᴀʟ: {current_interval} sᴇᴄᴏɴᴅs\n"
            "ᴘʟᴇᴀsᴇ sᴇɴᴅ ᴍᴇ ᴛʜᴇ ɴᴇᴡ ɪɴᴛᴇʀᴠᴀʟ ɪɴ sᴇᴄᴏɴᴅs (60-86400):</b></blockquote>",
            parse_mode='html',
            buttons=[[Button.inline("𝗕𝗮𝗰𝗸", b"auto_settings")]]
        )
        
        if event.chat_id not in user_states:
            user_states[event.chat_id] = UserState()
        
        user_states[event.chat_id]._waiting_for_interval = True

    @client.on(events.CallbackQuery(data=b"back_to_main"))
    async def back_to_main_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        user_id = event.sender_id
    
        user = await event.get_sender()
        mention = f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"
        
        try:
            start_pic_path = bot_settings.get("start_pic", None)
            if start_pic_path and os.path.exists(start_pic_path):
                start_media = start_pic_path
            else:
                import aiohttp
                temp_pic_path = os.path.join(THUMBNAIL_DIR, "start_pic_temp.jpg")
                async with aiohttp.ClientSession() as session:
                    async with session.get(START_PIC_URL) as response:
                        if response.status == 200:
                            with open(temp_pic_path, 'wb') as f:
                                f.write(await response.read())
                            start_media = temp_pic_path
                        else:
                            logger.error(f"Failed to download start picture: {response.status}")
                            raise Exception("Failed to download start picture")
            chnl_name=CHANNEL_NAME
            chnl_user = CHANNEL_USERNAME.lstrip("@")


            caption_text=(
                   f"<blockquote><b>🍁 Hᴇʏ, {mention}!</b></blockquote>\n"
                   f"<blockquote><b><i>I'ᴍ ᴀ ᴀᴜᴛᴏ ᴀɴɪᴍᴇ ʙᴏᴛ. ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴏɴɢᴏɪɴɢ ᴀɴᴅ ғɪɴɪsʜᴇᴅ ᴀɴɪᴍᴇ ғʀᴏᴍ ᴀɴɪᴍᴇᴘᴀʜᴇ.ʀᴜ ᴀɴᴅ ᴜᴘʟᴏᴀᴅ ᴛʜᴏsᴇ ғɪʟᴇs ᴏɴ ʏᴏᴜʀ ᴄʜᴀɴᴇʟ ᴅɪʀᴇᴄᴛʟʏ...</i></b>\n</blockquote>"
                   f"<blockquote><b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ - <a href='https://t.me/{chnl_user}'>{chnl_user}</a></blockquote></b>"
            )
            
            if is_admin(event.chat_id):
                    buttons = [
                        [Button.inline("𝗔𝘂𝘁𝗼 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", b"auto_settings"), Button.inline("𝗛𝗲𝗹𝗽", b"show_help")],
                    ]
            else:
                buttons = [
                    [Button.url("𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", "https://t.me/KamiKaito"),
                     Button.url("𝗠𝗮𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/GenAnimeOngoing")],
                    [Button.url("𝗕𝗮𝗰𝗸𝘂𝗽 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/OngoingAnimeBackup")]
                ]

            try:
                await safe_edit(
                    event.chat_id,
                    event,
                    f"<blockquote><b>🍁 Hᴇʏ, {mention}!</b></blockquote>\n"
                    f"<blockquote><b><i>I'ᴍ ᴀ ᴀᴜᴛᴏ ᴀɴɪᴍᴇ ʙᴏᴛ. ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴏɴɢᴏɪɴɢ ᴀɴᴅ ғɪɴɪsʜᴇᴅ ᴀɴɪᴍᴇ ғʀᴏᴍ ᴀɴɪᴍᴇᴘᴀʜᴇ.ʀᴜ ᴀɴᴅ ᴜᴘʟᴏᴀᴅ ᴛʜᴏsᴇ ғɪʟᴇs ᴏɴ ʏᴏᴜʀ ᴄʜᴀɴᴇʟ ᴅɪʀᴇᴄᴛʟʏ...</i></b></blockquote>"
                    f"<blockquote><b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ - "
                    f"<a href='https://t.me/{CHANNEL_USERNAME.lstrip('@')}'>{CHANNEL_NAME}</a>"
                    f"</b></blockquote>",
                    parse_mode='HTML',
                    buttons=buttons,
                    link_preview=False
                )
            except Exception as photo_error:
                logger.error(f"Primary send_file failed: {photo_error}")
                raise
        except Exception as e:
            logger.error(f"Error sending start message with media: {e}")
            try:
                if is_admin(event.chat_id):
                    buttons = [
                        [Button.inline("𝗔𝘂𝘁𝗼 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗦𝗲𝘁𝘁𝗶𝗻𝗴𝘀", b"auto_settings"), Button.inline("𝗛𝗲𝗹𝗽", b"show_help")],
                    ]
                else:
                    buttons = [
                        [Button.url("𝗗𝗲𝘃𝗲𝗹𝗼𝗽𝗲𝗿", "https://t.me/KamiKaito"),
                        Button.url("𝗠𝗮𝗶𝗻 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/GenAnimeOngoing")],
                        [Button.url("𝗕𝗮𝗰𝗸𝘂𝗽 𝗖𝗵𝗮𝗻𝗻𝗲𝗹", "https://t.me/OngoingAnimeBackup")]
                    ]
                await safe_edit(
                    event,
                    f"<blockquote><b>🍁 Hᴇʏ, {mention}!</b></blockquote>\n"
                    f"<blockquote><b><i>I'ᴍ ᴀ ᴀᴜᴛᴏ ᴀɴɪᴍᴇ ʙᴏᴛ. ɪ ᴄᴀɴ ᴅᴏᴡɴʟᴏᴀᴅ ᴏɴɢᴏɪɴɢ ᴀɴᴅ ғɪɴɪsʜᴇᴅ ᴀɴɪᴍᴇ ғʀᴏᴍ ᴀɴɪᴍᴇᴘᴀʜᴇ.ʀᴜ ᴀɴᴅ ᴜᴘʟᴏᴀᴅ ᴛʜᴏsᴇ ғɪʟᴇs ᴏɴ ʏᴏᴜʀ ᴄʜᴀɴᴇʟ ᴅɪʀᴇᴄᴛʟʏ...</i></b></blockquote>"
                    f"<blockquote><b>ᴘᴏᴡᴇʀᴇᴅ ʙʏ - "
                    f"<a href='https://t.me/{CHANNEL_USERNAME.lstrip('@')}'>{CHANNEL_NAME}</a>"
                    f"</b></blockquote>",
                    buttons=buttons,
                    parse_mode="html"
                )
            except Exception as e2:
                logger.error(f"Error sending fallback message: {e2}")
                await event.respond("Welcome! I'm an anime bot. Type /help for more info.")

    @client.on(events.CallbackQuery(data=b"toggle_360p"))
    async def toggle_360p_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        enabled_qualities = quality_settings.enabled_qualities
        if "360p" in enabled_qualities:
            enabled_qualities.remove("360p")
        else:
            enabled_qualities.append("360p")
        
        quality_settings.enabled_qualities = enabled_qualities
        await event.answer(f"𝟯𝟲𝟬𝗽 {'𝗲𝗻𝗮𝗯𝗹𝗲𝗱' if '360p' in enabled_qualities else '𝗱𝗶𝘀𝗮𝗯𝗹𝗲𝗱'}")

    @client.on(events.CallbackQuery(data=b"toggle_720p"))
    async def toggle_720p_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        enabled_qualities = quality_settings.enabled_qualities
        if "720p" in enabled_qualities:
            enabled_qualities.remove("720p")
        else:
            enabled_qualities.append("720p")
        
        quality_settings.enabled_qualities = enabled_qualities
        await event.answer(f"𝟳𝟮𝟬𝗽 {'𝗲𝗻𝗮𝗯𝗹𝗲𝗱' if '720p' in enabled_qualities else '𝗱𝗶𝘀𝗮𝗯𝗹𝗲𝗱'}")

    @client.on(events.CallbackQuery(data=b"toggle_1080p"))
    async def toggle_1080p_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        enabled_qualities = quality_settings.enabled_qualities
        if "1080p" in enabled_qualities:
            enabled_qualities.remove("1080p")
        else:
            enabled_qualities.append("1080p")
        
        quality_settings.enabled_qualities = enabled_qualities
        await event.answer(f"𝟭𝟬𝟴𝟬𝗽 {'𝗲𝗻𝗮𝗯𝗹𝗲𝗱' if '1080p' in enabled_qualities else '𝗱𝗶𝘀𝗮𝗯𝗹𝗲𝗱'}")

    @client.on(events.CallbackQuery(data=b"toggle_all"))
    async def toggle_all_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        quality_settings.download_all = not quality_settings.download_all
        await event.answer(f"𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗮𝗹𝗹 𝗲𝗻𝗮𝗯𝗹𝗲𝗱 𝗾𝘂𝗮𝗹𝗶𝘁𝗶𝗲𝘀 {'𝗲𝗻𝗮𝗯𝗹𝗲𝗱' if quality_settings.download_all else '𝗱𝗶𝘀𝗮𝗯𝗹𝗲𝗱'}")

    @client.on(events.CallbackQuery(data=b"toggle_batch"))
    async def toggle_batch_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        quality_settings.batch_mode = not quality_settings.batch_mode
        await event.answer(f"𝗕𝗮𝘁𝗰𝗵 𝗺𝗼𝗱𝗲 {'𝗲𝗻𝗮𝗯𝗹𝗲𝗱' if quality_settings.batch_mode else '𝗱𝗶𝘀𝗮𝗯𝗹𝗲𝗱'}")

    @client.on(events.CallbackQuery(data=b"quality_settings"))
    async def quality_settings_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        enabled_qualities = quality_settings.enabled_qualities
        download_all = quality_settings.download_all
        batch_mode = quality_settings.batch_mode
        
        buttons = []
        
        quality_buttons = []
        for quality in ["360p", "720p", "1080p"]:
            checked = "𝗼" if quality in enabled_qualities else "𝘅"
            quality_buttons.append(Button.inline(f"{checked} {quality}", f"toggle_{quality}"))
        
        if len(quality_buttons) == 3:
            buttons.append([quality_buttons[0], quality_buttons[1]])
            buttons.append([quality_buttons[2]])
        elif len(quality_buttons) == 2:
            buttons.append(quality_buttons)
        else:
            buttons.append([btn] for btn in quality_buttons)
        
        all_checked = "𝗼" if download_all else "𝘅"
        buttons.append([Button.inline(f"{all_checked} 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗔𝗹𝗹 𝗘𝗻𝗮𝗯𝗹𝗲𝗱 𝗤𝘂𝗮𝗹𝗶𝘁𝗶𝗲𝘀", b"toggle_all")])
        
        batch_checked = "𝗼" if batch_mode else "𝘅"
        buttons.append([Button.inline(f"{batch_checked} 𝗕𝗮𝘁𝗰𝗵 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱 𝗠𝗼𝗱𝗲", b"toggle_batch")])
        
        buttons.append([Button.inline("𝗕𝗮𝗰𝗸", b"auto_settings")])
        
        status_text = (
            "<b><blockquote>✦ 𝗤𝗨𝗔𝗟𝗜𝗧𝗬 𝗦𝗘𝗧𝗧𝗜𝗡𝗚𝗦 ✦</blockquote>\n"
            f"──────────────────\n"
            f"<blockquote>・ Cᴜʀʀᴇɴᴛ ᴇɴᴀʙʟᴇᴅ ǫᴜᴀʟɪᴛɪᴇs: {', '.join(enabled_qualities)}\n"
            f"・ Dᴏᴡɴʟᴏᴀᴅ ᴀʟʟ ᴇɴᴀʙʟᴇᴅ: {'Yᴇs' if download_all else 'Nᴏ'}\n"
            f"・ Bᴀᴛᴄʜ ᴅᴏᴡɴʟᴏᴀᴅ ᴍᴏᴅᴇ: {'Eɴᴀʙʟᴇᴅ' if batch_mode else 'Dɪsᴀʙʟᴇᴅ'}</blockquote>\n"
            f"──────────────────\n"
            "<blockquote>Sᴇʟᴇᴄᴛ ǫᴜᴀʟɪᴛɪᴇs ᴛᴏ ᴇɴᴀʙʟᴇ/ᴅɪsᴀʙʟᴇ:</blockquote></b>"
        )
        
        await safe_edit(event, status_text, buttons=buttons, parse_mode='html')

    @client.on(events.NewMessage)
    async def handle_message(event):
        if event.out:
            return

        if not isinstance(event.peer_id, PeerUser):
            return

        user_id = event.sender_id
        
        if not is_admin(event.chat_id):
            return
        
        if event.chat_id not in user_states:
            user_states[event.chat_id] = UserState()
        
        user_state = user_states[event.chat_id]
        
        if not event.text:
            return
        
        if event.text.startswith('/'):
            current_time = time.time()
            if current_time - user_state.last_command_time < 3:
                return
            user_state.last_command_time = current_time
            return
        
        if hasattr(user_state, '_waiting_for_interval') and user_state._waiting_for_interval:
            try:
                interval = int(event.text.strip())
                if interval < 60 or interval > 86400:
                    await safe_respond(event, "<b><blockquote>ɪɴᴛᴇʀᴠᴀʟ ᴍᴜsᴛ ʙᴇ ʙᴇᴛᴡᴇᴇɴ 60 ᴀɴᴅ 86400 sᴇᴄᴏɴᴅs (24 ʜᴏᴜʀs).</blockquote></b>", parse_mode='html')
                    return
                
                auto_download_state.interval = interval
                await safe_respond(event, 
                    f"<blockquote><b>ᴄʜᴇᴄᴋ ɪɴᴛᴇʀᴠᴀʟ sᴇᴛ ᴛᴏ {interval} sᴇᴄᴏɴᴅs.</b></blockquote>", 
                    buttons=[[Button.inline("𝗕𝗮𝗰𝗸", b"auto_settings")]], 
                    parse_mode='html'
                )
                user_state._waiting_for_interval = False
                return
            except ValueError:
                await safe_respond(event, "<b><blockquote>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ.</blockquote></b>", parse_mode='html')
                return
        
        query = event.text.strip()
        if not query:
            await safe_respond(event, "<b><blockquote>ᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴀɴ ᴀɴɪᴍᴇ ɴᴀᴍᴇ ᴛᴏ sᴇᴀʀᴄʜ.</blockquote></b>", parse_mode='html')
            return
        
        current_time = time.time()
        if hasattr(user_state, 'rate_limited_until') and current_time < user_state.rate_limited_until:
            return
        
        if current_time - user_state.last_command_time < 5:
            user_state.rate_limited_until = user_state.last_command_time + 5
            await safe_respond(event, "<b><blockquote>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ᴀ ᴍᴏᴍᴇɴᴛ ʙᴇғᴏʀᴇ sᴇᴀʀᴄʜɪɴɢ ᴀɢᴀɪɴ.</blockquote></b>", parse_mode='html')
            return
        
        user_state.last_command_time = current_time
        
        search_msg = await safe_respond(event, f"<blockquote><b>sᴇᴀʀᴄʜɪɴɢ ғᴏʀ: {query}...</b></blockquote>", parse_mode='html')
        
        try:
            anime_results = await search_anime(query)
            if not anime_results:
                await safe_edit(search_msg, "<b><blockquote>ᴀɴɪᴍᴇ ɴᴏᴛ ғᴏᴜɴᴅ.</blockquote></b>", parse_mode='html')
                return
        except Exception as e:
            logger.error(f"Error in anime search: {str(e)}")
            await safe_edit(search_msg, "<b><blockquote>ᴀɴ ᴇʀʀᴏʀ ᴏᴄᴄᴜʀʀᴇᴅ ᴡʜɪʟᴇ sᴇᴀʀᴄʜɪɴɢ.</blockquote></b>", parse_mode='html')
            return
        
        buttons = []
        for i, anime in enumerate(anime_results[:10]):
            buttons.append([Button.inline(
                f"{anime['title']} ({anime['year']}) - {anime['episodes']} ᴇᴘs",
                f"anime_{i}".encode()
            )])
        
        buttons.append([Button.inline("𝗖𝗮𝗻𝗰𝗲𝗹", b"cancel_search")])
        
        user_state.anime_results = anime_results
        
        await safe_respond(event,
            "<b>Sᴇᴀʀᴄʜ Rᴇsᴜʟᴛs:</b>\n<b>Sᴇʟᴇᴄᴛ ᴀɴ ᴀɴɪᴍᴇ ғʀᴏᴍ ᴛʜᴇ ʟɪsᴛ ʙᴇʟᴏᴡ:</b>",
            buttons=buttons,
            parse_mode='html'
        )

    @client.on(events.CallbackQuery())
    async def handle_callback(event):
        if not is_admin(event.chat_id):
            await event.answer("ᴀᴅᴍɪɴ ᴏɴʟʏ!", alert=True)
            return
        
        channel_format = (CHANNEL_USERNAME or BOT_USERNAME).lstrip('@')

        data = event.data.decode('utf-8')
        
        if event.chat_id not in user_states:
            user_states[event.chat_id] = UserState()
        
        user_state = user_states[event.chat_id]
        
        current_time = time.time()
        if current_time - user_state.last_command_time < 1:
            return
        user_state.last_command_time = current_time
        
        if data == 'cancel_search':
            await safe_edit(event, "<blockquote><b>ᴄᴀɴᴄᴇʟᴇᴅ, sᴇɴᴅ /sᴛᴀʀᴛ ᴛᴏ ʙᴇɢɪɴ ᴀɢᴀɪɴ!</b></blockquote>", parse_mode='html')
            return
        
        if data.startswith('anime_'):
            if not user_state.anime_results:
                await safe_edit(event, "<blockquote><b>ᴇxᴘɪʀᴇᴅ, sᴇɴᴅ /sᴛᴀʀᴛ ᴛᴏ ʙᴇɢɪɴ ᴀɢᴀɪɴ!</b></blockquote>", parse_mode='html')
                return
            
            anime_index = int(data.split('_')[1])
            if anime_index >= len(user_state.anime_results):
                await safe_edit(event, "<blockquote><b>ɪɴᴠᴀʟɪᴅ, sᴇɴᴅ /sᴛᴀʀᴛ ᴛᴏ ʙᴇɢɪɴ ᴀɢᴀɪɴ!</b></blockquote>", parse_mode='html')
                return
            
            selected_anime = user_state.anime_results[anime_index]
            anime_session = selected_anime['session']
            anime_title = selected_anime['title']
            
            if quality_settings.batch_mode:
                await safe_edit(event,
                    f"<blockquote><b>✦ 𝗕𝗔𝗧𝗖𝗛 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Sᴛᴀᴛᴜs: ᴘʀᴏᴄᴇssɪɴɢ...</blockquote>"
                    f"──────────────────\n"
                    f"<blockquote>≡ ᴘᴏᴡᴇʀᴇᴅ ʙʏ: <a href='t.me/{channel_format}'>{CHANNEL_NAME}</a></blockquote></b>",
                    parse_mode='html'
                )
                success = await download_anime_batch(event, anime_session, anime_title)
                if success:
                    await safe_respond(event, f"<b>Batch download completed for:</b> <i>{anime_title}</i>", parse_mode='html')
                else:
                    await safe_respond(event, f"<b>Batch download failed for:</b> <i>{anime_title}</i>", parse_mode='html')
                return
            
            user_state.anime_session = anime_session
            user_state.anime_title = anime_title
            user_state.total_episodes = selected_anime['episodes']
            
            await safe_edit(event,
                f"<blockquote><b>✦ 𝗙𝗘𝗧𝗖𝗛𝗜𝗡𝗚 𝗘𝗣𝗜𝗦𝗢𝗗𝗘𝗦 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {user_state.anime_title}</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>Fᴇᴛᴄʜɪɴɢ ᴇᴘɪsᴏᴅᴇ ʟɪsᴛ...</blockquote></b>",
                parse_mode='html'
            )
            
            episode_data = await get_episode_list(user_state.anime_session)
            if not episode_data or 'data' not in episode_data:
                await safe_edit(event, "<b><blockquote>ғᴀɪʟᴇᴅ ᴛᴏ ɢᴇᴛ ᴇᴘɪsᴏᴅᴇ ʟɪsᴛ ғᴏʀ ᴀɴɪᴍᴇ</b>/blockquote>", parse_mode='html')
                return
            
            episodes = episode_data.get('data', [])
            if not episodes:
                await safe_edit(event, "<b><blockquote>ɴᴏ ᴇᴘɪsᴏᴅᴇs ғᴏᴜɴᴅ ғᴏʀ ᴛʜɪs ᴀɴɪᴍᴇ.</blockquote></b>", parse_mode='html')
                return
            
            total_pages = episode_data.get('last_page', 1)
            total_episodes = episode_data.get('total', len(episodes))
            user_state.episodes = episodes
            user_state.current_page = 1
            user_state.total_pages = total_pages
            user_state.total_episodes = total_episodes
            
            episodes_per_page = 10
            total_pages_this_batch = (len(episodes) + episodes_per_page - 1) // episodes_per_page
            current_batch_page = 1
            
            buttons = []
            start_idx = (current_batch_page - 1) * episodes_per_page
            end_idx = start_idx + episodes_per_page
            page_episodes = episodes[start_idx:end_idx]
            
            for ep in page_episodes:
                buttons.append([Button.inline(
                    f"Eᴘɪsᴏᴅᴇ {ep['episode']}: {ep['title']}",
                    f"eps_{ep['episode']}".encode()
                )])
            
            nav_buttons = []
            show_nav = total_episodes > episodes_per_page
            
            if show_nav:
                if current_batch_page > 1:
                    nav_buttons.append(Button.inline("𝗣𝗿𝗲𝘃", b"ep_prev"))
                nav_buttons.append(Button.inline(f"𝗣𝗮𝗴𝗲 {current_batch_page}/{total_pages_this_batch}", b"ep_page"))
                if current_batch_page < total_pages_this_batch or user_state.current_page < total_pages:
                    nav_buttons.append(Button.inline("𝗡𝗲𝘅𝘁", b"ep_next"))
                buttons.append(nav_buttons)
            
            buttons.append([Button.inline("𝗖𝗮𝗻𝗰𝗲𝗹", b"cancel_episode")])
            
            await safe_edit(event,
                f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>・ Aɴɪᴍᴇ: {user_state.anime_title}\n"
                f"・ Eᴘɪsᴏᴅᴇs (Pᴀɢᴇ 1/{user_state.total_pages}):</blockquote>\n"
                f"──────────────────\n"
                f"<blockquote>Sᴇʟᴇᴄᴛ ᴀɴ ᴇᴘɪsᴏᴅᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:</b></blockquote>",
                buttons=buttons,
                parse_mode='html'
            )
        
        elif data.startswith(('ep_', 'eps_')):
            if data in ['ep_prev', 'ep_next', 'ep_page']:
                action = data.split('_')[1]
                current_page = user_state.current_page
                total_pages = user_state.total_pages
                anime_session = user_state.anime_session
                anime_title = user_state.anime_title
                episodes = user_state.episodes
                total_episodes = len(episodes)
                
                episodes_per_page = 10
                total_pages_this_batch = (total_episodes + episodes_per_page - 1) // episodes_per_page
                current_batch_page = user_state.current_batch_page if hasattr(user_state, 'current_batch_page') else 1
                
                if action == 'prev':
                    if current_batch_page > 1:
                        current_batch_page -= 1
                    elif current_page > 1:
                        current_page -= 1
                        episode_data = await get_episode_list(anime_session, current_page)
                        episodes = episode_data['data']
                        user_state.episodes = episodes
                        total_episodes = len(episodes)
                        total_pages_this_batch = (total_episodes + episodes_per_page - 1) // episodes_per_page
                        current_batch_page = total_pages_this_batch
                elif action == 'next':
                    if current_batch_page * episodes_per_page < total_episodes:
                        current_batch_page += 1
                    elif current_page < total_pages:
                        current_page += 1
                        episode_data = await get_episode_list(anime_session, current_page)
                        episodes = episode_data['data']
                        current_batch_page = 1
                
                user_state.current_page = current_page
                user_state.current_batch_page = current_batch_page
                
                buttons = []
                start_idx = (current_batch_page - 1) * episodes_per_page
                end_idx = min(start_idx + episodes_per_page, total_episodes)
                page_episodes = episodes[start_idx:end_idx]
                
                for ep in page_episodes:
                    buttons.append([Button.inline(
                        f"Eᴘɪsᴏᴅᴇ {ep['episode']}: {ep['title']}",
                        f"eps_{ep['episode']}".encode()
                    )])
                
                nav_buttons = []
                show_nav = total_episodes > episodes_per_page
                
                if show_nav:
                    if current_batch_page > 1 or current_page > 1:
                        nav_buttons.append(Button.inline("𝗣𝗿𝗲𝘃", b"ep_prev"))
                    nav_buttons.append(Button.inline(
                        f"Pᴀɢᴇ {current_batch_page}/{total_pages_this_batch}" +
                        (f" (Sᴇᴛ {current_page}/{total_pages})" if total_pages > 1 else ""),
                        b"ep_page"
                    ))
                    if current_batch_page * episodes_per_page < total_episodes or current_page < total_pages:
                        nav_buttons.append(Button.inline("𝗡𝗲𝘅𝘁", b"ep_next"))
                    buttons.append(nav_buttons)
                
                buttons.append([Button.inline("𝗖𝗮𝗻𝗰𝗲𝗹", b"cancel_episode")])
                
                await safe_edit(event,
                    f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇs (Pᴀɢᴇ {current_page}/{total_pages}):</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>Sᴇʟᴇᴄᴛ ᴀɴ ᴇᴘɪsᴏᴅᴇ ᴛᴏ ᴅᴏᴡɴʟᴏᴀᴅ:</blockquote>",
                    buttons=buttons,
                    parse_mode='html'
                )
            else:
                episode_num = int(data.split('_')[1])
                episodes = user_state.episodes
                
                selected_episode = None
                for ep in episodes:
                    if int(ep['episode']) == episode_num:
                        selected_episode = ep
                        break
                
                if not selected_episode:
                    await safe_edit(event, "<b><blockquote>ᴜɴᴀʙʟᴇ ᴛᴏ ғɪɴᴅ ᴇᴘɪsᴏᴅᴇ</b></blockquote>", parse_mode='html')
                    return
                
                episode_number = selected_episode['episode']
                episode_session = selected_episode['session']
                anime_session = user_state.anime_session
                anime_title = user_state.anime_title
                
                user_state.episode_session = episode_session
                user_state.episode_number = episode_number
                
                await safe_edit(event,
                    f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number} - {selected_episode['title']}\n"
                    f"・ Sᴛᴀᴛᴜs: ғᴇᴛᴄʜɪɴɢ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋs...</b></blockquote>",
                    parse_mode='html'
                )
                
                download_links = get_download_links(anime_session, episode_session)
                if not download_links:
                    await safe_edit(event, "<b><blockquote>ɴᴏ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋs ғᴏᴜɴᴅ ғᴏʀ ᴛʜɪs ᴇᴘɪsᴏᴅᴇ.</blockquote></b>", parse_mode='html')
                    return
                
                user_state.download_links = download_links
                
                buttons = []
                for i, link in enumerate(download_links):
                    buttons.append([Button.inline(
                        link['text'],
                        f"qual_{i}".encode()
                    )])
                
                buttons.append([Button.inline("𝗖𝗮𝗻𝗰𝗲𝗹", b"cancel_quality")])
                
                await safe_edit(event,
                    f"<blockquote><b>✦ 𝗗𝗢𝗪𝗡𝗟𝗢𝗔𝗗𝗜𝗡𝗚 ✦</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>・ Aɴɪᴍᴇ: {anime_title}\n"
                    f"・ Eᴘɪsᴏᴅᴇ: {episode_number} - {selected_episode['title']}</blockquote>\n"
                    f"──────────────────\n"
                    f"<blockquote>Sᴇʟᴇᴄᴛ ᴅᴏᴡɴʟᴏᴀᴅ ǫᴜᴀʟɪᴛʏ:</blockqute></b>",
                    buttons=buttons,
                    parse_mode='html'
                )
        
        elif data.startswith('qual_'):
            quality_index = int(data.split('_')[1])
            download_links = user_state.download_links
            
            if not download_links:
                await safe_edit(event, "<blockquote><b>ɴᴏ ᴅᴏᴡɴʟᴏᴀᴅ ʟɪɴᴋs ғᴏᴜɴᴅ!</b></blockquote>", parse_mode='html')
                return
            
            if quality_index >= len(download_links):
                await safe_edit(event, "<blockquote><b>ɪɴᴠᴀʟɪᴅ sᴇʟᴇᴄᴛɪᴏɴ.</b></blockquote>", parse_mode='html')
                return
            
            selected_quality = download_links[quality_index]
            anime_session = user_state.anime_session
            anime_title = user_state.anime_title
            episode_number = user_state.episode_number
            episode_session = user_state.episode_session
            
            await download_episode(event, anime_title, anime_session, episode_number, episode_session, selected_quality)
        
            error_msg_fk='''<blockquote><b>ᴏᴘᴇʀᴀᴛɪᴏɴ ᴄᴀɴᴄᴇʟᴇᴅ, sᴇɴᴅ /sᴛᴀʀᴛ ᴛᴏ ʙᴇɢɪɴ ᴀɢᴀɪɴ!</b></blockquote>'''

        elif data == 'cancel_episode':
            await safe_edit(event, error_msg_fk, parse_mode='html')
        
        elif data == 'cancel_quality':
            await safe_edit(event, error_msg_fk, parse_mode='html')
        
        elif data == 'cancel_download':
            await safe_edit(event, error_msg_fk, parse_mode='html')

@client.on(events.NewMessage(pattern=r'^/request\s+(.+)$'))
async def request_command(event):
    try:
        from core.database import (
            add_request, get_user_pending_requests, 
            get_pending_request_count, get_max_requests_setting,
            get_request_group_chat
        )
        
        group_config = await get_request_group_chat()
        if not group_config:
            await safe_respond(event, "<blockquote><b>ᴍʀ sʏsᴛᴇᴍ ɴᴏᴛ ᴄᴏɴғɪɢᴜʀᴇᴅ ʏᴇᴛ.</b></blockquote>", parse_mode='html')
            return
        
        configured_chat_id = group_config.get('chat_id')
        configured_username = group_config.get('username')
        
        is_correct_group = False
        if configured_chat_id and event.chat_id == configured_chat_id:
            is_correct_group = True
        elif configured_username:
            chat = await event.get_chat()
            if hasattr(chat, 'username') and chat.username == configured_username.lstrip('@'):
                is_correct_group = True
        
        if not is_correct_group:
            await safe_respond(event, "<blockquote><b>ʀᴇǫᴜᴇsᴛs ᴀʀᴇ ᴏɴʟʏ ᴀʟʟᴏᴡᴇᴅ ɪɴ ᴛʜᴇ ᴄᴏɴғɪɢᴜʀᴇᴅ ɢʀᴏᴜᴘ.</b></blockquote>", parse_mode='html')
            return
        
        request_text = event.pattern_match.group(1).strip()
        
        if not request_text:
            await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀɴɪᴍᴇ ɴᴀᴍᴇ ᴛᴏ ʀᴇǫᴜᴇsᴛ.</b>\n<i>ᴇxᴀᴍᴘʟᴇ: /request Jujutsu Kaisen</i></blockquote>", parse_mode='html')
            return
        
        user_id = event.sender_id
        sender = await event.get_sender()
        username = sender.username if sender.username else f"User{user_id}"
        
        user_pending = await get_user_pending_requests(user_id)
        if user_pending > 0:
            await safe_respond(event, "<blockquote><b>ʏᴏᴜ ᴀʟʀᴇᴀᴅʏ ʜᴀᴠᴇ ᴀ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛ.</b>\n<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ғᴏʀ ɪᴛ ᴛᴏ ʙᴇ ᴘʀᴏᴄᴇssᴇᴅ.</i></blockquote>", parse_mode='html')
            return
        
        max_requests = await get_max_requests_setting()
        total_pending = await get_pending_request_count()
        
        if total_pending >= max_requests:
            await safe_respond(event, f"<blockquote><b>ʀᴇǫᴜᴇsᴛ ǫᴜᴇᴜᴇ ɪs ғᴜʟʟ ({total_pending}/{max_requests}).</b>\n<i>ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.</i></blockquote>", parse_mode='html')
            return
        
        success = await add_request(user_id, request_text, username)
        
        if success:
            await safe_respond(
                event,
                f"<blockquote><b>✦ ʀᴇǫᴜᴇsᴛ ᴀᴄᴄᴇᴘᴛᴇᴅ ✦</b>\n\n"
                f"<b>Aɴɪᴍᴇ:</b> {request_text}\n"
                f"<b>Usᴇʀ:</b> @{username}\n"
                f"<b>Sᴛᴀᴛᴜs:</b> ᴘᴇɴᴅɪɴɢ\n\n"
                f"<i>ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ᴡɪʟʟ ʙᴇ ᴘʀᴏᴄᴇssᴇᴅ ᴅᴜʀɪɴɢ ᴅᴀɪʟʏ ʙᴀᴛᴄʜ ᴘʀᴏᴄᴇssɪɴɢ.</i></blockquote>",
                parse_mode='html'
            )
            logger.info(f"Request added from user {user_id} (@{username}): {request_text}")
        else:
            await safe_respond(event, "<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴀᴅᴅ ʀᴇǫᴜᴇsᴛ. ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b></blockquote>", parse_mode='html')
    
    except Exception as e:
        logger.error(f"Error in request_command: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> <i>{str(e)}</i></blockquote>", parse_mode='html')


@client.on(events.NewMessage(pattern=r'^\*request\s+(.+)$'))
async def request_pattern_handler(event):
    try:
        from core.database import (
            add_request, get_user_pending_requests, 
            get_pending_request_count, get_max_requests_setting,
            get_request_group_chat
        )
        
        group_config = await get_request_group_chat()
        if not group_config:
            await safe_respond(event, "<blockquote><b>ᴍʀ sʏsᴛᴇᴍ ɴᴏᴛ ᴄᴏɴғɪɢᴜʀᴇᴅ ʏᴇᴛ.</b></blockquote>", parse_mode='html')
            return

        configured_chat_id = group_config.get('chat_id')
        configured_username = group_config.get('username')
        
        is_correct_group = False
        if configured_chat_id and event.chat_id == configured_chat_id:
            is_correct_group = True
        elif configured_username:
            chat = await event.get_chat()
            if hasattr(chat, 'username') and chat.username == configured_username.lstrip('@'):
                is_correct_group = True
        
        if not is_correct_group:
            await safe_respond(event, "<blockquote><b>ʀᴇǫᴜᴇsᴛs ᴀʀᴇ ᴏɴʟʏ ᴀʟʟᴏᴡᴇᴅ ɪɴ ᴛʜᴇ ᴄᴏɴғɪɢᴜʀᴇᴅ ɢʀᴏᴜᴘ.</b></blockquote>", parse_mode='html')
            return
        
        request_text = event.pattern_match.group(1).strip()
        
        if not request_text:
            await safe_respond(event, "<blockquote><b>ᴘʟᴇᴀsᴇ ᴘʀᴏᴠɪᴅᴇ ᴀɴɪᴍᴇ ɴᴀᴍᴇ ᴛᴏ ʀᴇǫᴜᴇsᴛ.</b>\n<i>ᴇxᴀᴍᴘʟᴇ: *request Jujutsu Kaisen</i></blockquote>", parse_mode='html')
            return

        user_id = event.sender_id
        sender = await event.get_sender()
        username = sender.username if sender.username else f"User{user_id}"
        
        user_pending = await get_user_pending_requests(user_id)
        if user_pending > 0:
            await safe_respond(event, "<blockquote><b>ʏᴏᴜ ᴀʟʀᴇᴀᴅʏ ʜᴀᴠᴇ ᴀ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛ.</b>\n<i>ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ ғᴏʀ ɪᴛ ᴛᴏ ʙᴇ ᴘʀᴏᴄᴇssᴇᴅ.</i></blockquote>", parse_mode='html')
            return
        
        max_requests = await get_max_requests_setting()
        total_pending = await get_pending_request_count()
        
        if total_pending >= max_requests:
            await safe_respond(event, f"<blockquote><b>ʀᴇǫᴜᴇsᴛ ǫᴜᴇᴜᴇ ɪs ғᴜʟʟ ({total_pending}/{max_requests}).</b>\n<i>ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ ʟᴀᴛᴇʀ.</i></blockquote>", parse_mode='html')
            return
        
        success = await add_request(user_id, request_text, username)
        
        if success:
            await safe_respond(
                event,
                f"<blockquote><b>✦ ʀᴇǫᴜᴇsᴛ ᴀᴄᴄᴇᴘᴛᴇᴅ ✦</b>\n\n"
                f"<b>Aɴɪᴍᴇ:</b> {request_text}\n"
                f"<b>Usᴇʀ:</b> @{username}\n"
                f"<b>Sᴛᴀᴛᴜs:</b> ᴘᴇɴᴅɪɴɢ\n\n"
                f"<i>ʏᴏᴜʀ ʀᴇǫᴜᴇsᴛ ᴡɪʟʟ ʙᴇ ᴘʀᴏᴄᴇssᴇᴅ ᴅᴜʀɪɴɢ ᴅᴀɪʟʏ ʙᴀᴛᴄʜ ᴘʀᴏᴄᴇssɪɴɢ.</i></blockquote>",
                parse_mode='html'
            )
            logger.info(f"Request added from user {user_id} (@{username}): {request_text}")
        else:
            await safe_respond(event, "<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴀᴅᴅ ʀᴇǫᴜᴇsᴛ. ᴘʟᴇᴀsᴇ ᴛʀʏ ᴀɢᴀɪɴ.</b></blockquote>", parse_mode='html')
    
    except Exception as e:
        logger.error(f"Error in request_pattern_handler: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> <i>{str(e)}</i></blockquote>", parse_mode='html')



@client.on(events.NewMessage(pattern=r'^/set_request_group\s+(.+)$'))
async def set_request_group_command(event):
    if not is_admin(event.chat_id):
        await safe_respond(event, "<blockquote><b>ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ.</b></blockquote>", parse_mode='html')
        return
    
    try:
        from core.database import set_request_group_chat
        
        group_identifier = event.pattern_match.group(1).strip()
        
        chat_id = None
        username = None
        
        if group_identifier.isdigit():
            chat_id = int(group_identifier)
        elif group_identifier.startswith('@'):
            username = group_identifier
        elif group_identifier.startswith('-'):
            try:
                chat_id = int(group_identifier)
            except ValueError:
                username = group_identifier
        else:
            username = group_identifier if not group_identifier.isdigit() else None
            if not username:
                try:
                    chat_id = int(group_identifier)
                except ValueError:
                    username = group_identifier
        
        success = await set_request_group_chat(chat_id, username)
        
        if success:
            config_text = f"Chat ID: {chat_id}" if chat_id else f"Username: {username}"
            await safe_respond(
                event,
                f"<blockquote><b>✦ ʀᴇǫᴜᴇsᴛ ɢʀᴏᴜᴘ ᴄᴏɴғɪɢᴜʀᴇᴅ ✦</b>\n\n"
                f"<b>{config_text}</b>\n\n"
                f"<i>ᴜsᴇʀs ᴄᴀɴ ɴᴏᴡ sᴜʙᴍɪᴛ ʀᴇǫᴜᴇsᴛs ᴜsɪɴɢ /request ᴏʀ *request</i></blockquote>",
                parse_mode='html'
            )
            logger.info(f"Request group set to: {config_text}")
        else:
            await safe_respond(event, "<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ sᴇᴛ ʀᴇǫᴜᴇsᴛ ɢʀᴏᴜᴘ.</b></blockquote>", parse_mode='html')
    
    except Exception as e:
        logger.error(f"Error in set_request_group_command: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> <i>{str(e)}</i></blockquote>", parse_mode='html')


@client.on(events.NewMessage(pattern=r'^/view_requests$'))
async def view_requests_command(event):
    if not is_admin(event.chat_id):
        await safe_respond(event, "<blockquote><b>ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ.</b></blockquote>", parse_mode='html')
        return
    
    try:
        from core.database import get_all_pending_requests
        
        status_msg = await safe_respond(event, "<blockquote><b>ғᴇᴛᴄʜɪɴɢ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs...</blockquote></b>", parse_mode='html')
        
        pending_requests = await get_all_pending_requests()
        
        if not pending_requests:
            await status_msg.edit("<blockquote><b>ɴᴏ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs ᴀᴛ ᴛʜᴇ ᴍᴏᴍᴇɴᴛ.</b></blockquote>", parse_mode='html')
            return
        
        requests_text = "<blockquote><b>✦ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs ✦</b></blockquote>\n\n"
        
        for idx, req in enumerate(pending_requests, 1):
            user_id = req.get('user_id', 'N/A')
            username = req.get('username', 'Unknown')
            text = req.get('text', 'N/A')
            created_at = req.get('created_at', 'N/A')
            
            try:
                created_dt = datetime.fromisoformat(created_at)
                created_at = created_dt.strftime('%Y-%m-%d %H:%M')
            except:
                pass
            
            requests_text += (
                f"<blockquote><b>{idx}. {text}</b>\n"
                f"<b>User:</b> @{username} (ID: {user_id})\n"
                f"<b>Added:</b> {created_at}</blockquote>\n"
            )
        
        await status_msg.edit(requests_text, parse_mode='html')
        logger.info(f"Showed {len(pending_requests)} pending requests")
    
    except Exception as e:
        logger.error(f"Error in view_requests_command: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> <i>{str(e)}</i></blockquote>", parse_mode='html')


@client.on(events.NewMessage(pattern=r'^/set_max_requests\s+(\d+)$'))
async def set_max_requests_command(event):
    if not is_admin(event.chat_id):
        await safe_respond(event, "<blockquote><b>ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ.</b></blockquote>", parse_mode='html')
        return
    
    try:
        from core.database import set_max_requests_setting
        
        max_requests = int(event.pattern_match.group(1))
        
        if max_requests < 1:
            await safe_respond(event, "<blockquote><b>ᴍᴀx ʀᴇǫᴜᴇsᴛs ᴍᴜsᴛ ʙᴇ ᴀᴛ ʟᴇᴀsᴛ 1.</b></blockquote>", parse_mode='html')
            return
        
        if max_requests > 100:
            await safe_respond(event, "<blockquote><b>ᴍᴀx ʀᴇǫᴜᴇsᴛs ᴄᴀɴɴᴏᴛ ᴇxᴄᴇᴇᴅ 100.</b></blockquote>", parse_mode='html')
            return
        
        success = await set_max_requests_setting(max_requests)
        
        if success:
            await safe_respond(
                event,
                f"<blockquote><b>✦ ᴍᴀx ʀᴇǫᴜᴇsᴛs ᴜᴘᴅᴀᴛᴇᴅ ✦</b>\n\n"
                f"<b>ɴᴇᴡ ʟɪᴍɪᴛ:</b> {max_requests} ʀᴇǫᴜᴇsᴛs\n\n"
                f"<i>ɪғ ᴄᴜʀʀᴇɴᴛ ʀᴇǫᴜᴇsᴛs ᴇxᴄᴇᴇᴅ ᴛʜɪs, ɴᴇᴡ ᴏɴᴇs ᴡɪʟʟ ʙᴇ ʀᴇᴊᴇᴄᴛᴇᴅ.</i></blockquote>",
                parse_mode='html'
            )
            logger.info(f"Max requests set to {max_requests}")
        else:
            await safe_respond(event, "<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴜᴘᴅᴀᴛᴇ ᴍᴀx ʀᴇǫᴜᴇsᴛs.</b></blockquote>", parse_mode='html')
    
    except Exception as e:
        logger.error(f"Error in set_max_requests_command: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> <i>{str(e)}</i></blockquote>", parse_mode='html')


@client.on(events.NewMessage(pattern=r'^/set_request_time\s+([0-2][0-9]:[0-5][0-9])$'))
async def set_request_time_command(event):
    if not is_admin(event.chat_id):
        await safe_respond(event, "<blockquote><b>ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴜsᴇ ᴛʜɪs ᴄᴏᴍᴍᴀɴᴅ.</b></blockquote>", parse_mode='html')
        return
    
    try:
        from core.database import set_request_process_time
        from core.scheduler import reschedule_daily_requests, convert_ist_to_utc
        
        time_str = event.pattern_match.group(1)
        
        success = await set_request_process_time(time_str)
        
        if success:
            await reschedule_daily_requests(time_str)
            
            utc_time_str = convert_ist_to_utc(time_str)
            
            await safe_respond(
                event,
                f"<blockquote><b>✦ ʀᴇǫᴜᴇsᴛ ᴘʀᴏᴄᴇssɪɴɢ ᴛɪᴍᴇ ᴜᴘᴅᴀᴛᴇᴅ ✦</b>\n\n"
                f"<b>ᴅᴀɪʟʏ ᴘʀᴏᴄᴇssɪɴɢ ᴛɪᴍᴇ:</b> {time_str} (IST)\n"
                f"<b>ᴇǫᴜɪᴠᴀʟᴇɴᴛ ᴜᴛᴄ:</b> {utc_time_str}\n\n"
                f"<i>ʀᴇǫᴜᴇsᴛs ᴡɪʟʟ ʙᴇ ᴘʀᴏᴄᴇssᴇᴅ ᴇᴠᴇʀʏ ᴅᴀʏ ᴀᴛ {time_str} (IST)</i></blockquote>",
                parse_mode='html'
            )
            logger.info(f"Request processing time set to {time_str} IST ({utc_time_str} UTC)")
        else:
            await safe_respond(event, "<blockquote><b>ғᴀɪʟᴇᴅ ᴛᴏ ᴜᴘᴅᴀᴛᴇ ᴘʀᴏᴄᴇssɪɴɢ ᴛɪᴍᴇ.</b></blockquote>", parse_mode='html')
    
    except Exception as e:
        logger.error(f"Error in set_request_time_command: {e}")
        await safe_respond(event, f"<blockquote><b>ᴇʀʀᴏʀ:</b> <i>{str(e)}</i></blockquote>", parse_mode='html')
