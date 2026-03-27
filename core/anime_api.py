from __future__ import annotations
import re
import time
import random
import logging
from typing import Optional, List, Dict, Any
from urllib.parse import quote

import requests
import aiohttp
import cloudscraper
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import (
    HEADERS, YTDLP_HEADERS, ANILIST_API, WORKER_BASE_URL, PAHE_LINKS_WORKER_URL
)

logger = logging.getLogger(__name__)



@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
async def search_anime(query: str) -> Optional[List[Dict[str, Any]]]:
    search_url = f"https://animepahe.si/api?m=search&q={quote(query)}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(search_url, headers=HEADERS) as response:
            response.raise_for_status()
            data = await response.json()
            
            if data.get('total', 0) == 0:
                return None
            
            return data.get('data', [])


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
async def get_episode_list(session_id: str, page: int = 1) -> Dict[str, Any]:
    episodes_url = f"https://animepahe.si/api?m=release&id={session_id}&sort=episode_asc&page={page}"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(episodes_url, headers=HEADERS) as response:
            response.raise_for_status()
            return await response.json()


def get_latest_releases(page=1):
    releases_url = f"https://animepahe.si/api?m=airing&page={page}"
    response = requests.get(releases_url, headers=HEADERS).json()
    return response


async def get_all_episodes(anime_session):
    all_episodes = []
    page = 1
    while True:
        episode_data = await get_episode_list(anime_session, page)
        if not episode_data or 'data' not in episode_data:
            break
        episodes = episode_data['data']
        all_episodes.extend(episodes)
        if page >= episode_data.get('last_page', 1):
            break
        page += 1
    return all_episodes


def find_closest_episode(episodes, target_episode):
    try:
        target = int(target_episode)
    except (ValueError, TypeError):
        return None
    
    valid_episodes = []
    for ep in episodes:
        try:
            ep_num = int(ep['episode'])
            valid_episodes.append((ep_num, ep))
        except (ValueError, TypeError):
            continue
    
    if not valid_episodes:
        return None
    
    valid_episodes.sort(key=lambda x: x[0])
    
    closest = None
    for ep_num, ep in valid_episodes:
        if ep_num <= target:
            closest = ep
        else:
            break
    
    if closest is None and valid_episodes:
        closest = valid_episodes[0][1]
    
    return closest



def extract_resolution_from_text(text: str) -> Optional[int]:
    import re
    match = re.search(r'(\d{3,4})p', text)
    if match:
        return int(match.group(1))
    return None


def map_resolution_to_quality_tier(resolution: int) -> str:
    if resolution <= 360:
        return "360p"
    elif resolution <= 720:
        return "720p"
    else:
        return "1080p"


def find_best_link_for_quality(download_links: List[Dict[str, Any]], target_quality: str) -> Optional[Dict[str, Any]]:
    target_value = int(target_quality[:-1])
    
    for link in download_links:
        if target_quality in link['text']:
            return link
    
    candidates = []
    for link in download_links:
        resolution = extract_resolution_from_text(link['text'])
        if resolution:
            mapped_tier = map_resolution_to_quality_tier(resolution)
            if mapped_tier == target_quality:
                candidates.append((resolution, link))
    
    if not candidates:
        return None
    
    candidates.sort(key=lambda x: x[0])
    
    if target_quality == "360p":
        return candidates[0][1]
    else:
        return candidates[-1][1]


def get_available_qualities_with_mapping(download_links: List[Dict[str, Any]], enabled_qualities: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    result = {}
    for quality in enabled_qualities:
        result[quality] = find_best_link_for_quality(download_links, quality)
    return result



@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=10),
    reraise=True
)
def get_download_links(anime_session, episode_session):
    if '-' in episode_session:
        episode_url = f"https://animepahe.si/play/{episode_session}"
    else:
        episode_url = f"https://animepahe.si/play/{anime_session}/{episode_session}"
    
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        time.sleep(random.uniform(2, 5))
        local_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        session.headers.update(local_headers)
        session.get("https://animepahe.si/")
        logger.info(f"Fetching episode page: {episode_url}")
        response = session.get(episode_url)
        response.raise_for_status()
        
        for parser in ['lxml', 'html.parser', 'html5lib']:
            try:
                soup = BeautifulSoup(response.content, parser)
                break
            except:
                continue
        
        links = []
        
        selectors = [
            "#pickDownload a.dropdown-item",
            "#downloadMenu a",
            "a[download]",
            "a.btn-download",
            "a[href*='download']",
            ".download-wrapper a"
        ]
        
        for selector in selectors:
            elements = soup.select(selector)
            if elements:
                logger.info(f"Found {len(elements)} links with selector: {selector}")
                for element in elements:
                    href = element.get('href') or element.get('data-url') or element.get('data-href')
                    if href:
                        if not href.startswith('http'):
                            href = f"https://animepahe.si{href}"
                        links.append({
                            'text': element.get_text(strip=True),
                            'href': href
                        })
        
        if not links:
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)
                if any(keyword in href.lower() or keyword in text.lower() 
                      for keyword in ['download', 'kwik.cx', 'video', 'player']):
                    if not href.startswith('http'):
                        href = f"https://animepahe.si{href}"
                    links.append({
                        'text': text or 'Download',
                        'href': href
                    })
        
        if links:
            logger.info(f"Found {len(links)} download links")
            return links
        
        logger.error(f"No download links found for episode {episode_url}")
        logger.debug(f"Page content sample: {response.text[:1000]}")
        return None
        
    except Exception as e:
        logger.error(f"Error getting download links: {str(e)}")
        logger.error(f"URL attempted: {episode_url}")
        return None

def step_2(s, seperator, base=10):
    mapped_range = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+/"
    numbers = mapped_range[0:base]
    max_iter = 0
    for index, value in enumerate(s[::-1]):
        max_iter += int(value if value.isdigit() else 0) * (seperator**index)
    mid = ''
    while max_iter > 0:
        mid = numbers[int(max_iter % base)] + mid
        max_iter = (max_iter - (max_iter % base)) / base
    return mid or '0'

def step_1(data, key, load, seperator):
    payload = ""
    i = 0
    seperator = int(seperator)
    load = int(load)
    while i < len(data):
        s = ""
        while data[i] != key[seperator]:
            s += data[i]
            i += 1
        for index, value in enumerate(key):
            s = s.replace(value, str(index))
        payload += chr(int(step_2(s, seperator, 10)) - load)
        i += 1
    payload = re.findall(
        r'action="([^\"]+)" method="POST"><input type="hidden" name="_token"\s+value="([^\"]+)', payload
    )[0]
    return payload

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
def get_dl_link(link):
    try:
        if link and link.startswith("WORKER_RESOLVED:"):
            final_mp4_url = link.replace("WORKER_RESOLVED:", "")
            logger.info(f"Using Worker-resolved MP4 URL: {final_mp4_url[:80]}...")
            return WORKER_BASE_URL + final_mp4_url
        
        time.sleep(random.uniform(1, 3))

        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            interpreter='nodejs'
        )

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
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
        
        scraper.get("https://animepahe.si/", headers=headers)
        
        resp = scraper.get(link, headers=headers)
        
        patterns = [
            r'\("([^"]+)",(\d+),"([^"]+)",(\d+),(\d+)',
            r'\("(\S+)",\d+,"(\S+)",(\d+),(\d+)'
        ]
        
        match = None
        for pattern in patterns:
            match = re.search(pattern, resp.text)
            if match:
                break
        
        if not match:
            logger.error(f"Could not find required pattern in response from {link}")
            return None
        
        if len(match.groups()) == 5:
            data, _, key, load, seperator = match.groups()
        else:
            data, key, load, seperator = match.groups()
        
        url, token = step_1(data=data, key=key, load=load, seperator=seperator)

        post_url = url if url.startswith('http') else f"https://kwik.cx{url}"
        data = {"_token": token}
        post_headers = {
            'referer': link,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Origin': 'https://kwik.cx'
        }
        
        resp = scraper.post(url=post_url, data=data, headers=post_headers, allow_redirects=False)
        
        if 'location' in resp.headers:
            direct_link = resp.headers["location"]
            return WORKER_BASE_URL + direct_link
        
        resp = scraper.post(url=post_url, data=data, headers=post_headers, allow_redirects=True)
        
        if resp.url != post_url and not resp.url.startswith('https://kwik.cx/'):
            direct_link = resp.url
            return WORKER_BASE_URL + direct_link
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting direct link: {str(e)}")
        raise

def extract_kwik_link_via_worker(pahe_win_url: str) -> Optional[str]:
    if not PAHE_LINKS_WORKER_URL:
        logger.error("PAHE_LINKS_WORKER_URL not configured")
        return None
    
    try:
        from urllib.parse import urlencode, quote
        
        worker_url = f"{PAHE_LINKS_WORKER_URL.rstrip('/')}/?url={quote(pahe_win_url, safe='')}"
        
        logger.info(f"Calling Worker API to resolve pahe.win URL: {pahe_win_url}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'application/json',
        }
        
        response = requests.get(worker_url, headers=headers, timeout=60)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get('status') == 'success':
            final_mp4_url = data.get('final_mp4_url')
            original_kwik = data.get('original_kwik')
            
            if final_mp4_url:
                logger.info(f"Worker API resolved to MP4: {final_mp4_url[:80]}...")
                return f"WORKER_RESOLVED:{final_mp4_url}"
            elif original_kwik:
                logger.info(f"Worker API returned kwik URL: {original_kwik}")
                return original_kwik
        
        error_msg = data.get('error', 'Unknown error from Worker API')
        logger.error(f"Worker API error: {error_msg}")
        return None
        
    except requests.exceptions.Timeout:
        logger.error(f"Worker API timeout for URL: {pahe_win_url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Worker API request error: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Worker API unexpected error: {str(e)}")
        return None


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    reraise=True
)
def extract_kwik_link(url):
    if 'pahe.win' in url or 'pahe.cx' in url:
        result = extract_kwik_link_via_worker(url)
        if result:
            return result
        logger.warning(f"Worker API failed for {url}, will retry...")
        raise Exception(f"Worker API failed to resolve: {url}")
    
    try:
        time.sleep(random.uniform(1, 3))
        
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            interpreter='nodejs'
        )
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://animepahe.si/'
        }
        
        scraper.get("https://animepahe.si/", headers=headers)
        
        response = scraper.get(url, headers=headers)
        response.raise_for_status()
        
        logger.info(f"Got response from {url}, status code: {response.status_code}")
        
        for parser in ['lxml', 'html.parser', 'html5lib']:
            try:
                soup = BeautifulSoup(response.text, parser)
                logger.info(f"Parsed with {parser}")
                break
            except Exception as e:
                logger.warning(f"Parser {parser} failed: {str(e)}")
                continue
        
        for script in soup.find_all('script'):
            if script.string:
                match = re.search(r'https://kwik\.cx/f/[\w\d-]+', script.string)
                if match:
                    return match.group(0)
        
        download_elements = soup.select('a[href*="kwik.cx"], a[onclick*="kwik.cx"]')
        for element in download_elements:
            href = element.get('href') or element.get('onclick', '')
            match = re.search(r'https://kwik\.cx/f/[\w\d-]+', href)
            if match:
                return match.group(0)
        
        page_text = str(soup)
        matches = re.findall(r'https://kwik\.cx/f/[\w\d-]+', page_text)
        if matches:
            return matches[0]
        
        return None
    except Exception as e:
        logger.error(f"Error extracting kwik link: {str(e)}")
        raise



async def get_anime_info(title: str) -> Dict[str, Any]:
    query = """
query ($id: Int, $search: String, $seasonYear: Int) {
  Media(id: $id, type: ANIME, search: $search, seasonYear: $seasonYear) {
    id
    idMal
    title {
      romaji
      english
      native
    }
    type
    format
    status(version: 2)
    description(asHtml: false)
    startDate {
      year
      month
      day
    }
    endDate {
      year
      month
      day
    }
    season
    seasonYear
    episodes
    duration
    chapters
    volumes
    countryOfOrigin
    source
    hashtag
    trailer {
      id
      site
      thumbnail
    }
    updatedAt
    coverImage {
      large
    }
    bannerImage
    genres
    synonyms
    averageScore
    meanScore
    popularity
    trending
    favourites
    studios {
      nodes {
         name
         siteUrl
      }
    }
    isAdult
    nextAiringEpisode {
      airingAt
      timeUntilAiring
      episode
    }
    airingSchedule {
      edges {
        node {
          airingAt
          timeUntilAiring
          episode
        }
      }
    }
    externalLinks {
      url
      site
    }
    siteUrl
  }
}
"""
    
    variables = {
        'search': title
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANILIST_API, json={'query': query, 'variables': variables}) as response:
                data = await response.json()
                if data.get('data', {}).get('Media'):
                    return data['data']['Media']
    except Exception as e:
        logger.error(f"Error fetching anime info from AniList: {e}")
    
    return None


async def download_anime_poster(anime_title: str) -> Optional[str]:
    from core.config import THUMBNAIL_DIR
    from core.utils import sanitize_filename
    
    try:
        anime_info = await get_anime_info(anime_title)
        if not anime_info:
            return None
        
        poster_url = anime_info.get('coverImage', {}).get('large')
        if not poster_url:
            return None

        async with aiohttp.ClientSession() as session:
            async with session.get(poster_url) as response:
                if response.status == 200:
                    import os
                    poster_path = os.path.join(THUMBNAIL_DIR, f"{sanitize_filename(anime_title)}.jpg")
                    with open(poster_path, 'wb') as f:
                        f.write(await response.read())
                    return poster_path
    except Exception as e:
        logger.error(f"Error downloading anime poster: {e}")
    
    return None
