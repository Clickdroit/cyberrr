"""
IP Address OSINT worker.
Queries open APIs (ip-api.com) for geolocation, ISP, hosting, and proxy/VPN detection.
"""
import logging
import httpx
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

async def run_ip_scan(
    ip: str,
    scan_id: str,
    progress_callback=None,
    proxy_url: Optional[str] = None
) -> Dict[str, Any]:
    """Perform geolocation and VPN/proxy detection on the target IP."""
    logger.info(f"Starting IP scan for target: {ip} (scan_id={scan_id})")

    if progress_callback:
        await progress_callback("ip_lookup", "running", 0, 1)

    metadata = {}
    try:
        # Use fields parameter to get proxy/hosting/mobile detection flags
        url = f"http://ip-api.com/json/{ip}?fields=status,message,country,countryCode,region,regionName,city,zip,lat,lon,timezone,isp,org,as,query,proxy,hosting,mobile"
        
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=5)
        mounts = {}
        if proxy_url:
            mounts = {"http://": httpx.HTTPTransport(proxy=proxy_url), "https://": httpx.HTTPTransport(proxy=proxy_url)}

        async with httpx.AsyncClient(limits=limits, mounts=mounts) as client:
            resp = await client.get(url, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "success":
                    metadata = {
                        "ip": data.get("query"),
                        "country": data.get("country", "Inconnu"),
                        "country_code": data.get("countryCode", ""),
                        "region": data.get("regionName", "Inconnu"),
                        "city": data.get("city", "Inconnu"),
                        "zip": data.get("zip", ""),
                        "lat": data.get("lat"),
                        "lon": data.get("lon"),
                        "timezone": data.get("timezone", ""),
                        "isp": data.get("isp", "Inconnu"),
                        "org": data.get("org", ""),
                        "asn": data.get("as", ""),
                        "is_proxy": data.get("proxy", False),
                        "is_hosting": data.get("hosting", False),
                        "is_mobile": data.get("mobile", False),
                        "valid": True
                    }
                    from app.utils.scan_logger import log_scan_message
                    log_scan_message(scan_id, f"📍 IP: Geolocation trouvée : {metadata['city']}, {metadata['country']} (ISP: {metadata['isp']})")
                    if metadata["is_proxy"]:
                        log_scan_message(scan_id, "⚠️ IP Warning: L'adresse IP est détectée comme étant un Proxy/VPN.")

                    # Query Shodan if API key is configured
                    from app.utils.settings import get_setting
                    shodan_key = get_setting("shodan_api_key")
                    shodan_info = {"configured": False}
                    
                    if shodan_key:
                        shodan_info["configured"] = True
                        log_scan_message(scan_id, "📍 IP: Interrogation passive de la base Shodan...")
                        try:
                            shodan_url = f"https://api.shodan.io/shodan/host/{ip}?key={shodan_key}"
                            async with httpx.AsyncClient(limits=limits, mounts=mounts) as shodan_client:
                                shodan_resp = await shodan_client.get(shodan_url, timeout=12.0)
                                if shodan_resp.status_code == 200:
                                    sdata = shodan_resp.json()
                                    
                                    services_list = []
                                    for item in sdata.get("data", []):
                                        services_list.append({
                                            "port": item.get("port"),
                                            "transport": item.get("transport", "tcp"),
                                            "product": item.get("product", ""),
                                            "version": item.get("version", ""),
                                            "info": item.get("info", "")
                                        })
                                        
                                    shodan_info.update({
                                        "success": True,
                                        "ports": sdata.get("ports", []),
                                        "vulns": sdata.get("vulns", []),
                                        "os": sdata.get("os", ""),
                                        "hostnames": sdata.get("hostnames", []),
                                        "services": services_list
                                    })
                                    log_scan_message(scan_id, f"📍 IP: Shodan a détecté {len(sdata.get('ports', []))} ports ouverts et {len(sdata.get('vulns', []))} vulnérabilités.")
                                elif shodan_resp.status_code == 404:
                                    shodan_info.update({
                                        "success": True,
                                        "ports": [],
                                        "vulns": [],
                                        "os": "",
                                        "hostnames": [],
                                        "services": []
                                    })
                                    log_scan_message(scan_id, "📍 IP: Aucune donnée trouvée pour cette adresse dans Shodan.")
                                else:
                                    shodan_info.update({
                                        "success": False,
                                        "error": f"API returned status {shodan_resp.status_code}"
                                    })
                                    log_scan_message(scan_id, f"⚠️ IP Warning: Échec de l'interrogation Shodan (Code: {shodan_resp.status_code})")
                        except Exception as se:
                            logger.error(f"Shodan query failed: {se}")
                            shodan_info.update({
                                "success": False,
                                "error": str(se)
                            })
                            log_scan_message(scan_id, f"⚠️ IP Warning: Échec de l'interrogation Shodan : {se}")
                    else:
                        log_scan_message(scan_id, "📍 IP: Shodan non configuré (clé API manquante).")

                    metadata["shodan"] = shodan_info
                else:
                    metadata = {"valid": False, "error": data.get("message", "IP lookup failed")}
            else:
                metadata = {"valid": False, "error": f"API returned status {resp.status_code}"}
    except Exception as e:
        logger.error(f"IP lookup failed: {e}", exc_info=True)
        metadata = {"valid": False, "error": str(e)}

    results = {
        "tool_name": "ip_lookup",
        "status": "completed" if metadata.get("valid") else "failed",
        "sites_found": 1 if metadata.get("valid") else 0,
        "sites_checked": 1,
        "metadata": metadata
    }

    if progress_callback:
        await progress_callback("ip_lookup", "completed", 1 if metadata.get("valid") else 0, 1)

    return results
