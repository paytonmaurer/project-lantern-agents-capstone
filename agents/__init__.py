# agents/__init__.py
"""
Agent layer for Project LANTERN.

This package defines the three core agents used throughout the pipeline:

- OCRAgent
    Vision-based OCR over scanned pages (e.g., GPT-4o Vision).
- ThreadingAgent
    Thread reconstruction over manifest rows (sequence_id + sequence_order).
- ExtractionAgent
    Page-level and sequence-level enrichment (stats, entities, summaries).

These agents are intentionally lightweight and framework-agnostic:
they expose clear Python interfaces that the orchestration layer can call,
while hiding the underlying model / API details.

Typical usage
-------------
from agents import (
    OCRAgent, OCRAgentConfig,
    ThreadingAgent, ThreadingAgentConfig,
    ExtractionAgent, ExtractionConfig,
)
"""

from __future__ import annotations

from .ocr_agent import OCRAgent, OCRAgentConfig
from .threading_agent import ThreadingAgent, ThreadingAgentConfig
from .extraction_agent import ExtractionAgent, ExtractionConfig

__all__ = [
    "OCRAgent",
    "OCRAgentConfig",
    "ThreadingAgent",
    "ThreadingAgentConfig",
    "ExtractionAgent",
    "ExtractionConfig",
]