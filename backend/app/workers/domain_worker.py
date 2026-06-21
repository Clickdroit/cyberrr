"""
Domain OSINT worker.
Resolves DNS records, queries RDAP (JSON WHOIS replacement),
and performs basic subdomain énumération.
"""
import asyncio
import logging
import httpx
import aiodns
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COMMON_SUBDOMAINS = [
    "www", "mail", "dev", "blog", "admin", "api", "vpn", "shop", "portal",
    "secure", "webmail", "ftp", "cpanel", "test", "staging", "git", "support"
]

async def run_domain_scan(
    domain: str,
    scan_id: str,
    progress_callback=None,
    proxy_url: Optional[str] = None
) -> Dict[str, Any]:
    """Perform DNS queries, WHOIS/RDAP, and subdomain énumération."""
    logger.info(f"Starting domain scan for target: {domain} (scan_id={scan_id})")

    if progress_callback:
        await progress_callback("domain_lookup", "running", 0, 100)

    from app.utils.scan_logger import log_scan_message
    log_scan_message(scan_id, f"🌐 Domaine: Lancement de l'analyse sur {domain}...")

    loop = asyncio.get_event_loop()
    resolver = aiodns.DNSResolver(loop=loop)
    
    dns_records = {}
    whois_data = {}
    subdomains_found = []

    # 1. Resolve basic DNS records
    record_types = {
        "A": aiodns.error.DNSError,
        "AAAA": aiodns.error.DNSError,
        "MX": aiodns.error.DNSError,
        "TXT": aiodns.error.DNSError
    }
    
    log_scan_message(scan_id, "🌐 Domaine: Récupération des enregistrements DNS (A, AAAA, MX, TXT)...")
    for rtype in record_types:
        try:
            answers = await resolver.query(domain, rtype)
            if rtype == "A":
                dns_records["A"] = [ans.host for ans in answers]
            elif rtype == "AAAA":
                dns_records["AAAA"] = [ans.host for ans in answers]
            elif rtype == "MX":
                dns_records["MX"] = [f"{ans.host} (priorité {ans.priority})" for ans in answers]
            elif rtype == "TXT":
                dns_records["TXT"] = [ans.text for ans in answers]
        except aiodns.error.DNSError:
            dns_records[rtype] = []

    # 2. RDAP (WHOIS JSON API)
    log_scan_message(scan_id, "🌐 Domaine: Consultation de la base Whois/RDAP...")
    try:
        url = f"https://rdap.org/domain/{domain}"
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=5)
        mounts = {}
        if proxy_url:
            mounts = {"http://": httpx.HTTPTransport(proxy=proxy_url), "https://": httpx.HTTPTransport(proxy=proxy_url)}

        async with httpx.AsyncClient(limits=limits, mounts=mounts, follow_redirects=True) as client:
            resp = await client.get(url, timeout=12.0)
            if resp.status_code == 200:
                raw_rdap = resp.json()
                
                # Parse registrar
                registrar = "Inconnu"
                for entity in raw_rdap.get("entities", []):
                    if "registrar" in entity.get("roles", []):
                        # Find registrar name
                        vcard = entity.get("vcardArray", [])
                        if len(vcard) > 1:
                            for prop in vcard[1]:
                                if prop[0] == "fn":
                                    registrar = prop[3]
                                    break
                
                # Parse registration and expiration dates
                created_date = "Inconnue"
                expires_date = "Inconnue"
                for event in raw_rdap.get("events", []):
                    action = event.get("eventAction", "")
                    if action == "registration":
                        created_date = event.get("eventDate", "Inconnue").split("T")[0]
                    elif action == "expiration":
                        expires_date = event.get("eventDate", "Inconnue").split("T")[0]

                # Parse name servers
                nameservers = [ns.get("ldhName", "") for ns in raw_rdap.get("nameservers", [])]
                nameservers = [ns for ns in nameservers if ns]

                whois_data = {
                    "registrar": registrar,
                    "created_at": created_date,
                    "expires_at": expires_date,
                    "nameservers": nameservers,
                    "raw_rdap_url": url
                }
                log_scan_message(scan_id, f"🌐 Domaine: Registrar trouvé : {registrar} (Expire le: {expires_date})")
            else:
                logger.warning(f"RDAP returned status code {resp.status_code}")
                whois_data = {"error": f"RDAP status code {resp.status_code}"}
    except Exception as e:
        logger.error(f"RDAP query failed: {e}")
        whois_data = {"error": str(e)}

    # 3. Subdomain enumeration (Concurrently check 17 subdomains)
    log_scan_message(scan_id, "🌐 Domaine: Énumération de sous-domaines courants...")
    
    async def check_subdomain(sub):
        sub_fqdn = f"{sub}.{domain}"
        try:
            answers = await resolver.query(sub_fqdn, "A")
            ips = [ans.host for ans in answers]
            if ips:
                subdomains_found.append({
                    "subdomain": sub_fqdn,
                    "ips": ips
                })
                log_scan_message(scan_id, f"🌐 Domaine: [+] Sous-domaine trouvé : {sub_fqdn} -> {', '.join(ips)}")
        except Exception:
            pass

    tasks = [check_subdomain(sub) for sub in COMMON_SUBDOMAINS]
    await asyncio.gather(*tasks)

    results = {
        "tool_name": "domain_lookup",
        "status": "completed",
        "sites_found": len(subdomains_found),
        "sites_checked": len(COMMON_SUBDOMAINS),
        "dns_records": dns_records,
        "whois_data": whois_data,
        "subdomains": subdomains_found
    }

    if progress_callback:
        await progress_callback("domain_lookup", "completed", len(subdomains_found), len(COMMON_SUBDOMAINS))

    return results
