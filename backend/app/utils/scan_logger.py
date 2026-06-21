import os
from datetime import datetime

REPORTS_DIR = os.getenv("REPORTS_DIR", "/data/reports")

def log_scan_message(scan_id: str, message: str):
    """Append a log message to the scan's log file."""
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
        log_file = os.path.join(REPORTS_DIR, f"scan_{scan_id}.log")
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass

def get_scan_logs(scan_id: str) -> str:
    """Read the logs of a scan."""
    log_file = os.path.join(REPORTS_DIR, f"scan_{scan_id}.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return "Erreur lors de la lecture du fichier de log."
    return "Aucun log disponible pour cette recherche."
