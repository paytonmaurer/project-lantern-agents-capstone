"""
search_index.py

Search database layer for Project LANTERN.

Goal
----
Turn the exported JSONL files from the pipeline
  - pages.jsonl     (page-level enriched records)
  - sequences.jsonl (sequence-level summaries)
into a DuckDB database that is easy to query for:

- Keyword search (over a `search_text` field)
- Filtering by category, doc_type, sequence_id, etc.
- Joining pages <-> sequences

This module is intentionally dependency-light:
- pandas (already used elsewhere)
- duckdb (small, pure-Python package)

Typical usage (from a notebook)
-------------------------------
from pathlib import Path
from src.search_index import build_duckdb, open_duckdb

DATA_ROOT = PROJECT_ROOT / "data"
EXPORT_DIR = DATA_ROOT / "outputs"
DB_PATH = DATA_ROOT / "lantern.duckdb"

build_duckdb(
    db_path=DB_PATH,
    pages_path=EXPORT_DIR / "pages.jsonl",
    seqs_path=EXPORT_DIR / "sequences.jsonl",
)

con = open_duckdb(DB_PATH)
con.sql("SELECT * FROM pages LIMIT 5").df()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import json

import duckdb
import pandas as pd

PageRecord = Dict[str, Any]
SequenceRecord = Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers for loading JSONL
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """
    Load a JSONL file into a list of dicts.

    Each line is expected to be a valid JSON object.
    Returns an empty list if the file does not exist.
    """
    if not path.exists():
        print(f"⚠️ JSONL file not found, skipping: {path}")
        return []

    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"⚠️ Skipping malformed JSON line in {path}: {e}")
    return records


# ---------------------------------------------------------------------------
# Page-level normalization
# ---------------------------------------------------------------------------

def _build_page_dataframe(pages: List[PageRecord]) -> pd.DataFrame:
    """
    Normalize page-level records into a tabular DataFrame.

    We keep a set of core fields that are expected to exist (or
    can be safely defaulted), and also preserve any extra columns
    from the JSON as-is.

    Core columns
    ------------
      - file_path
      - category
      - doc_type
      - sequence_id
      - sequence_order
      - summary / page_summary
      - ocr_text
      - search_text  (derived for keyword search if missing)
    """
    if not pages:
        return pd.DataFrame()

    df = pd.json_normalize(pages)

    # Ensure core fields exist, even if missing in some records
    for col, default in [
        ("file_path", None),
        ("category", None),
        ("doc_type", None),
        ("sequence_id", None),
        ("sequence_order", None),
        ("summary", None),
        ("page_summary", None),
        ("ocr_text", None),
    ]:
        if col not in df.columns:
            df[col] = default

    # If summary is missing but page_summary exists, align the naming
    if "summary" not in df.columns and "page_summary" in df.columns:
        df["summary"] = df["page_summary"]
    elif "summary" in df.columns and "page_summary" not in df.columns:
        df["page_summary"] = df["summary"]

    def make_search_text(row: pd.Series) -> str:
        """
        Derive a basic search_text field that concatenates summary,
        OCR text, and any entity names (if available).
        """
        parts: List[str] = []

        summary = row.get("summary")
        if isinstance(summary, str):
            parts.append(summary)

        ocr_text = row.get("ocr_text")
        if isinstance(ocr_text, str):
            parts.append(ocr_text)

        # entities is often a list of dicts with 'text' or 'name'
        entities = row.get("entities")
        if isinstance(entities, list):
            names: List[str] = []
            for ent in entities:
                if isinstance(ent, dict):
                    name = (
                        ent.get("text")
                        or ent.get("name")
                        or ent.get("value")
                    )
                    if isinstance(name, str):
                        names.append(name)
                elif isinstance(ent, str):
                    names.append(ent)
            if names:
                parts.append(" ".join(names))

        return " ".join(parts)

    # Use existing search_text if present; otherwise derive one.
    if "search_text" not in df.columns:
        df["search_text"] = df.apply(make_search_text, axis=1)

    # A simple boolean convenience flag for downstream filters
    df["has_text"] = df["search_text"].fillna("").str.len() > 0

    # Normalize common identifier columns for friendlier querying
    if "sequence_id" in df.columns:
        # Keep as string for consistent joins and WHERE filters
        df["sequence_id"] = df["sequence_id"].astype(str)

    return df


# ---------------------------------------------------------------------------
# Sequence-level normalization
# ---------------------------------------------------------------------------

def _build_sequence_dataframe(seqs: List[SequenceRecord]) -> pd.DataFrame:
    """
    Normalize sequence-level records into a tabular DataFrame.

    Core columns
    ------------
      - sequence_id
      - num_pages
      - categories_present
      - doc_types_present
      - overall_summary / summary
    """
    if not seqs:
        return pd.DataFrame()

    df = pd.json_normalize(seqs)

    # If the ExtractionAgent used `summary` instead of `overall_summary`,
    # align the naming for the database.
    if "overall_summary" not in df.columns and "summary" in df.columns:
        df["overall_summary"] = df["summary"]
    elif "overall_summary" in df.columns and "summary" not in df.columns:
        df["summary"] = df["overall_summary"]

    for col, default in [
        ("sequence_id", None),
        ("num_pages", 0),
        ("categories_present", []),
        ("doc_types_present", []),
        ("overall_summary", None),
    ]:
        if col not in df.columns:
            df[col] = default

    # Normalize identifier type
    df["sequence_id"] = df["sequence_id"].astype(str)

    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_duckdb(
    db_path: Path,
    pages_path: Path,
    seqs_path: Path,
    *,
    overwrite: bool = True,
) -> None:
    """
    Build (or rebuild) a DuckDB database for search & analytics.

    Parameters
    ----------
    db_path:
        Location where `lantern.duckdb` (or similar) should live.

    pages_path:
        Path to the exported `pages.jsonl` file from the pipeline.

    seqs_path:
        Path to the exported `sequences.jsonl` file from the pipeline.

    overwrite:
        If True (default), existing tables will be replaced.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    pages = _load_jsonl(pages_path)
    seqs = _load_jsonl(seqs_path)

    pages_df = _build_page_dataframe(pages)
    seqs_df = _build_sequence_dataframe(seqs)

    print(f"📄 Pages loaded    : {len(pages_df)} rows")
    print(f"🧵 Sequences loaded: {len(seqs_df)} rows")

    con = duckdb.connect(str(db_path))

    # Register temporary views so we can create tables from them
    con.register("pages_df", pages_df)
    con.register("seqs_df", seqs_df)

    if overwrite:
        con.execute("DROP TABLE IF EXISTS pages;")
        con.execute("DROP TABLE IF EXISTS sequences;")

    con.execute("CREATE TABLE IF NOT EXISTS pages AS SELECT * FROM pages_df;")
    con.execute("CREATE TABLE IF NOT EXISTS sequences AS SELECT * FROM seqs_df;")

    # Placeholder for future performance tuning (indexes / projections / clustering)
    # Example (when supported/needed):
    #   con.execute('CREATE INDEX IF NOT EXISTS idx_pages_seq ON pages(sequence_id);')

    con.close()
    print(f"✅ DuckDB search database written to: {db_path}")


def open_duckdb(db_path: Path) -> duckdb.DuckDBPyConnection:
    """
    Convenience helper to open a DuckDB connection.

    Raises
    ------
    FileNotFoundError
        If the DuckDB file does not exist.
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"DuckDB file not found at {db_path}. "
            "Run build_duckdb(...) first."
        )
    return duckdb.connect(str(db_path))