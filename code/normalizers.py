"""Safe normalization and conversion utilities for monetary values, dates,

and categories.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Set

VALID_CURRENCIES: Set[str] = {"INR", "ZAR", "IDR", "USD", "EUR"}


def parse_decimal(val: Optional[str], allow_blank: bool = True) -> Optional[Decimal]:
    """Parse a monetary or numeric string into Decimal safely.

    Handles commas, currency symbols, and distinguishes blank/None from zero.

    Args:
        val: The string representation to parse.
        allow_blank: If True, empty strings return None instead of raising an error.

    Returns:
        Decimal or None.

    Raises:
        ValueError: If val cannot be parsed as a Decimal.
    """
    if val is None:
        if allow_blank:
            return None
        raise ValueError("Unexpected None value for required Decimal field")

    clean_str = val.strip()
    if not clean_str:
        if allow_blank:
            return None
        raise ValueError("Unexpected empty string for required Decimal field")

    # Remove standard thousands-separator commas
    clean_str = clean_str.replace(",", "")

    try:
        return Decimal(clean_str)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid monetary/decimal format: '{val}'") from exc


def parse_date(val: Optional[str], allow_blank: bool = False) -> Optional[date]:
    """Parse a date string in YYYY-MM-DD format.

    Args:
        val: String date in YYYY-MM-DD format.
        allow_blank: If True, blank values return None.

    Returns:
        date or None.

    Raises:
        ValueError: If val cannot be parsed.
    """
    if val is None or not val.strip():
        if allow_blank:
            return None
        raise ValueError("Date field cannot be empty")

    clean_str = val.strip()
    try:
        return date.fromisoformat(clean_str)
    except ValueError as exc:
        raise ValueError(f"Invalid date format (expected YYYY-MM-DD): '{val}'") from exc


def parse_datetime(val: Optional[str]) -> datetime:
    """Parse an ISO-8601 UTC timestamp string (e.g. 2025-07-29T09:30:00Z).

    Args:
        val: ISO timestamp string.

    Returns:
        datetime object with UTC timezone.

    Raises:
        ValueError: If val cannot be parsed.
    """
    if val is None or not val.strip():
        raise ValueError("Timestamp field cannot be empty")

    clean_str = val.strip()
    if clean_str.endswith("Z"):
        clean_str = clean_str[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(clean_str)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp format: '{val}'") from exc


def parse_int(val: Optional[str], allow_blank: bool = False) -> Optional[int]:
    """Parse an integer string safely.

    Args:
        val: String integer.
        allow_blank: If True, blank values return None.

    Returns:
        int or None.

    Raises:
        ValueError: If val cannot be parsed.
    """
    if val is None or not val.strip():
        if allow_blank:
            return None
        raise ValueError("Integer field cannot be empty")

    clean_str = val.strip().replace(",", "")
    try:
        return int(clean_str)
    except ValueError as exc:
        raise ValueError(f"Invalid integer: '{val}'") from exc


def parse_bool(val: Optional[str]) -> bool:
    """Parse a boolean string (e.g. 'true', 'false', 'True', '1').

    Args:
        val: String boolean.

    Returns:
        bool.

    Raises:
        ValueError: If val is unrecognized.
    """
    if val is None or not val.strip():
        raise ValueError("Boolean field cannot be empty")

    clean_str = val.strip().lower()
    if clean_str in {"true", "1", "t", "yes", "y"}:
        return True
    if clean_str in {"false", "0", "f", "no", "n"}:
        return False
    raise ValueError(f"Unrecognized boolean value: '{val}'")


def parse_pipe_list(val: Optional[str]) -> List[str]:
    """Parse a pipe-separated string into a list of cleaned tokens.

    Example: 'rent|education|groceries' -> ['rent', 'education', 'groceries']
    Blank string returns [].
    """
    if val is None or not val.strip():
        return []
    return [item.strip() for item in val.split("|") if item.strip()]


def parse_currency(val: Optional[str]) -> str:
    """Validate and normalize a 3-letter currency code."""
    if val is None or not val.strip():
        raise ValueError("Currency field cannot be empty")

    currency = val.strip().upper()
    if currency not in VALID_CURRENCIES:
        raise ValueError(f"Unsupported currency code: '{currency}' (expected one of {VALID_CURRENCIES})")
    return currency
