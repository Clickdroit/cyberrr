import os
import json
import logging

logger = logging.getLogger(__name__)

SETTINGS_DIR = os.getenv("SETTINGS_DIR", "/data/config")
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULT_SETTINGS = {
    "hibp_api_key": "",
    "proxy_url": "",
    "ghunt_cookies": "",
    "shodan_api_key": ""
}

def load_settings() -> dict:
    """Load settings from JSON file, falling back to environment variables."""
    settings = DEFAULT_SETTINGS.copy()
    
    # 1. Load from file if exists
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                for k in DEFAULT_SETTINGS:
                    if k in loaded:
                        settings[k] = loaded[k]
        except Exception as e:
            logger.error(f"Error reading settings file: {e}")

    # 2. Fallbacks to environment variables if still empty
    if not settings["hibp_api_key"]:
        settings["hibp_api_key"] = os.getenv("HIBP_API_KEY", "")
    if not settings["proxy_url"]:
        settings["proxy_url"] = os.getenv("PROXY_URL", "")
    if not settings["shodan_api_key"]:
        settings["shodan_api_key"] = os.getenv("SHODAN_API_KEY", "")

    # For GHunt cookies, check the cookies path
    if not settings["ghunt_cookies"]:
        cookies_path = os.getenv("GHUNT_COOKIES_PATH", "/app/config/ghunt_cookies.json")
        if os.path.exists(cookies_path):
            try:
                with open(cookies_path, "r", encoding="utf-8") as f:
                    # Keep it as formatted string
                    settings["ghunt_cookies"] = f.read()
            except Exception:
                pass
                
    return settings

def save_settings(new_settings: dict):
    """Save settings to the configuration file and update files like ghunt_cookies.json if needed."""
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        
        # We save HIBP key, Proxy URL and Shodan key in settings.json to keep it clean
        to_save = {
            "hibp_api_key": new_settings.get("hibp_api_key", "").strip(),
            "proxy_url": new_settings.get("proxy_url", "").strip(),
            "shodan_api_key": new_settings.get("shodan_api_key", "").strip()
        }
        
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(to_save, f, indent=4)
            
        # If ghunt_cookies is provided, write it directly to the GHunt cookies file
        ghunt_cookies_raw = new_settings.get("ghunt_cookies", "").strip()
        if ghunt_cookies_raw:
            cookies_path = os.getenv("GHUNT_COOKIES_PATH", "/app/config/ghunt_cookies.json")
            os.makedirs(os.path.dirname(cookies_path), exist_ok=True)
            with open(cookies_path, "w", encoding="utf-8") as f:
                f.write(ghunt_cookies_raw)
                
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        raise e

def get_setting(key: str, default: str = "") -> str:
    """Helper to get a single configuration setting."""
    settings = load_settings()
    return settings.get(key, default)
