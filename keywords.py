"""
Order Detection Keywords and CP Package Detector.
Contains dedicated keyword definitions and CP package normalization for detecting customer orders in Client Group messages.
"""

import re
from typing import List, Tuple, Optional
from config import Config

# Dedicated order detection keywords (case-insensitive)
ORDER_KEYWORDS: List[str] = [
    ".com",
    ".co",
    ".net",
    ".org",
    ".pk",
    ".io",
    ".gg",
    ".ru",
    "gmail",
    "gma",
    "hotmail",
    "hotmail.com",
    "outlook",
    "outlook.com",
    "yahoo",
    "icloud",
    "proton",
    "+",
    "email"
]


def normalize_cp_text(text: Optional[str]) -> str:
    """
    Normalizes input text for CP package detection and parsing.
    Handles:
    - Escaped newlines ('\\n' -> '\n')
    - Comma removal in numbers ('12,000' -> '12000')
    - 'k'/'K' notation ('12k' -> '12000', '10.8k' -> '10800')
    - Standardizing spacing before CP suffix ('12000CP' -> '12000 CP')
    """
    if not text:
        return ""

    # 1. Unescape literal escaped newlines
    normalized = text.replace("\\n", "\n").replace("\\r", "\r")

    # 2. Remove commas between digits (e.g. 12,000 -> 12000)
    normalized = re.sub(r'(\d+),(\d{3})', r'\1\2', normalized)

    # 3. Convert 'k'/'K' numbers (e.g. 12k -> 12000, 10.8k -> 10800, 12K cp -> 12000 CP)
    def k_replacer(match):
        num_str = match.group(1)
        try:
            val = float(num_str)
            int_val = int(val * 1000)
            return str(int_val)
        except ValueError:
            return match.group(0)

    normalized = re.sub(r'\b(\d+(?:\.\d+)?)\s*[kK]\b', k_replacer, normalized)

    # 4. Standardize number + CP/cp (e.g. 12000CP -> 12000 CP, 12000cp -> 12000 CP)
    normalized = re.sub(r'\b(\d+)\s*([cC][pP])\b', r'\1 CP', normalized)

    return normalized


def contains_order_keyword(text: Optional[str]) -> Tuple[bool, Optional[str]]:
    """
    Evaluates message text or caption for order detection.
    Detection Priority:
    1. Parse and normalize text.
    2. Check for explicit or numeric CP packages matching configured Config.KNOWN_CP_PACKAGES.
    3. Check for explicit CP suffix (e.g. '12345 CP') for unknown CP packages.
    4. Check for traditional order keywords (e.g. '.com', 'gmail', etc.).

    Args:
        text (Optional[str]): Message text, photo caption, or document caption.

    Returns:
        Tuple[bool, Optional[str]]: (is_matched, match_info_or_keyword)
    """
    if not text:
        return False, None

    normalized = normalize_cp_text(text)

    # 1. Check for explicit CP suffix mentions: <number> CP (e.g. "12000 CP", "12345 CP")
    cp_matches = re.findall(r'\b(\d+)\s*CP\b', normalized, re.IGNORECASE)
    for num_str in cp_matches:
        try:
            val = int(num_str)
            if val in Config.KNOWN_CP_PACKAGES:
                return True, f"cp_package:{val}"
            else:
                return True, f"unknown_cp_package:{val}"
        except ValueError:
            pass

    # 2. Check for standalone numbers matching configured KNOWN_CP_PACKAGES (e.g. "12000")
    number_tokens = re.findall(r'\b(\d+)\b', normalized)
    for num_str in number_tokens:
        try:
            val = int(num_str)
            if val in Config.KNOWN_CP_PACKAGES:
                return True, f"cp_package:{val}"
        except ValueError:
            pass

    # 3. Check for traditional order keywords
    text_lower = text.lower()
    for kw in ORDER_KEYWORDS:
        if kw.lower() in text_lower:
            return True, kw

    return False, None
