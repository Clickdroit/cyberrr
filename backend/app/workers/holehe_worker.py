"""
Holehe OSINT worker — email-to-service registration checker.
Uses Holehe's native async Python API with httpx.
Checks ~120 services to see if an email is registered.
"""
import asyncio
import importlib
import logging
import pkgutil
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


async def run_holehe(
    email: str,
    scan_id: str,
    progress_callback=None,
) -> Dict[str, Any]:
    """
    Run Holehe email check across all available modules.
    Returns standardized dict.
    """
    registered_sites = []
    all_results = []

    try:
        import httpx
        import holehe
        import holehe.modules

        # Dynamically discover all Holehe modules
        modules = _discover_holehe_modules()

        if not modules:
            if progress_callback:
                await progress_callback("holehe", "skipped", 0, 0)
            return _empty_result("No Holehe modules found")

        total = len(modules)
        if progress_callback:
            await progress_callback("holehe", "running", 0, total)

        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            },
        ) as client:
            # Run modules in batches to avoid rate limiting
            batch_size = 10
            found_count = 0

            for i in range(0, total, batch_size):
                batch = modules[i : i + batch_size]
                tasks = []

                for module_func in batch:
                    out = []
                    tasks.append(_run_single_module(module_func, email, client, out))

                batch_outputs = await asyncio.gather(*tasks, return_exceptions=True)

                for j, result in enumerate(batch_outputs):
                    if isinstance(result, Exception):
                        continue
                    if result:
                        all_results.extend(result)
                        for item in result:
                            if item.get("exists") and not item.get("rateLimit"):
                                found_count += 1
                                site_name = item.get("name", "Unknown")
                                registered_sites.append({
                                    "site_name": site_name,
                                    "url": _get_site_url(site_name),
                                    "metadata": {
                                        "email_recovery": item.get("emailrecovery"),
                                        "phone_hint": item.get("phoneNumber"),
                                        "other": item.get("others"),
                                    },
                                })

                checked = min(i + batch_size, total)
                if progress_callback:
                    await progress_callback("holehe", "running", found_count, total)

                # Small delay between batches to be respectful
                if i + batch_size < total:
                    await asyncio.sleep(0.5)

        if progress_callback:
            await progress_callback("holehe", "completed", found_count, total)

        return {
            "accounts": registered_sites,
            "metadata": {},
            "emails": [email],
            "sites_found": found_count,
            "sites_checked": total,
        }

    except ImportError:
        logger.warning("Holehe not installed — skipping")
        if progress_callback:
            await progress_callback("holehe", "skipped", 0, 0)
        return _empty_result("Holehe not installed")

    except Exception as e:
        logger.error(f"Holehe error: {e}", exc_info=True)
        if progress_callback:
            await progress_callback("holehe", "failed", 0, 0)
        return _empty_result(str(e))


async def _run_single_module(module_func, email: str, client, out: list):
    """Run a single Holehe module safely."""
    try:
        await module_func(email, client, out)
        return out
    except Exception as e:
        logger.debug(f"Holehe module error ({module_func.__name__}): {e}")
        return []


def _discover_holehe_modules() -> List:
    """Dynamically discover all Holehe module functions."""
    modules = []
    try:
        import holehe.modules as holehe_modules

        for importer, modname, ispkg in pkgutil.walk_packages(
            path=holehe_modules.__path__,
            prefix=holehe_modules.__name__ + ".",
            onerror=lambda x: None,
        ):
            if not ispkg:
                try:
                    module = importlib.import_module(modname)
                    # Function name = last part of module path
                    func_name = modname.split(".")[-1]
                    func = getattr(module, func_name, None)
                    if callable(func):
                        modules.append(func)
                except Exception as e:
                    logger.debug(f"Could not load Holehe module {modname}: {e}")
    except Exception as e:
        logger.warning(f"Could not discover Holehe modules: {e}")

    return modules


def _get_site_url(site_name: str) -> str:
    """Best-effort URL reconstruction for a site name."""
    # Map common site names to their URLs
    url_map = {
        "twitter": "https://twitter.com",
        "instagram": "https://instagram.com",
        "facebook": "https://facebook.com",
        "github": "https://github.com",
        "reddit": "https://reddit.com",
        "tumblr": "https://tumblr.com",
        "pinterest": "https://pinterest.com",
        "spotify": "https://spotify.com",
        "snapchat": "https://snapchat.com",
        "discord": "https://discord.com",
        "twitch": "https://twitch.tv",
        "wordpress": "https://wordpress.com",
        "adobe": "https://adobe.com",
        "amazon": "https://amazon.com",
        "netflix": "https://netflix.com",
        "paypal": "https://paypal.com",
    }
    name_lower = site_name.lower()
    for key, url in url_map.items():
        if key in name_lower:
            return url
    return f"https://{site_name.lower().replace(' ', '')}.com"


def _empty_result(reason: str) -> Dict[str, Any]:
    return {
        "accounts": [],
        "metadata": {},
        "emails": [],
        "sites_found": 0,
        "sites_checked": 0,
        "error": reason,
    }
