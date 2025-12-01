# agents/threading_agent.py
"""
Thread Reconstruction Agent for Project LANTERN.

This module groups manifest rows into logical "threads" or sequences, as
depicted in the Project LANTERN architecture diagram.

In the curated dataset, threading is primarily driven by:
- `sequence_id`     : logical thread identifier (e.g., "seq1", "seq2", ...)
- `sequence_order`  : numeric order within the thread

For rows without a usable `sequence_id`, each page is treated as its own
singleton sequence (keyed by file_path). This keeps the interface simple
while still allowing non-threaded documents to flow through the same
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping
import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ThreadingAgentConfig:
    """
    Configuration for ThreadingAgent.

    Attributes
    ----------
    enable_threads:
        If False, each page will be treated as a standalone sequence with
        a synthetic sequence_id derived from its file_path.
    """

    enable_threads: bool = True


def _sequence_id_is_missing(seq_id: Any) -> bool:
    """
    Best-effort check for an unusable sequence_id.

    Treats None, empty strings, and NaN-like floats as "missing".
    """
    if seq_id is None:
        return True
    if isinstance(seq_id, str) and not seq_id.strip():
        return True
    if isinstance(seq_id, float):
        try:
            return math.isnan(seq_id)
        except Exception:
            return False
    return False


class ThreadingAgent:
    """
    Agent responsible for grouping manifest rows into sequences/threads.

    Core API
    --------
        ThreadingAgent.group_sequences(rows: List[Dict[str, Any]])
            -> Dict[str, List[Dict[str, Any]]]

    The returned mapping is:

        sequence_id (str) -> ordered list of manifest rows

    This aligns with the "Thread Reconstruction Agent" in the architecture
    diagram and provides the orchestration layer with well-defined units
    of work for downstream extraction and summarization.
    """

    def __init__(
        self,
        config: ThreadingAgentConfig | None = None,
        *,
        enable_threads: bool | None = None,
    ) -> None:
        """
        Initialize a ThreadingAgent.

        Parameters
        ----------
        config:
            Optional ThreadingAgentConfig instance. If not provided, a
            default config is created.
        enable_threads:
            Optional convenience override. If provided, it sets
            config.enable_threads directly, allowing the notebook to
            instantiate the agent as:

                ThreadingAgent(enable_threads=False)
        """
        if config is None:
            config = ThreadingAgentConfig()

        if enable_threads is not None:
            config.enable_threads = enable_threads

        self.config = config
        logger.debug("Initialized ThreadingAgent with config: %s", self.config)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # Placeholder for any future subclassing behavior.
        super().__init_subclass__(**kwargs)

    def group_sequences(self, rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group manifest rows into ordered sequences.

        Parameters
        ----------
        rows:
            Each row should contain at least:
            - file_path       : str
            - sequence_id     : (optional) str or NaN/None
            - sequence_order  : (optional) int/float or NaN/None

        Returns
        -------
        Dict[str, List[Dict[str, Any]]]
            Mapping of sequence_id -> ordered list of rows.

        Behavior
        --------
        - If enable_threads=False:
            Each row is treated as its own sequence, keyed by file_path.
        - If enable_threads=True:
            Rows are grouped by sequence_id. Missing/NaN IDs are turned
            into "singleton::<file_path>" so every page still flows through
            the pipeline in a consistent way.
        """
        if not rows:
            logger.info("ThreadingAgent.group_sequences called with 0 rows.")
            return {}

        # No-thread mode: treat each row as its own sequence
        if not self.config.enable_threads:
            logger.info(
                "ThreadingAgent running in 'no-thread' mode; "
                "treating each row as its own sequence."
            )
            return {
                str(row.get("file_path", f"seq_{idx}")): [row]
                for idx, row in enumerate(rows)
            }

        grouped: MutableMapping[str, List[Dict[str, Any]]] = defaultdict(list)

        for row in rows:
            seq_id = row.get("sequence_id")
            file_path = row.get("file_path", "<unknown>")

            # If sequence_id is missing/NaN, treat file_path as its own sequence ID
            if _sequence_id_is_missing(seq_id):
                seq_id = f"singleton::{file_path}"

            grouped[str(seq_id)].append(row)

        # Sort rows within each sequence by sequence_order (if present)
        ordered: Dict[str, List[Dict[str, Any]]] = {}

        for seq_id, items in grouped.items():

            def sort_key(r: Mapping[str, Any]) -> float:
                val = r.get("sequence_order")
                try:
                    return float(val)
                except Exception:
                    # Non-numeric or missing: push to the end
                    return 1e9

            ordered_rows = sorted(items, key=sort_key)
            ordered[seq_id] = ordered_rows

        logger.info(
            "ThreadingAgent grouped %d rows into %d sequences.",
            len(rows),
            len(ordered),
        )
        return ordered