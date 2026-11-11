"""
Email, Order ID, and Package extraction module using regular expressions.
Parses, sanitizes, and normalizes email addresses, Order IDs, and package text from messages.
Includes extract_last_email helper for Loader caption email overrides.
"""

import re
import logging
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Universal email format regex: validates structure (local@domain.tld) for ANY valid domain & TLD
EMAIL_REGEX = re.compile(
    r'(?<![A-Za-z0-9._%+@-])'
    r'[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*'
    r'@'
    r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+'
    r'[A-Za-z]{2,}'
    r'(?![A-Za-z0-9_@-])',
    re.IGNORECASE
)

# Regex pattern for extracting Order ID numbers (e.g. "Order ID: #10025", "Order #10025", "#10025", "Order ID 10025")
ORDER_ID_REGEX = re.compile(
    r'(?:order\s*id|order\s*#|order|#)\s*[:#\s]*(\d+)',
    re.IGNORECASE
)


def extract_email(text: Optional[str]) -> Optional[str]:
    """
    Extracts the first valid email address found in the provided text.
    Strips trailing punctuation and normalizes to lowercase.

    Args:
        text (str, optional): The input string to scan (message text or caption).

    Returns:
        Optional[str]: The normalized (lowercase, trimmed) email address if found, else None.
    """
    if not text:
        return None

    match = EMAIL_REGEX.search(text)
    if match:
        raw_email = match.group(0).strip()
        email = raw_email.rstrip(".,;!)]>").lower()
        logger.debug(f"Extracted email: '{email}' from text.")
        return email

    return None


def extract_last_email(text: Optional[str]) -> Optional[str]:
    """
    Scans text for all valid email addresses and returns the LAST valid email address found.
    Normalizes to lowercase and strips trailing punctuation.

    Args:
        text (str, optional): The input string to scan (loader caption/text).

    Returns:
        Optional[str]: The last normalized email address if found, else None.
    """
    if not text:
        return None

    matches = EMAIL_REGEX.findall(text)
    if not matches:
        return None

    last_raw = matches[-1].strip()
    email = last_raw.rstrip(".,;!)]>").lower()
    logger.debug(f"Extracted last email override: '{email}' from text.")
    return email


def extract_order_id(text: Optional[str]) -> Optional[int]:
    """
    Extracts an Order ID integer from text or message captions.

    Args:
        text (str, optional): Input text string.

    Returns:
        Optional[int]: Order ID integer if found, else None.
    """
    if not text:
        return None

    match = ORDER_ID_REGEX.search(text)
    if match:
        try:
            order_id = int(match.group(1))
            logger.debug(f"Extracted Order ID: {order_id} from text.")
            return order_id
        except ValueError:
            pass

    return None


HEADER_KEYWORDS = {
    "login", "password", "pass", "nickname", "nick", "email",
    "uid", "id", "user", "username", "account", "credentials",
    "wallet", "address", "network"
}


# Exact supported Double CP Event combinations: (left, right) -> (canonical_combo, total_cp)
DOUBLE_CP_COMBINATIONS: Dict[Tuple[int, int], Tuple[str, int]] = {
    (80, 80): ("80+80", 160),
    (400, 400): ("400+400", 800),
    (800, 800): ("800+800", 1600),
    (2000, 2000): ("2000+2000", 4000),
    (4000, 4000): ("4000+4000", 8000),
    (8000, 8000): ("8000+8000", 16000),
    # Short customer inputs
    (2, 2): ("2000+2000", 4000),
    (4, 4): ("4000+4000", 8000),
    (8, 8): ("8000+8000", 16000),
}

# Labels that indicate a standalone number is a price, password, UID, or phone rather than a CP package
NON_CP_NUMBER_PREFIX_RE = re.compile(
    r'(?:\b(?:price|rs|pkr|usd|inr|eur|gbp|total|amount|uid|id|pass|password|pin|code|phone|tel|mobile|order)\b[:\s.\-]*|[$€£₹]\s*)$',
    re.IGNORECASE
)


def extract_double_cp_package(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Detects Double CP Event combinations (full, comma, k-notation, optional CP suffix, and short forms 2+2/4+4/8+8).
    Masks emails first so '+' inside emails never matches.
    Returns dict with 'combination', 'total_cp', and 'formatted', or None if no supported Double CP combination exists.
    """
    if not text:
        return None

    from keywords import normalize_cp_text

    text_no_email = EMAIL_REGEX.sub(" ", text)
    normalized = normalize_cp_text(text_no_email)

    for match in re.finditer(r'(?<![.\-+\d])\b(\d+)\s*\+\s*(\d+)(?:\s*CP)?\b(?![.\-+\d])', normalized, re.IGNORECASE):
        try:
            left = int(match.group(1))
            right = int(match.group(2))
        except ValueError:
            continue

        entry = DOUBLE_CP_COMBINATIONS.get((left, right))
        if entry:
            combo, total_cp = entry
            return {
                "combination": combo,
                "total_cp": total_cp,
                "formatted": f"Double CP: {combo} (Total: {total_cp} CP)",
            }

    return None


def extract_valid_cp_package(text: Optional[str]) -> Optional[str]:
    """
    Strictly extracts either a supported Double CP Event combination or a supported normal CODM CP package.
    Double CP detection runs before normal standalone CP extraction.
    Email addresses are masked before scanning so digits inside an email never count as a package.
    Returns formatted package string if valid, else None.
    """
    if not text:
        return None

    # 1. Check Double CP Event combinations first
    double_cp = extract_double_cp_package(text)
    if double_cp:
        return double_cp["formatted"]

    from keywords import normalize_cp_text
    from config import Config

    # Mask emails so digits inside an email (e.g. player.5000@gmail.com) don't match as CP
    text_no_email = EMAIL_REGEX.sub(" ", text)
    normalized = normalize_cp_text(text_no_email)

    # 2. Explicit '<number> CP' matches (e.g. '5000 CP', '2,400 CP', '5K CP', '5000cp')
    for match in re.finditer(r'(?<![.\-+\d])\b(\d+)\s*CP\b(?![.\-+\d])', normalized, re.IGNORECASE):
        try:
            val = int(match.group(1))
            if val in Config.KNOWN_CP_PACKAGES:
                return f"{val} CP"
        except ValueError:
            pass

    # 3. Standalone integer matches in supported package catalog (e.g. '5000', '5k', '2.4k', '12k')
    for match in re.finditer(r'(?<![.\-+\d])\b(\d+)\b(?![.\-+\d])', normalized):
        try:
            val = int(match.group(1))
        except ValueError:
            continue

        if val not in Config.KNOWN_CP_PACKAGES:
            continue

        # Ignore standalone numbers immediately preceded by price/ID/credential/phone labels on the same line
        line_start = normalized.rfind("\n", 0, match.start()) + 1
        prefix_on_line = normalized[line_start:match.start()]
        if NON_CP_NUMBER_PREFIX_RE.search(prefix_on_line):
            continue

        return f"{val} CP"

    return None


def extract_package(text: Optional[str]) -> str:
    """
    Extracts package/item description from customer message.
    Normalizes text and prioritizes Double CP and explicit or known CP package detection.

    Args:
        text (str, optional): Input order message text.

    Returns:
        str: Package text description or default fallback.
    """
    if not text:
        return "Standard Package"

    double_cp = extract_double_cp_package(text)
    if double_cp:
        return double_cp["formatted"]

    from keywords import normalize_cp_text
    from config import Config

    normalized = normalize_cp_text(text)

    # 1. Search for explicit CP package match (e.g. "12000 CP", "12345 CP")
    cp_match = re.search(r'\b(\d+)\s*CP\b', normalized, re.IGNORECASE)
    if cp_match:
        return f"{cp_match.group(1)} CP"

    # 2. Search for known CP package number in text (e.g. 12000, 10800, 5000)
    for num_str in re.findall(r'\b(\d+)\b', normalized):
        try:
            val = int(num_str)
            if val in Config.KNOWN_CP_PACKAGES:
                return f"{val} CP"
        except ValueError:
            pass

    # 3. Look for explicit package header lines (e.g. "Package: ...", "Item: ...")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if EMAIL_REGEX.search(line):
            continue
        line_lower = line.lower()
        if line_lower.startswith(("package:", "item:", "order:")):
            val = line.split(":", 1)[-1].strip()
            if val:
                return val

    # 4. Filter out email lines and credential header lines
    candidate_lines = []
    for line in lines:
        if EMAIL_REGEX.search(line):
            continue
        clean_word = line.lower().rstrip(":")
        if clean_word in HEADER_KEYWORDS:
            continue
        candidate_lines.append(line)

    if candidate_lines:
        return " | ".join(candidate_lines[:2])

    return "Standard Package"


# Known CODM account login methods (case-insensitive, whole word)
LOGIN_METHODS: List[str] = ["Activision", "Facebook", "Google", "Apple", "Line", "VK", "Twitter", "Guest"]


def extract_login_method(text: Optional[str]) -> Optional[str]:
    """
    Extracts the account login method (e.g. 'Activision') from an order message.
    Returns the canonical method name, or None if no known method is mentioned.
    Parse-only helper: the value is not stored in the database.
    """
    if not text:
        return None
    for method in LOGIN_METHODS:
        if re.search(rf'\b{re.escape(method)}\b', text, re.IGNORECASE):
            return method
    return None
