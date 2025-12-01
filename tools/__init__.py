# tools/__init__.py
"""
Utility helpers for Project LANTERN.

This package centralizes small, reusable building blocks used across:
- agents/ (OCR, extraction, threading)
- src/   (pipeline orchestration, search index)
- notebooks/ (exploratory analysis & demos)

Key modules
-----------
- cleanup_tools:
    Text normalization & safe truncation for noisy OCR.
- ocr_tools:
    OCR result schema helpers, JSONL I/O, and cache-key utilities.
"""

from .cleanup_tools import (
    normalize_whitespace,
    basic_cleanup,
    strip_control_chars,
    collapse_hyphenation,
    safe_truncate,
)

from .ocr_tools import (
    OCRResult,
    make_cache_key,
    write_jsonl,
    load_jsonl,
    save_json,
    normalize_ocr_record,
    stub_ocr_for_path,
)

__all__ = [
    # cleanup_tools
    "normalize_whitespace",
    "basic_cleanup",
    "strip_control_chars",
    "collapse_hyphenation",
    "safe_truncate",
    # ocr_tools
    "OCRResult",
    "make_cache_key",
    "write_jsonl",
    "load_jsonl",
    "save_json",
    "normalize_ocr_record",
    "stub_ocr_for_path",
]