"""
WhatsMyName worker — scans a username against the WhatsMyName database.
Fetches the database dynamically from GitHub, caches it locally,
and runs checks concurrently using HTTP requests.
"""
import asyncio
import os
import json
import logging
import httpx
from typing import Dict, List, Callable, Optional
from app.utils.scan_logger import log_scan_message

logger = logging.getLogger(__name__)

WMN_DATABASE_URL = "https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-json.json"
CACHE_PATH = "/data/db/wmn-json.json"

# Fallback top sites list if the network download fails completely
FALLBACK_SITES = [
    {"name": "Twitter", "uri_check": "https://twitter.com/{account}", "e_code": 200, "m_code": 404},
    {"name": "Instagram", "uri_check": "https://www.instagram.com/{account}/", "e_code": 200, "m_code": 404},
    {"name": "Reddit", "uri_check": "https://www.reddit.com/user/{account}", "e_code": 200, "m_code": 404},
    {"name": "GitHub", "uri_check": "https://github.com/{account}", "e_code": 200, "m_code": 404},
    {"name": "Pinterest", "uri_check": "https://www.pinterest.com/{account}/", "e_code": 200, "m_code": 404},
    {"name": "SoundCloud", "uri_check": "https://soundcloud.com/{account}", "e_code": 200, "m_code": 404},
    {"name": "Steam", "uri_check": "https://steamcommunity.com/id/{account}", "e_code": 200, "m_code": 404},
    {"name": "Tumblr", "uri_check": "https://{account}.tumblr.com", "e_code": 200, "m_code": 404},
    {"name": "Vimeo", "uri_check": "https://vimeo.com/{account}", "e_code": 200, "m_code": 404},
    {"name": "eBay", "uri_check": "https://www.ebay.com/usr/{account}", "e_code": 200, "m_code": 404},
    {"name": "Medium", "uri_check": "https://medium.com/@{account}", "e_code": 200, "m_code": 404},
    {"name": "Twitch", "uri_check": "https://www.twitch.tv/{account}", "e_code": 200, "m_code": 404},
    {"name": "DeviantArt", "uri_check": "https://www.deviantart.com/{account}", "e_code": 200, "m_code": 404},
    {"name": "WordPress", "uri_check": "https://{account}.wordpress.com", "e_code": 200, "m_code": 404},
]


async def _load_wmn_database(client: httpx.AsyncClient) -> List[Dict]:
    """Load sites from cache or download from official GitHub repository."""
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    
    # 1. Try to download
    try:
        logger.info(f"Downloading WhatsMyName database from GitHub...")
        response = await client.get(WMN_DATABASE_URL, timeout=10.0)
        if response.status_code == 200:
            data = response.json()
            sites = data.get("sites", [])
            if sites:
                with open(CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(sites, f)
                logger.info(f"WhatsMyName DB downloaded: {len(sites)} sites")
                return sites
    except Exception as e:
        logger.warning(f"Could not download WhatsMyName DB: {e}. Trying cache...")

    # 2. Try cache
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                sites = json.load(f)
                if sites:
                    logger.info(f"WhatsMyName DB loaded from cache: {len(sites)} sites")
                    return sites
        except Exception as e:
            logger.error(f"Error loading cached WMN database: {e}")

    # 3. Fallback
    logger.info("Using minimal built-in fallback sites for WhatsMyName")
    return FALLBACK_SITES


async def check_site(
    client: httpx.AsyncClient,
    site: Dict,
    username: str,
    proxy_url: Optional[str] = None
) -> Optional[Dict]:
    """Check if username exists on a single WhatsMyName site."""
    name = site.get("name", "Unknown")
    uri_check = site.get("uri_check", "")
    if not uri_check or "{account}" not in uri_check:
        return None

    url = uri_check.replace("{account}", username)
    e_code = site.get("e_code")
    e_string = site.get("e_string")
    m_code = site.get("m_code")
    m_string = site.get("m_string")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        # Perform request
        resp = await client.get(url, headers=headers, follow_redirects=True, timeout=5.0)
        
        # Check validation rules
        is_found = False
        
        # Rule: m_code / m_string (Must Not Contain/Match)
        if m_code and resp.status_code == m_code:
            return None
        if m_string and m_string in resp.text:
            return None

        # Rule: e_code / e_string (Must Contain/Match)
        if e_code and resp.status_code == e_code:
            is_found = True
        if e_string and e_string in resp.text:
            is_found = True

        # Fallback heuristic: 200 OK
        if not e_code and not e_string and not m_code and not m_string:
            if resp.status_code == 200:
                is_found = True

        if is_found:
            return {
                "site_name": name,
                "url": url,
                "status": "found"
            }
    except httpx.HTTPError:
        pass
    except Exception:
        pass

    return None


async def run_whatsmyname(
    username: str,
    scan_id: str,
    progress_callback: Optional[Callable] = None,
    proxy_url: Optional[str] = None
) -> Dict:
    """Run WMN scan asynchronously."""
    logger.info(f"Starting WhatsMyName scan for username: {username} (scan_id={scan_id})")

    # Set up client proxies if provided
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=30)
    mounts = {}
    if proxy_url:
        mounts = {"http://": httpx.HTTPTransport(proxy=proxy_url), "https://": httpx.HTTPTransport(proxy=proxy_url)}

    async with httpx.AsyncClient(limits=limits, mounts=mounts) as client:
        # Load database
        sites = await _load_wmn_database(client)
        
        # Limit checked sites to avoid scanning 600+ sites (too slow, rate limiting)
        # Select popular categories or shuffle/filter to top 150 sites
        popular_sites = [s for s in sites if s.get("name", "").lower() in [
            "github", "instagram", "reddit", "twitter", "pinterest", "steam", "soundcloud",
            "medium", "twitch", "deviantart", "wordpress", "ebay", "flickr", "vimeo", "tumblr",
            "keybase", "patreon", "spotify", "dockerhub", "gitlab", "npm", "pypi", "behance",
            "about.me", "scribd", "slideshare", "vsco", "wattpad", "wikipedia", "hackernews"
        ]]
        
        # Keep popular ones first, then add others up to 100 sites total
        popular_names = {s.get("name", "").lower() for s in popular_sites}
        other_sites = [s for s in sites if s.get("name", "").lower() not in popular_names]
        
        scan_list = popular_sites + other_sites[:70]
        total_sites = len(scan_list)
        
        checked = 0
        found_list = []
        
        # Set up concurrency limits
        semaphore = asyncio.Semaphore(15)
        
        async def worker(site):
            nonlocal checked
            async with semaphore:
                res = await check_site(client, site, username, proxy_url)
                checked += 1
                if res:
                    found_list.append(res)
                    log_scan_message(scan_id, f"🔍 WhatsMyName: [+] {res['site_name']}: {res['url']}")
                
                # Progress updates (throttle to avoid overloading pubsub)
                if progress_callback and (checked % 5 == 0 or checked == total_sites):
                    await progress_callback(
                        "whatsmyname",
                        "running",
                        len(found_list),
                        total_sites
                    )
                return res

        tasks = [worker(s) for s in scan_list]
        
        await asyncio.gather(*tasks)
        found_accounts = found_list

        logger.info(f"WhatsMyName completed: {len(found_accounts)} accounts found")
        
        if progress_callback:
            await progress_callback(
                "whatsmyname",
                "completed",
                len(found_accounts),
                total_sites
            )

        return {
            "tool_name": "whatsmyname",
            "status": "completed",
            "sites_found": len(found_accounts),
            "sites_checked": total_sites,
            "accounts": found_accounts,
        }
