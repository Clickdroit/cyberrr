"""
Celery orchestrator — main task that coordinates all OSINT workers.
Dispatches sub-tasks based on target type and aggregates results.
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict

from celery import Task

from app.celery_app import celery_app
from app.utils.aggregator import DataAggregator
from app.utils.input_detector import detect_input_type, normalize_target
from app.utils.redis_pubsub import publish_event_sync
from app.utils.scan_logger import log_scan_message

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PROXY_URL = os.getenv("PROXY_URL", None)


def _publish(scan_id: str, event: str, data: dict):
    """Helper to publish event synchronously."""
    try:
        publish_event_sync(scan_id, event, data)
        # Log to file
        if event == "scan_started":
            log_scan_message(scan_id, f"🔍 Investigation démarrée — Cible: {data.get('target')} ({data.get('target_type')})")
        elif event == "scan_complete":
            summary = data.get("summary", {})
            log_scan_message(scan_id, f"✅ Scan terminé — {summary.get('total_accounts', 0)} comptes trouvés")
        elif event == "scan_failed":
            log_scan_message(scan_id, f"❌ Scan échoué: {data.get('error')}")
        elif event == "email_discovered":
            log_scan_message(scan_id, f"📧 Email découvert: {data.get('email')} (via {data.get('source')})")
    except Exception as e:
        logger.warning(f"Could not publish event: {e}")


def _make_progress_callback(scan_id: str, tool_name: str):
    """
    Returns a sync callback that publishes tool progress events.
    Celery workers are sync, so we wrap the async pubsub in asyncio.run.
    """
    def callback(tool: str, status: str, found: int, total: int):
        _publish(scan_id, "tool_update", {
            "tool": tool,
            "status": status,
            "sites_found": found,
            "sites_checked": total,
            "timestamp": datetime.utcnow().isoformat(),
        })
        # Log update to file
        emoji = "🤖"
        if tool == "maigret": emoji = "🔭"
        elif tool == "sherlock": emoji = "🕵️"
        elif tool == "whatsmyname": emoji = "🔍"
        elif tool == "hibp": emoji = "🔑"
        elif tool == "phone_lookup": emoji = "📞"
        
        status_map = {
            "pending": "En attente",
            "running": "En cours",
            "completed": "Terminé",
            "failed": "Échec",
            "skipped": "Non configuré/Passé"
        }
        status_fr = status_map.get(status, status)
        
        log_scan_message(scan_id, f"{emoji} {tool} : {status_fr} ({found}/{total} vérifiés)")
    return callback


def _run_async(coro):
    """Run an async coroutine from a sync Celery context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed loop")
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


@celery_app.task(bind=True, name="app.workers.orchestrator.run_scan", max_retries=1)
def run_scan(self: Task, scan_id: str, target: str, target_type: str = "auto") -> Dict[str, Any]:
    """
    Main Celery task that orchestrates all OSINT tools for a given target.
    Updates the DB and publishes WebSocket events throughout.
    """
    # Configure global proxies for standard HTTP libraries (maigret, holehe, scrapers)
    if PROXY_URL:
        os.environ["HTTP_PROXY"] = PROXY_URL
        os.environ["HTTPS_PROXY"] = PROXY_URL
        logger.info(f"[Scan {scan_id}] Configured global proxy environment: {PROXY_URL}")
        log_scan_message(scan_id, f"⚙️ Proxy global configuré : {PROXY_URL}")

    # Detect type if auto
    if target_type == "auto":
        target_type = detect_input_type(target)

    normalized = normalize_target(target, target_type)

    logger.info(f"[Scan {scan_id}] Starting — target={target!r}, type={target_type}")
    _publish(scan_id, "scan_started", {
        "target": target,
        "target_type": target_type,
        "timestamp": datetime.utcnow().isoformat(),
    })

    # Update DB status to running
    _update_db_status(scan_id, "running", target_type)

    aggregator = DataAggregator()
    all_results = {}

    try:
        if target_type in ("username", "unknown"):
            all_results = _run_username_scan(scan_id, normalized, aggregator)
        elif target_type == "email":
            all_results = _run_email_scan(scan_id, normalized, aggregator)
        elif target_type == "phone":
            all_results = _run_phone_scan(scan_id, normalized, aggregator)
        else:
            # Unknown — try username scan
            all_results = _run_username_scan(scan_id, normalized, aggregator)

        # Build final summary
        summary = aggregator.build_summary()

        # Persist to DB
        _save_to_db(scan_id, all_results, summary)

        logger.info(
            f"[Scan {scan_id}] Completed — "
            f"{summary['total_accounts']} accounts found"
        )

        _publish(scan_id, "scan_complete", {
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Send Webhook alerts
        _send_webhooks(target, target_type, summary)

        return {"status": "completed", "scan_id": scan_id, "summary": summary}

    except Exception as e:
        logger.error(f"[Scan {scan_id}] Failed: {e}", exc_info=True)
        _publish(scan_id, "scan_failed", {
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        })
        _update_db_status(scan_id, "failed")
        raise


def _run_username_scan(scan_id: str, username: str, aggregator: DataAggregator) -> Dict:
    """
    Run username scan: Maigret (deep) + Sherlock (broad) + WhatsMyName + Scraper.
    """
    from app.workers.maigret_worker import run_maigret
    from app.workers.sherlock_worker import run_sherlock
    from app.workers.whatsmyname_worker import run_whatsmyname
    from app.workers.scraper_worker import run_scraper

    results = {}
    callback = _make_progress_callback(scan_id, "maigret")

    # 1. Maigret — deep metadata extraction
    maigret_results = _run_async(
        run_maigret(
            username=username,
            scan_id=scan_id,
            progress_callback=_async_wrap(callback),
        )
    )
    results["maigret"] = maigret_results
    aggregator.ingest_tool_results("maigret", maigret_results)

    # 2. Sherlock — broad fast sweep, deduplicated
    maigret_urls = {acc["url"] for acc in maigret_results.get("accounts", [])}
    sherlock_callback = _make_progress_callback(scan_id, "sherlock")
    sherlock_results = _run_async(
        run_sherlock(
            username=username,
            scan_id=scan_id,
            existing_urls=maigret_urls,
            progress_callback=_async_wrap(sherlock_callback),
            proxy_url=PROXY_URL,
        )
    )
    results["sherlock"] = sherlock_results
    aggregator.ingest_tool_results("sherlock", sherlock_results)

    # 3. WhatsMyName — concurrent swift check
    wmn_callback = _make_progress_callback(scan_id, "whatsmyname")
    whatsmyname_results = _run_async(
        run_whatsmyname(
            username=username,
            scan_id=scan_id,
            progress_callback=_async_wrap(wmn_callback),
            proxy_url=PROXY_URL,
        )
    )
    results["whatsmyname"] = whatsmyname_results
    aggregator.ingest_tool_results("whatsmyname", whatsmyname_results)

    # 4. Scraper — enrich top profile pages
    all_urls = [acc["url"] for acc in maigret_results.get("accounts", [])]
    all_urls += [acc["url"] for acc in sherlock_results.get("accounts", [])]
    all_urls += [acc["url"] for acc in whatsmyname_results.get("accounts", [])]
    
    # Deduplicate keeping order
    seen_urls = set()
    deduped_urls = []
    for u in all_urls:
        if u not in seen_urls:
            seen_urls.add(u)
            deduped_urls.append(u)

    # Prioritize high-value platforms
    priority = ["twitter", "instagram", "github", "reddit", "linkedin"]
    deduped_urls = _prioritize_urls(deduped_urls, priority)

    if deduped_urls:
        scraper_callback = _make_progress_callback(scan_id, "scraper")
        scraper_results = _run_async(
            run_scraper(
                urls=deduped_urls[:25],
                scan_id=scan_id,
                progress_callback=_async_wrap(scraper_callback),
            )
        )
        results["scraper"] = scraper_results
        aggregator.ingest_tool_results("scraper", scraper_results)

        # If scraper found emails → pivot to email scan
        for email in scraper_results.get("emails", []):
            if "@" in email:
                _publish(scan_id, "email_discovered", {
                    "email": email,
                    "source": "web_scraping",
                })

    return results


def _run_email_scan(scan_id: str, email: str, aggregator: DataAggregator) -> Dict:
    """
    Run email scan: Holehe (registrations) + GHunt (Google account) + HIBP + Scraper.
    """
    from app.workers.holehe_worker import run_holehe
    from app.workers.ghunt_worker import run_ghunt
    from app.workers.hibp_worker import run_hibp
    from app.workers.scraper_worker import run_scraper

    results = {}
    
    # 1. Holehe — check 120+ services
    holehe_callback = _make_progress_callback(scan_id, "holehe")
    holehe_results = _run_async(
        run_holehe(
            email=email,
            scan_id=scan_id,
            progress_callback=_async_wrap(holehe_callback),
        )
    )
    results["holehe"] = holehe_results
    aggregator.ingest_tool_results("holehe", holehe_results)

    # 2. GHunt — Google-specific intelligence
    ghunt_callback = _make_progress_callback(scan_id, "ghunt")
    ghunt_results = _run_async(
        run_ghunt(
            email=email,
            scan_id=scan_id,
            progress_callback=_async_wrap(ghunt_callback),
        )
    )
    results["ghunt"] = ghunt_results
    aggregator.ingest_tool_results("ghunt", ghunt_results)

    # 3. HaveIBeenPwned — check data leaks
    hibp_callback = _make_progress_callback(scan_id, "hibp")
    hibp_results = _run_async(
        run_hibp(
            email=email,
            scan_id=scan_id,
            progress_callback=_async_wrap(hibp_callback),
            proxy_url=PROXY_URL,
        )
    )
    results["hibp"] = hibp_results
    aggregator.ingest_tool_results("hibp", hibp_results)

    # 4. Scraper on found account URLs
    all_urls = [acc["url"] for acc in holehe_results.get("accounts", [])]
    if all_urls:
        scraper_callback = _make_progress_callback(scan_id, "scraper")
        scraper_results = _run_async(
            run_scraper(
                urls=all_urls[:20],
                scan_id=scan_id,
                progress_callback=_async_wrap(scraper_callback),
            )
        )
        results["scraper"] = scraper_results
        aggregator.ingest_tool_results("scraper", scraper_results)

    return results


def _run_phone_scan(scan_id: str, phone: str, aggregator: DataAggregator) -> Dict:
    """
    Perform local phone number lookup using the phonenumbers library.
    Extracts geocoding, carrier, timezone, and formatting information.
    """
    logger.info(f"[Scan {scan_id}] Running phone lookup for {phone}")
    callback = _make_progress_callback(scan_id, "phone_lookup")
    
    # Notify start
    _run_async(_async_wrap(callback)("phone_lookup", "running", 0, 1))

    metadata = {}
    try:
        import phonenumbers
        from phonenumbers import geocoder, carrier, timezone

        parsed = phonenumbers.parse(phone, None)
        if phonenumbers.is_valid_number(parsed):
            # Formats
            formatted_e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            formatted_intl = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            formatted_nat = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
            
            # Geography & Carrier
            region = geocoder.description_for_number(parsed, "fr")
            carrier_name = carrier.name_for_number(parsed, "fr")
            zones = list(timezone.time_zones_for_number(parsed))

            metadata = {
                "valid": True,
                "e164": formatted_e164,
                "international": formatted_intl,
                "national": formatted_nat,
                "location": region or "Inconnu",
                "carrier": carrier_name or "Inconnu",
                "timezones": zones,
                "country_code": parsed.country_code,
                "national_number": parsed.national_number,
            }
        else:
            metadata = {
                "valid": False,
                "error": "Numéro de téléphone invalide selon les normes E.164"
            }
    except Exception as e:
        logger.error(f"Phone lookup error: {e}", exc_info=True)
        metadata = {
            "valid": False,
            "error": str(e)
        }

    results = {
        "tool_name": "phone_lookup",
        "status": "completed",
        "sites_found": 1 if metadata.get("valid") else 0,
        "sites_checked": 1,
        "metadata": metadata
    }

    aggregator.ingest_tool_results("phone_lookup", results)
    
    # Notify completion
    _run_async(_async_wrap(callback)("phone_lookup", "completed", 1 if metadata.get("valid") else 0, 1))

    return {"phone_lookup": results}


def _send_webhooks(target: str, target_type: str, summary: dict):
    """Send summary results to Discord or Telegram webhooks if configured."""
    import httpx
    
    discord_url = os.getenv("DISCORD_WEBHOOK_URL")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not (discord_url or (tg_token and tg_chat_id)):
        return

    accounts_count = summary.get("total_accounts", 0)
    identity = summary.get("top_identity_guess", "Inconnue")
    confidence = int((summary.get("confidence_score", 0.0)) * 100)
    
    # Format message
    msg = (
        f"🔭 **Rapport d'Investigation OSINT**\n"
        f"🎯 **Cible** : `{target}` ({target_type})\n"
        f"👥 **Identité estimée** : {identity} ({confidence}% de confiance)\n"
        f"🔗 **Profils trouvés** : {accounts_count} comptes détectés\n"
    )
    
    # List top 5 accounts if any
    accounts = summary.get("accounts", [])
    if accounts:
        msg += "\n**Top profils identifiés** :\n"
        for acc in accounts[:5]:
            msg += f"- {acc.get('site_name')}: {acc.get('url')}\n"

    # Send to Discord
    if discord_url:
        try:
            httpx.post(discord_url, json={"content": msg}, timeout=5.0)
            logger.info("Discord webhook sent successfully")
        except Exception as e:
            logger.warning(f"Failed to send Discord webhook: {e}")

    # Send to Telegram
    if tg_token and tg_chat_id:
        try:
            tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            tg_msg = msg.replace("**", "*")  # Convert markdown bold to telegram format
            httpx.post(tg_url, json={"chat_id": tg_chat_id, "text": tg_msg, "parse_mode": "Markdown"}, timeout=5.0)
            logger.info("Telegram notification sent successfully")
        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")



def _async_wrap(sync_callback):
    """Wrap a sync callback into an async one."""
    async def async_callback(*args, **kwargs):
        sync_callback(*args, **kwargs)
    return async_callback


def _prioritize_urls(urls: list, priority_keywords: list) -> list:
    """Sort URLs so high-value platforms appear first."""
    def score(url: str) -> int:
        url_lower = url.lower()
        for i, kw in enumerate(priority_keywords):
            if kw in url_lower:
                return i
        return len(priority_keywords)
    return sorted(urls, key=score)


def _update_db_status(scan_id: str, status: str, target_type: str = None):
    """Update scan status in the DB (sync wrapper using a new event loop)."""
    try:
        from sqlalchemy import create_engine, update
        from sqlalchemy.orm import sessionmaker
        from app.database import Scan, DB_PATH

        engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)

        with Session() as session:
            q = session.query(Scan).filter(Scan.id == scan_id).first()
            if q:
                q.status = status
                if target_type:
                    q.target_type = target_type
                if status == "completed":
                    q.completed_at = datetime.utcnow()
                session.commit()
    except Exception as e:
        logger.warning(f"DB status update failed: {e}")


def _save_to_db(scan_id: str, all_results: Dict, summary: Dict):
    """Persist aggregated results to the database."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import Scan, ScanResult, CorrelatedEntity, DB_PATH

        engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
        Session = sessionmaker(bind=engine)

        with Session() as session:
            # Update scan
            scan = session.query(Scan).filter(Scan.id == scan_id).first()
            if scan:
                scan.status = "completed"
                scan.completed_at = datetime.utcnow()
                scan.summary = summary

            # Save tool results
            for tool_name, result in all_results.items():
                existing = (
                    session.query(ScanResult)
                    .filter(ScanResult.scan_id == scan_id, ScanResult.tool_name == tool_name)
                    .first()
                )
                if existing:
                    existing.status = "failed" if result.get("error") else "completed"
                    existing.raw_data = result
                    existing.sites_found = result.get("sites_found", 0)
                    existing.sites_checked = result.get("sites_checked", 0)
                    existing.error_message = result.get("error")
                    existing.completed_at = datetime.utcnow()
                else:
                    sr = ScanResult(
                        scan_id=scan_id,
                        tool_name=tool_name,
                        status="failed" if result.get("error") else "completed",
                        raw_data=result,
                        sites_found=result.get("sites_found", 0),
                        sites_checked=result.get("sites_checked", 0),
                        error_message=result.get("error"),
                        completed_at=datetime.utcnow(),
                    )
                    session.add(sr)

            # Save correlated entities
            for fn, count in summary.get("firstnames", {}).items():
                session.add(CorrelatedEntity(
                    scan_id=scan_id,
                    entity_type="firstname",
                    value=fn,
                    occurrences=count,
                    confidence=min(1.0, count / 5),
                    sources=list(all_results.keys()),
                ))

            for loc, count in summary.get("locations", {}).items():
                session.add(CorrelatedEntity(
                    scan_id=scan_id,
                    entity_type="location",
                    value=loc,
                    occurrences=count,
                    confidence=min(1.0, count / 3),
                    sources=list(all_results.keys()),
                ))

            for email in summary.get("emails_found", []):
                session.add(CorrelatedEntity(
                    scan_id=scan_id,
                    entity_type="email",
                    value=email,
                    occurrences=1,
                    confidence=0.9,
                    sources=list(all_results.keys()),
                ))

            session.commit()

    except Exception as e:
        logger.error(f"DB save failed: {e}", exc_info=True)
