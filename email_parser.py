"""
Email, Order ID, and Package extraction module using regular expressions.
Parses, sanitizes, and normalizes email addresses, Order IDs, and package text from messages.
Includes extract_last_email helper for Loader caption email overrides.
"""

import re
import logging
from typing import Optional, List, Dict, Any, Tuple, Union
from config import CATEGORY_A_NORMAL_CP_PRICES, CATEGORY_A_DOUBLE_CP_PRICES

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

# Labels that indicate a standalone number is a price, password, UID, order ID, or phone rather than a CP package
NON_CP_NUMBER_PREFIX_RE = re.compile(
    r'(?:\b(?:price|rs|pkr|usd|inr|eur|gbp|total|amount|uid|id|pass|password|pin|code|phone|tel|mobile)\b[:\s.\-]*|\border\s*(?:id|#)[:\s.\-]*|[$€£₹]\s*)$',
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


def extract_normal_cp_package(text: Optional[str]) -> Optional[str]:
    """
    Strictly extracts a supported Normal CODM CP package from text using Config.KNOWN_CP_PACKAGES.
    Email addresses are masked before scanning so digits inside an email never count as a package.
    Returns formatted '<val> CP' string if valid, else None.
    """
    if not text:
        return None

    from keywords import normalize_cp_text
    from config import Config

    # Mask emails so digits inside an email (e.g. player.5000@gmail.com) don't match as CP
    text_no_email = EMAIL_REGEX.sub(" ", text)
    normalized = normalize_cp_text(text_no_email)

    # 1. Explicit '<number> CP' matches (e.g. '5000 CP', '2,400 CP', '5K CP', '5000cp')
    for match in re.finditer(r'(?<![.\-+\d])\b(\d+)\s*CP\b(?![.\-+\d])', normalized, re.IGNORECASE):
        try:
            val = int(match.group(1))
            if val in Config.KNOWN_CP_PACKAGES:
                return f"{val} CP"
        except ValueError:
            pass

    # 2. Standalone integer matches in supported package catalog (e.g. '5000', '5k', '2.4k', '12k')
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


def extract_valid_cp_package(text: Optional[str]) -> Optional[str]:
    """
    Strictly extracts either a supported Double CP Event combination or a supported normal CODM CP package.
    Double CP detection runs before normal standalone CP extraction.
    Returns formatted package string if valid, else None.
    """
    if not text:
        return None

    double_cp = extract_double_cp_package(text)
    if double_cp:
        return double_cp["formatted"]

    return extract_normal_cp_package(text)


def is_valid_phone_or_username(val: Optional[str]) -> bool:
    """
    Validates if a string is a valid phone number, email, or Facebook username.
    """
    if not val:
        return False
    val = val.strip()
    # Check email
    if extract_email(val):
        return True
    # Check phone number (7 to 15 digits)
    digits = re.sub(r'\D', '', val)
    # A phone number or numeric ID must have 7 to 15 digits and cannot be all zeros
    if val.isdigit() or (val.startswith("+") and val[1:].isdigit()):
        if 7 <= len(digits) <= 15 and digits != "0" * len(digits):
            return True
        return False
    if re.match(r'^\+?[\d\s\-()]+$', val):
        if 7 <= len(digits) <= 15 and digits != "0" * len(digits):
            return True
        return False
    # Check username (alphanumeric, dot, underscore, hyphen, 3-50 chars)
    # A username must contain at least one letter and cannot be pure numbers
    if re.match(r'^[A-Za-z0-9._\-]{3,50}$', val):
        if any(c.isalpha() for c in val):
            reserved = {
                "facebook", "fb", "password", "pass", "activision", "login",
                "order", "fast", "recharge", "codm", "cp", "code", "codes",
                "backup", "auth", "otp", "2fa", "number", "num", "phone",
                "mobile", "contact", "user", "username", "account", "email",
                "price", "item", "package", "id", "uid", "name"
            }
            if val.lower() not in reserved:
                return True
    return False


def extract_facebook_password(text: Optional[str]) -> Optional[str]:
    """
    Extracts the password value for a Facebook order.
    Returns the password token if present, non-empty, and not a CP package or keyword.
    """
    if not text:
        return None
    match = re.search(r'\b(?:pass(?:word)?|pwd|psw|pas)\s*[:=\-]?\s*([^\r\n]+)', text, re.IGNORECASE)
    if not match:
        return None
    val_line = match.group(1).strip()
    if not val_line:
        return None
    # Cut off if subsequent labels appear on the same line (e.g. Code:, 2FA:)
    inline_cutoff = re.split(
        r'\b(?:code|codes|backup|2fa|otp|auth|pin|price|rs|pkr|usd)\b',
        val_line,
        maxsplit=1,
        flags=re.IGNORECASE
    )
    candidate_pass = inline_cutoff[0].strip().rstrip(",;:")
    if not candidate_pass:
        return None
    token = candidate_pass.split()[0].rstrip(",;:")
    if not token:
        return None
    # If the token itself is a CP package (e.g. "2000+2000", "5040", "5040CP"), password was omitted
    if extract_double_cp_package(token) or extract_normal_cp_package(token):
        return None
    if extract_double_cp_package(candidate_pass) or extract_normal_cp_package(candidate_pass):
        return None
    if token.lower().rstrip(":") in {"code", "codes", "2fa", "otp", "backup", "pin"}:
        return None
    return token


def extract_facebook_account(text: Optional[str]) -> Optional[str]:
    """
    Extracts a valid Facebook account identifier (phone number, email, or username)
    from a customer order message.
    Ignores password lines, verification code lines, and CP packages.
    """
    if not text:
        return None

    # 1. Check labeled fields (e.g. Phone: ..., Number: ..., User: ..., ID: ...)
    label_patterns = [
        re.compile(
            r'^\s*(?:phone(?:\s*number)?|mobile(?:\s*number)?|number|num|no\.?|contact|cell|tel)\s*[:=\-]\s*([^\r\n]+)',
            re.IGNORECASE | re.MULTILINE
        ),
        re.compile(
            r'^\s*(?:user(?:name)?|acc(?:ount)?|fb\s*id|uid|id)\s*[:=\-]\s*([^\r\n]+)',
            re.IGNORECASE | re.MULTILINE
        ),
        re.compile(
            r'^\s*email\s*[:=\-]\s*([^\r\n]+)',
            re.IGNORECASE | re.MULTILINE
        ),
    ]

    for pat in label_patterns:
        match = pat.search(text)
        if match:
            candidate = match.group(1).strip()
            # Cut off inline subsequent labels like Pass: or Code:
            inline_cutoff = re.split(
                r'\b(?:pass(?:word)?|pwd|psw|pas|code|codes|2fa|otp|backup|price)\b',
                candidate,
                maxsplit=1,
                flags=re.IGNORECASE
            )
            candidate = inline_cutoff[0].strip().rstrip(",;:")
            if not candidate:
                continue

            # If candidate is an email
            cand_email = extract_email(candidate)
            if cand_email:
                return cand_email

            tokens = candidate.split()
            cand_token = tokens[0].rstrip(",;:")

            combined_digits = re.sub(r'\D', '', candidate)
            cand_token_digits = re.sub(r'\D', '', cand_token)

            if is_valid_phone_or_username(candidate):
                if re.match(r'^\+?[\d\s\-()]+$', candidate):
                    clean_phone = ("+" if candidate.startswith("+") else "") + combined_digits
                    return clean_phone
                return candidate
            elif is_valid_phone_or_username(cand_token):
                if cand_token.isdigit() or cand_token.startswith("+"):
                    clean_phone = ("+" if cand_token.startswith("+") else "") + cand_token_digits
                    return clean_phone
                return cand_token

    # 2. Check unlabeled lines
    for line in text.splitlines():
        line_clean = line.strip()
        if not line_clean:
            continue
        # Skip login method headers (e.g. "Facebook", "FB", "Login: Facebook")
        if re.match(r'^(?:login\s*[:=\-]?\s*)?(?:facebook|fb)\b', line_clean, re.IGNORECASE):
            continue
        # Skip labeled field lines (already processed by label_patterns above)
        if re.match(r'^(?:phone(?:\s*number)?|mobile|number|num|no\.?|contact|cell|tel|user(?:name)?|acc(?:ount)?|email|fb\s*id|uid|id)\s*[:=\-]', line_clean, re.IGNORECASE):
            continue
        # Skip password lines
        if re.search(r'\b(?:pass(?:word)?|pwd|psw|pas)\b', line_clean, re.IGNORECASE):
            continue
        # Skip verification code / 2FA lines
        if re.search(r'\b(?:code|codes|backup|2fa|otp|auth|pin)\b', line_clean, re.IGNORECASE):
            continue
        # Skip title / header lines
        if re.match(r'^(?:fast\s*recharge|\bcodm\b|order\b)', line_clean, re.IGNORECASE):
            continue
        # Skip CP package lines
        if extract_double_cp_package(line_clean) or extract_normal_cp_package(line_clean):
            continue
        # Skip price lines
        if re.search(r'\b(?:price|rs|pkr|usd)\b', line_clean, re.IGNORECASE):
            continue

        # Check if line contains an email
        line_email = extract_email(line_clean)
        if line_email:
            return line_email

        # Check first token or line for phone number
        tokens = line_clean.split()
        cand_token = tokens[0].rstrip(",;:")
        if is_valid_phone_or_username(line_clean) and re.match(r'^\+?[\d\s\-()]+$', line_clean):
            digits = re.sub(r'\D', '', line_clean)
            clean_phone = ("+" if line_clean.startswith("+") else "") + digits
            return clean_phone
        elif is_valid_phone_or_username(cand_token):
            if cand_token.isdigit() or cand_token.startswith("+"):
                digits = re.sub(r'\D', '', cand_token)
                clean_phone = ("+" if cand_token.startswith("+") else "") + digits
                return clean_phone
            return cand_token

    return None


def validate_facebook_order(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Strict order validator for Facebook CODM orders.
    Requires:
    1. Facebook login method identifier ('Facebook' or 'FB').
    2. Must NOT be an Activision order.
    3. Password field present with non-empty password value.
    4. Valid Facebook username or phone number (email not required).
    5. Supported Normal CP or Double CP package.
    Returns structured order dict or None if invalid.
    """
    if not text:
        return None

    # 1. Require Facebook login method identifier
    has_fb_method = bool(re.search(r'\b(?:facebook|fb)\b', text, re.IGNORECASE))
    if not has_fb_method:
        return None

    # 2. Never classify Activision orders as Facebook
    if re.search(r'\bactivision\b', text, re.IGNORECASE):
        return None

    # 3. Require password field with non-empty password value
    password = extract_facebook_password(text)
    if not password:
        return None

    # 4. Require valid Facebook account (username or phone number)
    account = extract_facebook_account(text)
    if not account or not is_valid_phone_or_username(account):
        return None

    # 5. Require supported Double CP or Normal CP package
    double_cp = extract_double_cp_package(text)
    if double_cp:
        return {
            "email": account,
            "package": double_cp["formatted"],
            "order_type": "double_cp",
            "combination": double_cp["combination"],
            "total_cp": double_cp["total_cp"],
            "login_method": "Facebook",
        }

    normal_cp = extract_normal_cp_package(text)
    if normal_cp:
        return {
            "email": account,
            "package": normal_cp,
            "order_type": "normal_cp",
            "combination": None,
            "total_cp": int(normal_cp.split()[0]),
            "login_method": "Facebook",
        }

    return None


def validate_activision_order(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Strict order validator for Activision CODM orders (email-based).
    Preserves existing Activision email validation exactly as it is.
    Requires both a syntactically valid email AND a supported Normal or Double CP package.
    Returns structured dict or None.
    """
    if not text:
        return None

    email = extract_email(text)
    if not email:
        return None

    double_cp = extract_double_cp_package(text)
    if double_cp:
        return {
            "email": email,
            "package": double_cp["formatted"],
            "order_type": "double_cp",
            "combination": double_cp["combination"],
            "total_cp": double_cp["total_cp"],
            "login_method": "Activision",
        }

    normal_cp = extract_normal_cp_package(text)
    if normal_cp:
        return {
            "email": email,
            "package": normal_cp,
            "order_type": "normal_cp",
            "combination": None,
            "total_cp": int(normal_cp.split()[0]),
            "login_method": "Activision",
        }

    return None


def validate_order_fields(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Unified strict order validator used by both source_group_handler and duplicate_order_callback_handler.
    Preserves Activision email validation and adds separate Facebook login order validation.
    """
    if not text:
        return None

    # 1. Check Facebook order path first if Facebook login identifier is present and not Activision
    if re.search(r'\b(?:facebook|fb)\b', text, re.IGNORECASE) and not re.search(r'\bactivision\b', text, re.IGNORECASE):
        fb_order = validate_facebook_order(text)
        if fb_order:
            return fb_order

    # 2. Check Activision / standard email order path
    activision_order = validate_activision_order(text)
    if activision_order:
        return activision_order

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
    Extracts the account login method (e.g. 'Activision', 'Facebook') from an order message.
    Returns the canonical method name, or None if no known method is mentioned.
    Parse-only helper: the value is not stored in the database.
    """
    if not text:
        return None
    if re.search(r'\bactivision\b', text, re.IGNORECASE):
        return "Activision"
    if re.search(r'\b(?:facebook|fb)\b', text, re.IGNORECASE):
        return "Facebook"
    for method in LOGIN_METHODS:
        if re.search(rf'\b{re.escape(method)}\b', text, re.IGNORECASE):
            return method
    return None


def get_category_a_price(package_or_order: Any) -> Optional[str]:
    """
    Identifies the Category A price ($) using either the order's original CP package
    or Double CP combination.

    Normal CP and Double CP are matched separately. A Double CP price is NEVER
    calculated from its total CP alone.

    Returns price string with dollar sign (e.g. '$80', '$41', '$20.50', '$9', '$4.75', '$1')
    or None if no matching price exists (enabling manual fallback).
    """
    if not package_or_order:
        return None

    # Handle Order object or string
    text = ""
    if hasattr(package_or_order, "package"):
        text = package_or_order.package or ""
    elif isinstance(package_or_order, str):
        text = package_or_order
    else:
        text = str(package_or_order)

    text = text.strip()
    if not text:
        return None

    # 1. Match Double CP Event combination
    # Stored format is typically: "Double CP: 8000+8000 (Total: 16000 CP)" or raw "8000+8000" / "8+8"
    is_double = "double cp" in text.lower() or "+" in text
    if is_double:
        # Check canonical combination format first: e.g. "8000+8000", "4000+4000", etc.
        combo_match = re.search(r'\b(8000\+8000|4000\+4000|2000\+2000|800\+800|400\+400|80\+80)\b', text)
        if combo_match:
            combo = combo_match.group(1)
            # Match strictly against Double CP price table:
            return CATEGORY_A_DOUBLE_CP_PRICES.get(combo)

        # Fallback to extract_double_cp_package if raw text with shorthands (e.g. "8+8", "4k+4k")
        extracted_double = extract_double_cp_package(text)
        if extracted_double:
            combo = extracted_double["combination"]
            return CATEGORY_A_DOUBLE_CP_PRICES.get(combo)

        # Strict rule: Double CP must never fall through to Normal CP or match by total CP
        return None

    # 2. Match Normal CP package
    # Check for direct integer package (e.g. "10800 CP", "5040", "2400 CP", etc.)
    match_cp = re.search(r'(?<![.\-+\d])\b(\d+)\s*(?:CP)?\b(?![.\-+\d])', text, re.IGNORECASE)
    if match_cp:
        try:
            val = int(match_cp.group(1))
            if val in CATEGORY_A_NORMAL_CP_PRICES:
                return CATEGORY_A_NORMAL_CP_PRICES[val]
        except ValueError:
            pass

    # Fallback to extract_normal_cp_package if whole message text was provided
    extracted_normal = extract_normal_cp_package(text)
    if extracted_normal:
        try:
            val = int(extracted_normal.split()[0])
            if val in CATEGORY_A_NORMAL_CP_PRICES:
                return CATEGORY_A_NORMAL_CP_PRICES[val]
        except (ValueError, IndexError):
            pass

    return None

