"""Settings from the environment (and a local .env for non-Docker runs). Safe defaults throughout."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # absent inside the Docker images (never copied in)


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "postgresql://dcm:dcm@127.0.0.1:5432/dcm")
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8100"))

    # Classifier: claude (prototype) | gemma (local, OpenAI-compatible server) | rules (offline)
    classifier: str = os.getenv("CLASSIFIER", "claude")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    gemma_base_url: str = os.getenv("GEMMA_BASE_URL", "http://127.0.0.1:11434/v1")
    gemma_model: str = os.getenv("GEMMA_MODEL", "gemma4:e2b")
    classify_concurrency: int = int(os.getenv("CLASSIFY_CONCURRENCY", "3"))
    # Hard cost guard: paid model calls allowed per Asia/Dhaka day (0 = unlimited)
    max_llm_calls_per_day: int = int(os.getenv("MAX_LLM_CALLS_PER_DAY", "200"))
    job_lease_minutes: int = int(os.getenv("JOB_LEASE_MINUTES", "20"))

    # Collector schedule (Asia/Dhaka wall-clock times)
    scrape_times: list[str] = field(default_factory=lambda: _list("SCRAPE_TIMES", "08:00,20:00"))

    # Scraping
    user_agent: str = os.getenv("USER_AGENT", "DhakaCrimeMap/0.2 (research prototype)")
    request_delay: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))
    max_articles_per_run: int = int(os.getenv("MAX_ARTICLES_PER_RUN", "150"))

    # Exact-spot geocoding. Public Nominatim allows scheduled scripts 4 requests/minute.
    geocode_enabled: bool = _bool("GEOCODE_ENABLED", True)
    nominatim_url: str = os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
    geocode_min_interval: float = float(os.getenv("GEOCODE_MIN_INTERVAL_SECONDS", "15"))

    # Map
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    google_maps_map_id: str = os.getenv("GOOGLE_MAPS_MAP_ID", "")

    # "Collect now": dashboard button (same-origin + custom header) and/or X-Admin-Token for scripts
    allow_ui_trigger: bool = _bool("ALLOW_UI_TRIGGER", True)
    admin_token: str = os.getenv("ADMIN_TOKEN", "")


settings = Settings()
