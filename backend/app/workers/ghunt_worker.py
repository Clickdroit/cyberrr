"""
GHunt OSINT worker — Google account intelligence extraction.
Requires valid Google authentication cookies (configured via env).
Gracefully degrades if cookies are not configured.
"""
import asyncio
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

GHUNT_COOKIES_PATH = os.getenv("GHUNT_COOKIES_PATH", "/app/config/ghunt_cookies.json")


async def run_ghunt(
    email: str,
    scan_id: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Run GHunt to extract Google account intelligence.
    
    GHunt v2 requires authentication cookies. If not configured,
    this worker is silently skipped.
    
    To configure:
    1. Install GHunt: pip install ghunt
    2. Run: ghunt login  (follow the browser flow)
    3. Cookies are saved automatically by GHunt
    """
    if not _ghunt_available():
        if progress_callback:
            await progress_callback("ghunt", "skipped", 0, 0)
        return _empty_result("GHunt not configured (cookies required — see README)")

    if progress_callback:
        await progress_callback("ghunt", "running", 0, 1)

    try:
        # GHunt v2 uses its own async API
        # This is a subprocess wrapper since GHunt's internal API changes frequently
        import subprocess
        import sys
        import tempfile

        output_file = tempfile.mktemp(suffix=".json")

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "ghunt", "email",
            email,
            "--json", output_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ},
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            logger.warning(f"GHunt exited with code {proc.returncode}: {error_msg}")
            if progress_callback:
                await progress_callback("ghunt", "failed", 0, 1)
            return _empty_result(f"GHunt error: {error_msg[:200]}")

        # Parse JSON output
        result = {}
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                result = json.load(f)
            try:
                os.remove(output_file)
            except Exception:
                pass

        # Extract structured data
        google_data = _parse_ghunt_output(result)

        if progress_callback:
            await progress_callback("ghunt", "completed", 1, 1)

        return google_data

    except asyncio.TimeoutError:
        logger.warning("GHunt timed out")
        if progress_callback:
            await progress_callback("ghunt", "failed", 0, 1)
        return _empty_result("GHunt timed out after 60s")

    except Exception as e:
        logger.error(f"GHunt error: {e}", exc_info=True)
        if progress_callback:
            await progress_callback("ghunt", "failed", 0, 1)
        return _empty_result(str(e))


def _ghunt_available() -> bool:
    """Check if GHunt is installed and cookies are configured."""
    try:
        import ghunt  # noqa: F401

        # Check if GHunt has been authenticated
        # GHunt stores credentials in its own config dir
        ghunt_config = os.path.expanduser("~/.config/ghunt")
        if os.path.exists(ghunt_config):
            creds = [f for f in os.listdir(ghunt_config) if f.endswith(".json")]
            if creds:
                return True

        # Check custom cookies path
        if os.path.exists(GHUNT_COOKIES_PATH):
            return True

        return False
    except ImportError:
        return False


def _parse_ghunt_output(raw: Dict) -> Dict[str, Any]:
    """Parse GHunt v2 JSON output into our standardized format."""
    accounts = []
    metadata = {}
    emails_found = []

    if not raw:
        return _empty_result("No data returned by GHunt")

    # Extract profile info
    profile = raw.get("profile", raw)
    name = profile.get("name", profile.get("full_name", ""))
    photo = profile.get("profile_picture_url", profile.get("picture", ""))
    google_id = profile.get("google_id", raw.get("id", ""))

    if name:
        metadata["name"] = name
    if photo:
        metadata["profile_picture"] = photo
    if google_id:
        metadata["google_id"] = google_id

    # Google Maps reviews
    maps_data = raw.get("maps", {})
    if maps_data:
        metadata["maps_reviews_count"] = maps_data.get("reviews_count", 0)
        metadata["maps_photos_count"] = maps_data.get("photos_count", 0)
        if maps_data.get("city"):
            metadata["location"] = maps_data["city"]

    # YouTube channel
    youtube = raw.get("youtube", {})
    if youtube and youtube.get("channel_id"):
        accounts.append({
            "site_name": "YouTube",
            "url": f"https://youtube.com/channel/{youtube['channel_id']}",
            "metadata": {"channel_id": youtube.get("channel_id")},
            "tags": ["google", "video"],
        })

    # Calendar (public)
    calendar = raw.get("calendar", {})
    if calendar and calendar.get("public_url"):
        metadata["google_calendar"] = calendar["public_url"]

    return {
        "accounts": accounts,
        "metadata": metadata,
        "emails": emails_found,
        "sites_found": len(accounts),
        "sites_checked": 1,
        "google_data": raw,
    }


def _empty_result(reason: str) -> Dict[str, Any]:
    return {
        "accounts": [],
        "metadata": {},
        "emails": [],
        "sites_found": 0,
        "sites_checked": 0,
        "error": reason,
    }
