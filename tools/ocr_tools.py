"""
tools/ocr_tools.py

OCR-related utilities and small I/O helpers for Project LANTERN.

Design goals
------------
- Do NOT duplicate OCRAgent's backend logic.
- Provide shared, backend-agnostic utilities that:
    * Normalize OCR records to a stable schema (OCRResult)
    * Provide a deterministic stub for offline / demo usage
    * Handle JSON / JSONL reading and writing
    * Generate safe cache keys from file paths

These helpers can be used by:
- agents/ocr_agent.py           (for stubbing / normalization)
- src/pipeline.py               (for cache keys & JSONL exports)
- notebooks/project_lantern*.ipynb (for quick ad-hoc experiments)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union
import json
import logging

from .cleanup_tools import basic_cleanup

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# OCR result schema
# ---------------------------------------------------------------------------


@dataclass
class OCRResult:
    """
    Canonical OCR result schema used across Project LANTERN.

    Fields
    ------
    raw_text:
        Full text as returned by the underlying OCR backend.
    clean_text:
        Lightly cleaned text suitable for display / downstream stats.
    confidence:
        Best-effort confidence score in [0, 1]. May be approximate.
    error:
        None on success, or a human-readable error message on failure.
    model:
        Model name or version identifier (e.g., "gpt-4o", "stub").
    engine:
        Backend identifier ("gpt-4o", "tesseract", "stub", etc.).
    """

    raw_text: str
    clean_text: str
    confidence: float
    error: Optional[str] = None
    model: str = "unknown"
    engine: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to a dict with the keys expected by downstream components:
        - ocr_text
        - raw_text
        - clean_text
        - confidence
        - error
        - model
        - engine
        """
        data = asdict(self)
        return {
            "ocr_text": data["raw_text"],
            "raw_text": data["raw_text"],
            "clean_text": data["clean_text"],
            "confidence": data["confidence"],
            "error": data["error"],
            "model": data["model"],
            "engine": data["engine"],
        }


def normalize_ocr_record(
    record: Dict[str, Any],
    *,
    default_model: str = "unknown",
    default_engine: str = "unknown",
) -> OCRResult:
    """
    Normalize a loosely structured OCR dict into a canonical OCRResult.

    This is useful when:
    - Swapping OCR backends (ADK tools, third-party APIs, etc.)
    - Integrating with notebooks that may return slightly different keys

    Expected input keys (best-effort):
        - "ocr_text", "raw_text", or "clean_text"
        - "confidence" (optional)
        - "error" (optional)
        - "model" (optional)
        - "engine" (optional)
    """
    raw = (
        record.get("ocr_text")
        or record.get("raw_text")
        or record.get("clean_text")
        or ""
    )
    clean = basic_cleanup(record.get("clean_text") or raw)

    try:
        conf_val = float(record.get("confidence", 0.0))
    except Exception:
        conf_val = 0.0

    return OCRResult(
        raw_text=raw,
        clean_text=clean,
        confidence=conf_val,
        error=record.get("error"),
        model=str(record.get("model") or default_model),
        engine=str(record.get("engine") or default_engine),
    )


# ---------------------------------------------------------------------------
# File / cache helpers
# ---------------------------------------------------------------------------


def make_cache_key(rel_path: str) -> str:
    """
    Turn a relative file path into a safe cache file name.

    Example
    -------
    "A_clean_ocr/HOUSE_OVERSIGHT_011638.jpg"
    -> "A_clean_ocr__HOUSE_OVERSIGHT_011638.jpg.json"
    """
    return rel_path.replace("/", "__") + ".json"


def ensure_parent_dir(path: Path) -> None:
    """
    Ensure the parent directory of `path` exists.
    """
    path.parent.mkdir(parents=True, exist_ok=True)


def save_json(record: Dict[str, Any], path: Union[str, Path]) -> None:
    """
    Write a single JSON object to disk with UTF-8 encoding.

    This is useful for:
    - Per-page OCR cache files
    - Simple diagnostics dumps
    """
    p = Path(path)
    ensure_parent_dir(p)
    with p.open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    logger.debug("Wrote JSON record to %s", p)


# ---------------------------------------------------------------------------
# JSONL helpers
# ---------------------------------------------------------------------------


def write_jsonl(records: Iterable[Dict[str, Any]], out_path: Union[str, Path]) -> None:
    """
    Write an iterable of dict records to disk as JSON Lines (JSONL).

    Each record is written as one JSON object per line.

    This helper is intentionally generic so it can be reused by:
    - src/pipeline.py (pages.jsonl, sequences.jsonl)
    - ad-hoc notebook exports
    """
    p = Path(out_path)
    ensure_parent_dir(p)
    count = 0
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            json.dump(rec, f, ensure_ascii=False)
            f.write("\n")
            count += 1
    logger.info("Wrote %d JSONL records to %s", count, p)


def load_jsonl(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """
    Load a JSONL file into a list of dicts.

    Behavior
    --------
    - Returns an empty list if the file does not exist.
    - Skips malformed lines but logs a warning.
    """
    p = Path(path)
    if not p.exists():
        logger.warning("JSONL file not found, skipping: %s", p)
        return []

    records: List[Dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(
                    "Skipping malformed JSON line %d in %s: %s", idx, p, e
                )
    logger.info("Loaded %d JSONL records from %s", len(records), p)
    return records


# ---------------------------------------------------------------------------
# Stub / offline OCR helper
# ---------------------------------------------------------------------------


def stub_ocr_for_path(
    image_path: Union[str, Path],
    *,
    model_name: str = "stub-ocr",
    reason: Optional[str] = None,
) -> OCRResult:
    """
    Deterministic stub OCR result for a given image path.

    Use cases
    ---------
    - Offline demos where API access is not available
    - Unit tests for the pipeline without making external calls
    - Fallback path when OCRAgent hits quota or configuration issues

    The returned OCRResult always has:
    - raw_text    : short stub message referencing the image filename
    - clean_text  : cleaned version of the same stub
    - confidence  : 0.0 (since no real OCR was performed)
    - error       : the provided reason (if any)
    - model       : model_name
    - engine      : "stub"
    """
    p = Path(image_path)
    stub_text = f"[OCR_PLACEHOLDER] Text for {p.name}"
    cleaned = basic_cleanup(stub_text)

    return OCRResult(
        raw_text=stub_text,
        clean_text=cleaned,
        confidence=0.0,
        error=reason,
        model=model_name,
        engine="stub",
    )