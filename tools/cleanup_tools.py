"""
tools/cleanup_tools.py

Text cleanup helpers for Project LANTERN.

These utilities are intentionally:
- Safe for noisy OCR (no aggressive rewriting)
- Reusable across:
    * OCRAgent (post-processing model output)
    * ExtractionAgent (building summaries / search_text)
    * Search index construction (normalizing text fields)
"""

from __future__ import annotations

import re
from typing import Optional


_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_whitespace(text: str) -> str:
    """
    Collapse repeated whitespace and strip leading/trailing spaces.

    Examples
    --------
    "hello   world\\n\\nfoo" -> "hello world foo"
    """
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text).strip()


def strip_control_chars(text: str) -> str:
    """
    Remove non-printable control characters that occasionally show up
    in OCR output or malformed PDFs.

    This function is conservative: it does NOT remove newlines, only
    true control characters in the ASCII control ranges.
    """
    if not text:
        return ""
    return _CONTROL_CHARS_RE.sub("", text)


def collapse_hyphenation(text: str) -> str:
    """
    Collapse simple line-break hyphenation patterns from OCR.

    Example
    -------
    "multi-\nple" -> "multiple"

    Note: This is deliberately minimal. It avoids touching hyphenated
    words that do not span line breaks.
    """
    if not text:
        return ""
    # Join words that are split as "multi-\nple" or "multi-\r\nple"
    return re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)


def basic_cleanup(text: str) -> str:
    """
    Very light cleanup that is safe for noisy OCR.

    Operations
    ----------
    - Remove control characters
    - Normalize whitespace
    - Collapse simple hyphenation across line breaks
    - Strip obvious placeholder markers (e.g., "[OCR_PLACEHOLDER]")

    This is a good default for:
    - Post-processing OCRAgent.clean_text
    - Building search_text fields
    """
    if not text:
        return ""
    cleaned = strip_control_chars(text)
    cleaned = collapse_hyphenation(cleaned)
    cleaned = normalize_whitespace(cleaned)
    cleaned = cleaned.replace("[OCR_PLACEHOLDER]", "").strip()
    return cleaned


def safe_truncate(text: str, max_chars: int, suffix: str = "…") -> str:
    """
    Soft truncate text for UI / summaries.

    Parameters
    ----------
    text:
        Input string (may be None/empty).
    max_chars:
        Maximum length of returned string, including the suffix.
    suffix:
        Suffix to append when truncation occurs (default: "…").

    Returns
    -------
    str
        Original text if within limit, otherwise truncated and suffixed.
    """
    if not text:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if len(suffix) >= max_chars:
        # Edge case: suffix longer than allowed length
        return suffix[:max_chars]
    return text[: max_chars - len(suffix)] + suffix