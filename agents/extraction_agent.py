# agents/extraction_agent.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import json
import os

try:
    import google.generativeai as genai
except ImportError:
    genai = None


@dataclass
class ExtractionConfig:
    """Configuration for ExtractionAgent."""

    gcp_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    model_name: str = os.getenv("GEMINI_VISION_MODEL", "gemini-1.5-pro")
    use_llm: bool = True
    max_summary_chars: int = int(os.getenv("MAX_SUMMARY_CHARS", "600"))


class ExtractionAgent:
    """
    Extracts structured insights from OCR text.

    Produces:
      - page_summary
      - sequence_summary (when aggregating pages)
      - entities (list of {type, text})
      - num_entities (int)
      - search_text (for DuckDB search index)
    """

    def __init__(self, cfg: ExtractionConfig):
        self.cfg = cfg
        self._client = None

        api_key = cfg.gcp_api_key or cfg.google_api_key
        if api_key and genai is not None and cfg.use_llm:
            genai.configure(api_key=api_key)
            self._client = genai.GenerativeModel(cfg.model_name)

    # --------- Constructors -------------------------------------------------

    @classmethod
    def from_env(cls, env_cfg: Dict[str, Any]) -> "ExtractionAgent":
        cfg = ExtractionConfig(
            gcp_api_key=env_cfg.get("gcp_api_key"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            use_llm=True,
        )
        return cls(cfg)

    # --------- Page-level extraction ---------------------------------------

    def extract_page(self, clean_text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extract entities + summary for a single page of text.
        """
        if not clean_text:
            return self._empty_result()

        if self._client is None:
            # Deterministic heuristic fallback
            return self._heuristic_result(clean_text)

        try:
            prompt = (
                "You are an information extraction engine.\n\n"
                "Given the following text, respond with a JSON object with keys:\n"
                "  summary: short natural-language summary (<= 4 sentences)\n"
                "  entities: list of objects {type, text}\n"
                "  search_text: condensed keywords / phrases useful for search\n\n"
                "Text:\n"
                f"{clean_text[:8000]}"
            )

            resp = self._client.generate_content(prompt)
            raw = resp.text or "{}"

            # Best-effort JSON parse
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {
                    "summary": raw,
                    "entities": [],
                    "search_text": clean_text[: self.cfg.max_summary_chars],
                }

            entities = parsed.get("entities", []) or []
            num_entities = len(entities)

            return {
                "page_summary": parsed.get("summary", "")[: self.cfg.max_summary_chars],
                "entities": entities,
                "num_entities": num_entities,
                "search_text": parsed.get("search_text", clean_text[: self.cfg.max_summary_chars]),
            }

        except Exception:
            # Fall back to heuristic extraction
            return self._heuristic_result(clean_text)

    # --------- Sequence-level summarization --------------------------------

    def summarize_sequence(self, texts: List[str]) -> Dict[str, Any]:
        """
        Aggregate multiple pages into a sequence-level summary.
        """
        joined = "\n\n".join(t for t in texts if t)
        if not joined:
            return {"sequence_summary": "", "sequence_search_text": ""}

        if self._client is None:
            summary = joined[: self.cfg.max_summary_chars]
            return {"sequence_summary": summary, "sequence_search_text": summary}

        prompt = (
            "Summarize the following multi-page document as a single coherent thread. "
            "Return no more than 6 sentences.\n\n"
            f"{joined[:8000]}"
        )

        try:
            resp = self._client.generate_content(prompt)
            summary = (resp.text or "").strip()
        except Exception:
            summary = joined[: self.cfg.max_summary_chars]

        return {
            "sequence_summary": summary[: self.cfg.max_summary_chars],
            "sequence_search_text": summary[: self.cfg.max_summary_chars],
        }

    # --------- Internals ----------------------------------------------------

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "page_summary": "",
            "entities": [],
            "num_entities": 0,
            "search_text": "",
        }

    def _heuristic_result(self, text: str) -> Dict[str, Any]:
        """
        Fallback: simple summary + naive entity detection (capitalized tokens).
        """
        words = text.split()
        summary = " ".join(words[: min(len(words), 80)])

        # Very cheap "entities" = capitalized words
        ents = [{"type": "CAP_TOKEN", "text": w} for w in words if w.istitle()]

        return {
            "page_summary": summary[: self.cfg.max_summary_chars],
            "entities": ents,
            "num_entities": len(ents),
            "search_text": summary[: self.cfg.max_summary_chars],
        }
