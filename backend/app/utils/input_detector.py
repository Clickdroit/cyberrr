"""
Input type detector — automatically classifies a target string
as username, email, or phone number.
"""
import re
from typing import Literal

try:
    import phonenumbers
    PHONENUMBERS_AVAILABLE = True
except ImportError:
    PHONENUMBERS_AVAILABLE = False

InputType = Literal["username", "email", "phone", "ip", "domain", "unknown"]

# Email regex (RFC 5322 simplified)
EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# Phone-like patterns (E.164 or common formats)
PHONE_RE = re.compile(
    r"^[\+]?[(]?[0-9]{1,4}[)]?[-\s\./0-9]{6,14}$"
)

# IPv4 regex
IP_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)

# Domain name regex
DOMAIN_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
)


def detect_input_type(target: str) -> InputType:
    """
    Detect the type of the given target string.
    Order: email > ip > domain > phone > username.
    """
    target = target.strip()

    if EMAIL_RE.match(target):
        return "email"

    if IP_RE.match(target):
        return "ip"

    if DOMAIN_RE.match(target):
        return "domain"

    if PHONE_RE.match(target.replace(" ", "").replace("-", "")):
        if PHONENUMBERS_AVAILABLE:
            try:
                parsed = phonenumbers.parse(target, None)
                if phonenumbers.is_valid_number(parsed):
                    return "phone"
            except Exception:
                pass
        else:
            # Fallback heuristic: if it starts with + and has 10+ digits
            digits = re.sub(r"\D", "", target)
            if len(digits) >= 10 and target.startswith("+"):
                return "phone"

    # Validate as username (alphanumeric, dots, underscores, hyphens)
    if re.match(r"^[a-zA-Z0-9._\-]{2,50}$", target):
        return "username"

    return "unknown"


def normalize_target(target: str, target_type: InputType) -> str:
    """Normalize the target based on its type."""
    target = target.strip()
    if target_type == "email":
        return target.lower()
    if target_type == "phone":
        if PHONENUMBERS_AVAILABLE:
            try:
                parsed = phonenumbers.parse(target, None)
                return phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
            except Exception:
                pass
    return target
