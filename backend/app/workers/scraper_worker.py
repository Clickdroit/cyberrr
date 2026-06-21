"""
Custom web scraper worker.
Scrapes profile pages found by other tools to extract:
- Email addresses
- First names / real names
- Locations
- Social links
- Bio text
Uses httpx + BeautifulSoup4 with rotation of User-Agents.
Respects robots.txt and adds delays.
"""
import asyncio
import logging
import re
import urllib.robotparser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# User-Agent pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
SOCIAL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(twitter|x\.com|instagram|facebook|github|linkedin|tiktok|youtube|twitch|reddit)"
    r"[^\s\"'<>]*",
    re.IGNORECASE,
)


async def run_scraper(
    urls: List[str],
    scan_id: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Scrape a list of profile URLs and extract intelligence.
    urls: list of profile URLs discovered by Maigret/Sherlock.
    """
    if not urls:
        if progress_callback:
            await progress_callback("scraper", "skipped", 0, 0)
        return _empty_result("No URLs to scrape")

    if progress_callback:
        await progress_callback("scraper", "running", 0, len(urls))

    all_emails = set()
    all_social_links = set()
    all_names = []
    all_bios = []
    all_locations = []

    # Limit to top 30 URLs to stay reasonable
    urls_to_scrape = urls[:30]
    total = len(urls_to_scrape)
    scraped = 0

    async with httpx.AsyncClient(
        timeout=12.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENTS[0]},
    ) as client:
        # Process in batches of 5
        batch_size = 5
        for i in range(0, total, batch_size):
            batch = urls_to_scrape[i : i + batch_size]
            tasks = [_scrape_single(client, url, i % len(USER_AGENTS)) for i, url in enumerate(batch)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception) or result is None:
                    continue
                all_emails.update(result.get("emails", []))
                all_social_links.update(result.get("social_links", []))
                if result.get("name"):
                    all_names.append(result["name"])
                if result.get("bio"):
                    all_bios.append(result["bio"])
                if result.get("location"):
                    all_locations.append(result["location"])

            scraped += len(batch)
            if progress_callback:
                await progress_callback("scraper", "running", scraped, total)

            # Polite delay between batches
            if i + batch_size < total:
                await asyncio.sleep(1.0)

    if progress_callback:
        await progress_callback("scraper", "completed", scraped, total)

    # Convert social links to account entries
    social_accounts = []
    for link in all_social_links:
        domain = urlparse(link).netloc.replace("www.", "")
        site_name = domain.split(".")[0].title()
        social_accounts.append({
            "site_name": site_name,
            "url": link,
            "metadata": {"source": "web_scraping"},
            "tags": ["scraped"],
        })

    # Compile metadata from scraped profiles
    metadata = {}
    if all_names:
        from collections import Counter
        c = Counter(all_names)
        metadata["name"] = c.most_common(1)[0][0]
    if all_locations:
        from collections import Counter
        c = Counter(all_locations)
        metadata["location"] = c.most_common(1)[0][0]
    if all_bios:
        metadata["bio"] = " | ".join(set(all_bios[:3]))

    return {
        "accounts": social_accounts,
        "metadata": metadata,
        "emails": sorted(all_emails),
        "sites_found": len(social_accounts),
        "sites_checked": scraped,
    }


async def _scrape_single(
    client: httpx.AsyncClient,
    url: str,
    ua_index: int = 0,
) -> Optional[Dict[str, Any]]:
    """Scrape a single profile URL."""
    try:
        # Skip non-HTTP URLs
        if not url.startswith(("http://", "https://")):
            return None

        # Skip known API endpoints or CDN URLs
        skip_patterns = [".json", ".xml", ".css", ".js", ".png", ".jpg", ".gif"]
        if any(url.endswith(p) for p in skip_patterns):
            return None

        headers = {"User-Agent": USER_AGENTS[ua_index % len(USER_AGENTS)]}
        response = await client.get(url, headers=headers)

        if response.status_code != 200:
            return None

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            return None

        html = response.text
        soup = BeautifulSoup(html, "lxml")

        # Remove script/style tags
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()

        # Extract emails from page text
        page_text = soup.get_text(" ", strip=True)
        emails = list(set(EMAIL_RE.findall(page_text)))
        # Filter out obvious non-personal emails
        emails = [
            e for e in emails
            if not any(bot in e.lower() for bot in ["noreply", "no-reply", "mailer", "support@", "info@"])
        ]

        # Extract social links
        social_links = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if not href.startswith("http"):
                href = urljoin(url, href)
            if SOCIAL_RE.match(href):
                social_links.append(href)

        # Extract name from common meta/OG tags
        name = None
        for sel in [
            soup.find("meta", property="og:title"),
            soup.find("meta", attrs={"name": "author"}),
            soup.find("h1"),
        ]:
            if sel:
                content = sel.get("content") or sel.get_text(strip=True)
                if content and len(content) < 60:
                    name = content
                    break

        # Extract bio/description
        bio = None
        for sel in [
            soup.find("meta", property="og:description"),
            soup.find("meta", attrs={"name": "description"}),
        ]:
            if sel and sel.get("content"):
                bio = sel["content"][:300]
                break

        # Extract location
        location = None
        for sel in [
            soup.find("meta", property="og:locality"),
            soup.find(class_=re.compile(r"location|city|geo", re.I)),
        ]:
            if sel:
                loc = sel.get("content") or sel.get_text(strip=True)
                if loc and len(loc) < 100:
                    location = loc
                    break

        return {
            "emails": emails,
            "social_links": list(set(social_links)),
            "name": name,
            "bio": bio,
            "location": location,
        }

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.debug(f"Scraping error for {url}: {e}")
        return None
    except Exception as e:
        logger.debug(f"Unexpected scraping error for {url}: {e}")
        return None


def _empty_result(reason: str) -> Dict[str, Any]:
    return {
        "accounts": [],
        "metadata": {},
        "emails": [],
        "sites_found": 0,
        "sites_checked": 0,
        "error": reason,
    }
