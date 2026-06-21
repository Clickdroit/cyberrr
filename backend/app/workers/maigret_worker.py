"""
Maigret OSINT worker — username search with deep metadata extraction.
Uses Maigret's native Python API (asyncio-based).
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from app.utils.scan_logger import log_scan_message

REPORTS_DIR = os.getenv("REPORTS_DIR", "/data/reports")


async def run_maigret(
    username: str,
    scan_id: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Run Maigret username search.
    Returns standardized dict: {accounts: [...], metadata: {...}, emails: [...]}
    """
    accounts = []
    metadata_collected = {}
    emails_found = []

    try:
        from maigret import search as maigret_search
        from maigret.sites import MaigretDatabase

        # Load Maigret's site database
        db = MaigretDatabase()
        # Try loading from default path
        try:
            db_path = None
            import maigret
            pkg_dir = os.path.dirname(maigret.__file__)
            db_path = os.path.join(pkg_dir, "resources", "data.json")
            if os.path.exists(db_path):
                db.load_from_path(db_path)
            else:
                db.load_from_internet()
        except Exception:
            db.load_from_internet()

        sites = db.ranked_sites_dict(top=500)
        total = len(sites)

        if progress_callback:
            await progress_callback("maigret", "running", 0, total)

        # Run search (Maigret is async-native)
        results = await maigret_search(
            username=username,
            site_dict=sites,
            logger=logger,
            is_parsing_enabled=True,
            timeout=10,
        )

        found_count = 0
        for site_name, result in results.items():
            status = result.get("status")
            if status and hasattr(status, "is_found") and status.is_found():
                found_count += 1
                url = result.get("url_user", "")
                log_scan_message(scan_id, f"🔭 Maigret: [+] {site_name}: {url}")

                # Extract profile metadata if available
                tags = result.get("tags", []) or []
                ids_data = result.get("ids_data", {}) or {}

                # Gather metadata from the profile
                site_metadata = {}
                for field in ["name", "bio", "location", "followers", "following",
                              "image", "created_at"]:
                    val = ids_data.get(field)
                    if val:
                        site_metadata[field] = val
                        if field == "name" and val:
                            metadata_collected.setdefault("names", []).append(str(val))
                        if field == "location" and val:
                            metadata_collected.setdefault("locations", []).append(str(val))
                        if field == "bio" and val:
                            metadata_collected.setdefault("bios", []).append(str(val))

                # Extract emails from ids_data
                for field in ["email", "emails"]:
                    val = ids_data.get(field)
                    if val:
                        if isinstance(val, list):
                            emails_found.extend(val)
                        else:
                            emails_found.append(str(val))

                accounts.append({
                    "site_name": site_name,
                    "url": url,
                    "metadata": site_metadata,
                    "tags": tags,
                })

                # Progress update every 10 found
                if found_count % 10 == 0 and progress_callback:
                    await progress_callback("maigret", "running", found_count, total)

        if progress_callback:
            await progress_callback("maigret", "completed", found_count, total)

        # Build best metadata from all profiles
        best_metadata = _merge_profile_metadata(metadata_collected)

        return {
            "accounts": accounts,
            "metadata": best_metadata,
            "emails": list(set(emails_found)),
            "sites_found": found_count,
            "sites_checked": total,
        }

    except ImportError as e:
        logger.warning(f"Maigret not installed or import error: {e}", exc_info=True)
        log_scan_message(scan_id, f"⚠️ Maigret absent ou erreur d'import : {e}")
        if progress_callback:
            await progress_callback("maigret", "skipped", 0, 0)
        return _empty_result(f"maigret not installed or import error: {e}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Maigret error: {e}", exc_info=True)
        log_scan_message(scan_id, f"❌ Maigret échec : {e}\n{tb}")
        if progress_callback:
            await progress_callback("maigret", "failed", 0, 0)
        return _empty_result(str(e))


def _merge_profile_metadata(collected: Dict[str, List]) -> Dict[str, Any]:
    """Merge metadata collected from multiple profiles into a single best guess."""
    from collections import Counter

    result = {}
    if collected.get("names"):
        # Most common non-empty name
        c = Counter(n for n in collected["names"] if n.strip())
        if c:
            result["name"] = c.most_common(1)[0][0]

    if collected.get("locations"):
        c = Counter(l for l in collected["locations"] if l.strip())
        if c:
            result["location"] = c.most_common(1)[0][0]

    if collected.get("bios"):
        # Concatenate all bios for extraction
        result["bio"] = " | ".join(set(collected["bios"][:5]))

    return result


def _empty_result(reason: str) -> Dict[str, Any]:
    return {
        "accounts": [],
        "metadata": {},
        "emails": [],
        "sites_found": 0,
        "sites_checked": 0,
        "error": reason,
    }
