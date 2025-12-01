# src/__init__.py
"""
Core orchestration and search layer for Project LANTERN.

This package exposes a small, intentional public surface:

- :func:`run_pipeline`
    Execute the multi-agent document pipeline over a manifest-driven dataset.
- :func:`build_duckdb`
    Build a DuckDB search database from pipeline JSONL exports.
- :func:`open_duckdb`
    Convenience helper to open the DuckDB search database.

These entry points are used throughout the capstone notebook to demonstrate
an end-to-end, production-minded architecture.
"""

from __future__ import annotations

from .pipeline import run_pipeline
from .search_index import build_duckdb, open_duckdb

__all__ = [
    "run_pipeline",
    "build_duckdb",
    "open_duckdb",
]