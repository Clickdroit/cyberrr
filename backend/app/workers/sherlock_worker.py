"""
Sherlock OSINT worker — fast username detection across 400+ sites.
Uses subprocess to call Sherlock CLI and parses JSON output.
Deduplicates results against Maigret via URL normalization.
"""
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

REPORTS_DIR = os.getenv("REPORTS_DIR", "/data/reports")


def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication (strip trailing slashes, lowercase domain)."""
    url = url.strip().rstrip("/")
    # Lowercase the domain part
    match = re.match(r"(https?://)([^/]+)(.*)", url)
    if match:
        scheme, domain, path = match.groups()
        return f"{scheme}{domain.lower()}{path}"
    return url.lower()


async def run_sherlock(
    username: str,
    scan_id: str,
    existing_urls: Optional[Set[str]] = None,
    progress_callback=None,
    proxy_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run Sherlock via subprocess and parse results.
    existing_urls: set of URLs already found by other tools (for deduplication).
    """
    accounts = []
    emails_found = []
    existing_urls = existing_urls or set()
    normalized_existing = {_normalize_url(u) for u in existing_urls}

    output_file = os.path.join(REPORTS_DIR, f"sherlock_{scan_id}.json")
    os.makedirs(REPORTS_DIR, exist_ok=True)

    if progress_callback:
        await progress_callback("sherlock", "running", 0, 400)

    try:
        # Try to find sherlock executable
        sherlock_cmd = _find_sherlock_command()
        if not sherlock_cmd:
            if progress_callback:
                await progress_callback("sherlock", "skipped", 0, 0)
            return _empty_result("Sherlock not found in PATH")

        cmd = [
            *sherlock_cmd,
            username,
            "--json",
            "--output", output_file,
            "--timeout", "10",
            "--print-found",
        ]
        if proxy_url:
            cmd.extend(["--proxy", proxy_url])

        logger.info(f"Running Sherlock: {' '.join(cmd)}")

        # Run async subprocess
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )


        found_count = 0
        # Stream stdout to track progress in real time
        async for line in proc.stdout:
            decoded = line.decode("utf-8", errors="replace").strip()
            if "[+]" in decoded:
                found_count += 1
                if found_count % 20 == 0 and progress_callback:
                    await progress_callback("sherlock", "running", found_count, 400)

        await proc.wait()
        if proc.returncode != 0:
            stderr_bytes = await proc.stderr.read()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()
            logger.error(f"Sherlock exited with code {proc.returncode}. Stderr: {stderr_str}")

        # Parse JSON output file
        if os.path.exists(output_file):
            with open(output_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            for site_name, info in raw.items():
                if info.get("status") == "Claimed":
                    url = info.get("url_user", "")
                    norm = _normalize_url(url)
                    # Skip if already found by Maigret
                    if norm in normalized_existing:
                        continue

                    accounts.append({
                        "site_name": site_name,
                        "url": url,
                        "metadata": {},
                        "tags": [],
                    })
                    normalized_existing.add(norm)

            # Cleanup
            try:
                os.remove(output_file)
            except Exception:
                pass

        if progress_callback:
            await progress_callback(
                "sherlock", "completed", len(accounts) + found_count // 2, 400
            )

        return {
            "accounts": accounts,
            "metadata": {},
            "emails": emails_found,
            "sites_found": len(accounts),
            "sites_checked": 400,
        }

    except FileNotFoundError:
        logger.warning("Sherlock subprocess not found")
        if progress_callback:
            await progress_callback("sherlock", "skipped", 0, 0)
        return _empty_result("Sherlock not installed")

    except Exception as e:
        logger.error(f"Sherlock error: {e}", exc_info=True)
        if progress_callback:
            await progress_callback("sherlock", "failed", 0, 0)
        return _empty_result(str(e))


def _find_sherlock_command() -> Optional[List[str]]:
    """Try multiple ways to locate Sherlock."""
    # 1. Direct command
    for cmd in ["sherlock", "python -m sherlock"]:
        try:
            full_cmd = cmd.split() + ["--version"]
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                timeout=5,
            )
            if result.returncode in (0, 1):
                return cmd.split()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # 2. Python module
    try:
        result = subprocess.run(
            [sys.executable, "-m", "sherlock", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode in (0, 1):  # sherlock --version may return 1
            return [sys.executable, "-m", "sherlock"]
    except Exception:
        pass

    # 3. python -m sherlock_project
    try:
        result = subprocess.run(
            [sys.executable, "-m", "sherlock_project", "--version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode in (0, 1):
            return [sys.executable, "-m", "sherlock_project"]
    except Exception:
        pass

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
