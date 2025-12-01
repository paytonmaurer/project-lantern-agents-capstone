# agents/ocr_agent.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import os
import pathlib

try:
    import google.generativeai as genai
except ImportError:
    genai = None  # handled gracefully below


@dataclass
class OCRAgentConfig:
    """
    Configuration for OCRAgent.

    Attributes
    ----------
    gcp_api_key:
        Vertex / Gemini API key (preferred if available).
    google_api_key:
        Gemini Studio / Google AI Studio API key (fallback).
    model_name:
        Vision-capable Gemini model to use for OCR.
    use_mock_if_no_key:
        If True, fall back to deterministic mock OCR when no client is
        available so the pipeline never fully breaks.
    """

    gcp_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    model_name: str = os.getenv("GEMINI_OCR_MODEL", "gemini-1.5-flash")
    use_mock_if_no_key: bool = True


class OCRAgent:
    """
    Backend-agnostic OCR agent for Project LANTERN.

    Priority:
      1. Gemini / Vertex API via GCP_API_KEY or GOOGLE_API_KEY
      2. Deterministic mock output (for offline / demo use)

    Public API:
      - run_page(image_path, page_meta=None) -> Dict[str, Any]
      - run(...) alias for backwards compatibility

    Returned schema (best-effort, stable keys):

      {
        "raw_text": str,
        "clean_text": str,
        "ocr_text": str,          # alias for UI / notebooks
        "ocr_text_length": int,
        "confidence": float | None,
        "error": str | None,
        "model": str | None,
        "engine": "gemini" | "mock" | "none"
      }
    """

    def __init__(self, cfg: OCRAgentConfig):
        self.cfg = cfg
        self._client = None

        api_key = cfg.gcp_api_key or cfg.google_api_key
        if api_key and genai is not None:
            try:
                genai.configure(api_key=api_key)
                self._client = genai.GenerativeModel(cfg.model_name)
            except Exception:
                # If anything goes wrong initializing the client, leave it as None.
                self._client = None

    # --------- Constructors -------------------------------------------------

    @classmethod
    def from_env(cls, env_cfg: Dict[str, Any]) -> "OCRAgent":
        """
        Build an OCRAgent from the env dict produced by utils_env.load_environment().

        Expected env_cfg keys:
          - gcp_api_key
          - (optional) anything else you may pass through
        """
        cfg = OCRAgentConfig(
            gcp_api_key=env_cfg.get("gcp_api_key"),
            google_api_key=os.getenv("GOOGLE_API_KEY"),
        )
        return cls(cfg)

    # --------- Properties ---------------------------------------------------

    @property
    def client_active(self) -> bool:
        """Return True if a real Gemini client is configured and usable."""
        return self._client is not None

    @property
    def backend(self) -> str:
        """Human-friendly backend label."""
        if self._client is not None:
            return "gemini"
        if self.cfg.use_mock_if_no_key:
            return "mock"
        return "none"

    # --------- Public API ---------------------------------------------------

    def run_page(
        self,
        image_path: str,
        page_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Run OCR on a single page.

        Parameters
        ----------
        image_path:
            Path to the image file on disk.
        page_meta:
            Optional dict of manifest metadata for this page (unused for now,
            but kept for future prompt-conditioning).

        Returns
        -------
        Dict[str, Any]:
            Normalized OCR record with keys:
              - raw_text
              - clean_text
              - ocr_text
              - ocr_text_length
              - confidence
              - error
              - model
              - engine
        """
        # Early file-existence check for clearer errors
        if not os.path.exists(image_path):
            return {
                "raw_text": "",
                "clean_text": "",
                "ocr_text": "",
                "ocr_text_length": 0,
                "confidence": None,
                "error": f"File not found: {image_path}",
                "model": self.cfg.model_name,
                "engine": "none",
            }

        # If client is unavailable and mock mode is allowed, use deterministic mock
        if self._client is None:
            if self.cfg.use_mock_if_no_key:
                return self._mock_response(image_path, page_meta)
            else:
                return {
                    "raw_text": "",
                    "clean_text": "",
                    "ocr_text": "",
                    "ocr_text_length": 0,
                    "confidence": None,
                    "error": "No Gemini client configured and mock mode disabled.",
                    "model": self.cfg.model_name,
                    "engine": "none",
                }

        try:
            # Read image bytes
            with open(image_path, "rb") as f:
                img_bytes = f.read()

            prompt = (
                "You are an OCR engine. Return ONLY the visible text on this page. "
                "Do not add commentary or explanations."
            )

            resp = self._client.generate_content(
                contents=[
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "data": img_bytes,
                                    "mime_type": _guess_mime_type(image_path),
                                }
                            },
                        ],
                    }
                ]
            )

            raw_text = (getattr(resp, "text", "") or "").strip()
            clean_text = " ".join(raw_text.split())
            length = len(clean_text)

            return {
                "raw_text": raw_text,
                "clean_text": clean_text,
                "ocr_text": raw_text,              # 🔑 alias used by notebooks / UI
                "ocr_text_length": length,
                "confidence": None,                # Gemini doesn't expose a simple scalar here
                "error": None,
                "model": self.cfg.model_name,
                "engine": "gemini",
            }

        except Exception as e:
            # Fall back to mock so the pipeline never fully breaks
            return self._mock_response(image_path, page_meta, error=str(e))

    # Backwards-compatible alias for older code that calls ocr_agent.run(...)
    def run(
        self,
        image_path: str,
        page_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Alias to run_page for legacy calls."""
        return self.run_page(image_path, page_meta=page_meta)

    # --------- Internals ----------------------------------------------------

    def _mock_response(
        self,
        image_path: str,
        page_meta: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Deterministic offline OCR for demos / when no key is configured.

        This keeps the rest of the LANTERN pipeline fully runnable even when
        external OCR is unavailable.
        """
        filename = os.path.basename(image_path)
        text = f"[MOCK_OCR] Text for {filename}"
        clean_text = text

        return {
            "raw_text": text,
            "clean_text": clean_text,
            "ocr_text": text,                # 🔑 alias for visualizations
            "ocr_text_length": len(clean_text),
            "confidence": 0.0,
            "error": error,
            "model": self.cfg.model_name,
            "engine": "mock",
        }


# --------- Helper -----------------------------------------------------------

def _guess_mime_type(path: str) -> str:
    """
    Very small helper to guess a sensible mime type from the file extension.
    Defaults to image/jpeg if unsure.
    """
    suffix = pathlib.Path(path).suffix.lower()
    if suffix in {".png"}:
        return "image/png"
    if suffix in {".webp"}:
        return "image/webp"
    if suffix in {".tiff", ".tif"}:
        return "image/tiff"
    # Fallback
    return "image/jpeg"