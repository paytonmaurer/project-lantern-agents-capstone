import os
from dotenv import load_dotenv


def load_environment():
    """
    Load .env configuration and return a structured config dict.

    This keeps all environment-related logic in one place so agents and
    pipelines can stay focused on their specific responsibilities.
    """
    load_dotenv()

    gcp_project = os.getenv("GCP_PROJECT_ID")
    gcp_location = os.getenv("GCP_LOCATION", "us-central1")
    gcp_api_key = os.getenv("GCP_API_KEY")
    google_api_key = os.getenv("GOOGLE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    google_app_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    # Decide which key will be used for Gemini / Vertex calls if the caller
    # doesn't explicitly override.
    if gcp_api_key:
        gemini_key_source = "GCP_API_KEY"
        effective_gemini_key = gcp_api_key
    elif google_api_key:
        gemini_key_source = "GOOGLE_API_KEY"
        effective_gemini_key = google_api_key
    else:
        gemini_key_source = None
        effective_gemini_key = None

    cfg = {
        # Core GCP / Gemini
        "gcp_project": gcp_project,
        "gcp_location": gcp_location,
        "gcp_api_key": gcp_api_key,
        "google_api_key": google_api_key,
        "effective_gemini_key": effective_gemini_key,
        "gemini_key_source": gemini_key_source,

        # Optional OpenAI fallback
        "openai_key": openai_key,

        # Optional service-account based auth
        "google_app_creds": google_app_creds,

        # Feature flags
        "use_ocr_cache": os.getenv("USE_OCR_CACHE", "true").lower() == "true",
        "enable_entities": os.getenv("ENABLE_ENTITIES", "true").lower() == "true",
        "enable_seq_summary": os.getenv("ENABLE_SEQUENCE_SUMMARY", "true").lower() == "true",
        "debug": os.getenv("ENABLE_DEBUG_LOGS", "false").lower() == "true",

        # Numeric settings
        "ocr_timeout": int(os.getenv("OCR_TIMEOUT_SECONDS", "30")),
        "ocr_retries": int(os.getenv("MAX_OCR_RETRIES", "2")),
        "max_summary_chars": int(os.getenv("MAX_SUMMARY_CHARS", "600")),

        # Paths
        "project_root": os.getenv("PROJECT_ROOT", "./"),
        "data_root": os.getenv("DATA_ROOT", "./data"),
        "ocr_cache_dir": os.getenv("OCR_CACHE_DIR", "./data/ocr_cache"),
        "export_dir": os.getenv("EXPORT_DIR", "./data/outputs"),
    }

    # Pretty print status (without revealing secrets)
    print("🔧 Environment loaded:")
    print(f"   • GCP Project: {cfg['gcp_project']}")
    print(f"   • Location: {cfg['gcp_location']}")
    print(f"   • Gemini key source: {cfg['gemini_key_source'] or 'NONE'}")
    print(f"   • OpenAI key present: {bool(cfg['openai_key'])}")
    print(f"   • OCR cache enabled: {cfg['use_ocr_cache']}")
    print(f"   • Entities enabled: {cfg['enable_entities']}")
    print(f"   • Sequence summary enabled: {cfg['enable_seq_summary']}")

    if cfg["effective_gemini_key"] is None:
        print("⚠️  No Gemini / Vertex API key detected. "
              "OCR agents using Gemini will not function until a key is set.")

    return cfg