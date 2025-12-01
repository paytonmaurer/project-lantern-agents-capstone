"""
Project LANTERN pipeline orchestration.

This module wires together:

- OCRAgent
- ThreadingAgent
- ExtractionAgent

to run a manifest-driven pipeline over a curated dataset.

Primary entry point
-------------------

    run_pipeline(
        manifest_df,
        ocr_agent,
        threading_agent,
        extraction_agent,
        epstein_image_root,
        ocr_cache_dir=...,
        use_ocr_cache=True,
        save_ocr_cache=True,
        export_dir=Path("data/outputs"),   # optional
        export_jsonl=True,                 # optional
    )

Responsibilities
----------------
1. Iterate over manifest rows.
2. Run OCR on each image (with optional disk cache).
3. Group rows into sequences/threads via ThreadingAgent.
4. Produce page-level and sequence-level enriched records via ExtractionAgent.
5. Optionally export those records to disk in JSONL format.

Design Notes
------------
- This implementation uses the updated agents:

    * OCRAgent.run_page(...)
    * ExtractionAgent.extract_page(...)
    * ExtractionAgent.summarize_sequence(texts)

- The contract to the notebook and search layer is:

    * `enriched_pages`: list[dict] with at least
        - file_path
        - sequence_id
        - category
        - doc_type
        - search_text

    * `sequence_summaries`: list[dict] with at least
        - sequence_id
        - summary (alias of sequence_summary)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

import json
import logging

import pandas as pd

from agents.ocr_agent import OCRAgent
from agents.threading_agent import ThreadingAgent
from agents.extraction_agent import ExtractionAgent

logger = logging.getLogger(__name__)

# Type aliases for readability
PageRecord = Dict[str, Any]
SequenceRecord = Dict[str, Any]


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def _cache_key_for_path(rel_path: str) -> str:
    """
    Turn a relative file path into a safe cache file name.

    Example
    -------
    "A_clean_ocr/HOUSE_OVERSIGHT_011638.jpg"
        -> "A_clean_ocr__HOUSE_OVERSIGHT_011638.jpg.json"
    """
    return rel_path.replace("/", "__") + ".json"


def _load_ocr_from_cache(cache_dir: Path, rel_path: str) -> Optional[PageRecord]:
    """
    Attempt to load a cached OCR record from disk.

    Returns
    -------
    dict | None
        The cached OCR record if present and valid, otherwise None.
    """
    cache_file = cache_dir / _cache_key_for_path(rel_path)
    if not cache_file.exists():
        return None

    try:
        with cache_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.warning("Failed to load OCR cache for %s: %s", rel_path, e)
        return None


def _save_ocr_to_cache(cache_dir: Path, rel_path: str, record: PageRecord) -> None:
    """
    Save an OCR record to disk as JSON.

    This assumes that `record` is JSON-serializable (dict of primitives).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / _cache_key_for_path(rel_path)

    try:
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Failed to write OCR cache for %s: %s", rel_path, e)


def _write_jsonl(records: List[Dict[str, Any]], out_path: Path) -> None:
    """
    Write a list of dict records to disk as JSON Lines (JSONL).

    Each record is written as one JSON object per line.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            json.dump(rec, f, ensure_ascii=False)
            f.write("\n")
    logger.info("Wrote %d records to %s", len(records), out_path)


def _validate_manifest(manifest_df: pd.DataFrame) -> None:
    """
    Validate that the manifest contains the core columns expected by the pipeline.

    Raises
    ------
    ValueError
        If required columns are missing.
    """
    required_cols = ["file_path", "category", "doc_type"]
    missing = [c for c in required_cols if c not in manifest_df.columns]
    if missing:
        raise ValueError(
            f"Manifest is missing required columns: {missing}. "
            "Expected at least: 'file_path', 'category', 'doc_type'."
        )


def _build_search_text(enriched: PageRecord) -> str:
    """
    Construct a canonical `search_text` field for a page.

    Priority:
        1. search_text from ExtractionAgent
        2. notes (from manifest)
        3. OCR text (ocr_text → clean_text → raw_text)
    """
    pieces: List[str] = []

    if isinstance(enriched.get("search_text"), str) and enriched["search_text"].strip():
        pieces.append(enriched["search_text"].strip())

    notes = enriched.get("notes")
    if isinstance(notes, str) and notes.strip():
        pieces.append(notes.strip())

    ocr_text = (
        enriched.get("ocr_text")
        or enriched.get("clean_text")
        or enriched.get("raw_text")
    )

    if isinstance(ocr_text, str) and ocr_text.strip():
        pieces.append(ocr_text.strip())

    return "\n\n".join(pieces).strip()


# ---------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------
def run_pipeline(
    manifest_df: pd.DataFrame,
    ocr_agent: OCRAgent,
    threading_agent: ThreadingAgent,
    extraction_agent: ExtractionAgent,
    epstein_image_root: Path,
    *,
    ocr_cache_dir: Optional[Path] = None,
    use_ocr_cache: bool = True,
    save_ocr_cache: bool = True,
    export_dir: Optional[Path] = None,
    export_jsonl: bool = True,
) -> Tuple[List[PageRecord], List[SequenceRecord]]:
    """
    Run the Project LANTERN demo pipeline over a manifest-driven dataset.

    Parameters
    ----------
    manifest_df :
        DataFrame containing manifest rows with at least:
        - file_path (relative to epstein_image_root)
        - category
        - doc_type
        - sequence_id (optional)
        - sequence_order (optional)

    ocr_agent :
        Initialized OCR agent.

    threading_agent :
        Initialized Thread Reconstruction agent.

    extraction_agent :
        Initialized Extraction & Insights agent.

    epstein_image_root :
        Root directory where the curated Epstein images live, e.g.
        PROJECT_ROOT / "data" / "epstein_curated_v1".

    ocr_cache_dir :
        Optional directory to store and read OCR results (per-page JSON).

    use_ocr_cache :
        Whether to read existing OCR records from `ocr_cache_dir`.

    save_ocr_cache :
        Whether to save new OCR records into `ocr_cache_dir`.

    export_dir :
        Optional directory where page- and sequence-level outputs
        will be written as JSONL files (pages.jsonl, sequences.jsonl).

    export_jsonl :
        Whether to write JSONL exports when `export_dir` is provided.

    Returns
    -------
    (enriched_pages, sequence_summaries) :
        enriched_pages
            List of page-level enriched records.
        sequence_summaries
            List of sequence-level summary records.
    """
    if manifest_df.empty:
        logger.warning(
            "run_pipeline called with an empty manifest_df; "
            "no OCR or extraction will be performed."
        )
        return [], []

    _validate_manifest(manifest_df)

    if not epstein_image_root.exists():
        logger.warning(
            "epstein_image_root does not exist on disk: %s", epstein_image_root
        )

    logger.info(
        "Starting Project LANTERN pipeline on %d manifest rows.",
        len(manifest_df),
    )

    # ------------------------------------------------------------------
    # 1) OCR each image in the manifest (with optional cache)
    # ------------------------------------------------------------------
    ocr_outputs: Dict[str, PageRecord] = {}

    num_from_cache = 0
    num_fresh_ocr = 0

    for idx, (_, row) in enumerate(manifest_df.iterrows(), start=1):
        rel_path = str(row["file_path"])
        full_image_path = epstein_image_root / rel_path

        logger.debug(
            "OCR [%d/%d] → %s",
            idx,
            len(manifest_df),
            full_image_path,
        )

        ocr_record: Optional[PageRecord] = None

        # 1a. Try cache (if enabled), but ignore "bad" cached records
        if ocr_cache_dir is not None and use_ocr_cache:
            cached = _load_ocr_from_cache(ocr_cache_dir, rel_path)
            if cached is not None:
                # Consider cached OCR "bad" if it has an error AND no usable text
                has_text = any(
                    isinstance(cached.get(k), str) and cached[k].strip()
                    for k in ("clean_text", "raw_text", "ocr_text")
                )
                if cached.get("error") and not has_text:
                    logger.info(
                        "Ignoring cached OCR with error and no text for %s; re-running OCR.",
                        rel_path,
                    )
                    ocr_record = None
                else:
                    ocr_record = cached
                    num_from_cache += 1
            else:
                ocr_record = None

        # 1b. If cache miss or bad cache, call OCR agent
        if ocr_record is None:
            ocr_record = ocr_agent.run_page(str(full_image_path), page_meta=row.to_dict())
            num_fresh_ocr += 1

            if ocr_cache_dir is not None and save_ocr_cache and ocr_record is not None:
                _save_ocr_to_cache(ocr_cache_dir, rel_path, ocr_record)

        ocr_outputs[rel_path] = ocr_record or {}

    logger.info(
        "OCR completed for %d images (%d from cache, %d fresh).",
        len(ocr_outputs),
        num_from_cache,
        num_fresh_ocr,
    )

    # ------------------------------------------------------------------
    # 2) Group rows into sequences via ThreadingAgent
    # ------------------------------------------------------------------
    manifest_rows: List[PageRecord] = manifest_df.to_dict(orient="records")

    sequences_map = threading_agent.group_sequences(manifest_rows)
    # Expecting a mapping: sequence_id -> list[manifest_row_dict]
    if not isinstance(sequences_map, dict):
        raise TypeError(
            "ThreadingAgent.group_sequences is expected to return "
            "a dict[sequence_id -> list[manifest_row]], "
            f"but got {type(sequences_map)} instead."
        )

    logger.info(
        "ThreadingAgent grouped %d manifest rows into %d sequences.",
        len(manifest_rows),
        len(sequences_map),
    )

    # ------------------------------------------------------------------
    # 3) Enrich each page via ExtractionAgent
    # ------------------------------------------------------------------
    enriched_pages: List[PageRecord] = []

    for row in manifest_rows:
        rel_path = str(row.get("file_path"))
        ocr_record = ocr_outputs.get(rel_path, {}) or {}

        clean_text = (
            ocr_record.get("clean_text")
            or ocr_record.get("raw_text")
            or ""
        )

        ext_result = extraction_agent.extract_page(
            clean_text=clean_text,
            metadata=row,
        )

        enriched = {
            **row,
            **ocr_record,
            **ext_result,
        }

        # Ensure stable keys
        enriched.setdefault("file_path", rel_path)
        enriched.setdefault("sequence_id", row.get("sequence_id"))
        enriched.setdefault("sequence_order", row.get("sequence_order"))
        enriched.setdefault("ocr_text", enriched.get("ocr_text") or clean_text)
        enriched.setdefault(
            "ocr_text_length",
            len(enriched.get("ocr_text", "") or ""),
        )

        # Alias page_summary → summary for legacy notebook cells
        if "page_summary" in enriched and "summary" not in enriched:
            enriched["summary"] = enriched["page_summary"]

        # Canonical search_text
        enriched["search_text"] = _build_search_text(enriched)

        enriched_pages.append(enriched)

    # ------------------------------------------------------------------
    # 4) Sequence-level summaries via ExtractionAgent
    # ------------------------------------------------------------------
    sequence_summaries: List[SequenceRecord] = []

    # Build quick lookup by file_path for sequence assembly (optional)
    pages_by_file: Dict[str, PageRecord] = {
        str(p.get("file_path")): p for p in enriched_pages
    }

    for seq_id, rows in sequences_map.items():
        texts: List[str] = []
        for r in rows:
            fp = str(r.get("file_path"))
            page = pages_by_file.get(fp)
            if not page:
                continue
            ct = (
                page.get("clean_text")
                or page.get("ocr_text")
                or page.get("raw_text")
                or ""
            )
            if ct:
                texts.append(str(ct))

        if not texts:
            seq_meta = {"sequence_summary": "", "sequence_search_text": ""}
        else:
            seq_meta = extraction_agent.summarize_sequence(texts)

        seq_rec: Dict[str, Any] = {
            "sequence_id": seq_id,
            "num_pages": len(rows),
            **seq_meta,
        }

        # Alias for notebook compatibility
        if "summary" not in seq_rec:
            seq_rec["summary"] = seq_rec.get("sequence_summary", "")

        sequence_summaries.append(seq_rec)

    logger.info(
        "Pipeline complete: %d enriched pages across %d sequences.",
        len(enriched_pages),
        len(sequence_summaries),
    )

    # ------------------------------------------------------------------
    # 5) Optional JSONL export for search / analytics layers
    # ------------------------------------------------------------------
    if export_dir is not None and export_jsonl:
        export_dir = Path(export_dir)
        pages_path = export_dir / "pages.jsonl"
        seqs_path = export_dir / "sequences.jsonl"

        _write_jsonl(enriched_pages, pages_path)
        _write_jsonl(sequence_summaries, seqs_path)

    return enriched_pages, sequence_summaries
