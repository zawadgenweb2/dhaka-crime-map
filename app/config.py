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
    admin_port: int = int(os.getenv("ADMIN_PORT", "8101"))

    # Classifier: gemma (in-house model server, OpenAI-compatible API) | rules (offline keyword baseline)
    classifier: str = os.getenv("CLASSIFIER", "gemma")
    gemma_base_url: str = os.getenv("GEMMA_BASE_URL", "http://127.0.0.1:11434/v1")
    gemma_model: str = os.getenv("GEMMA_MODEL", "gemma4:e2b")
    model_label: str = os.getenv("MODEL_LABEL", "Gemma 4 E2B (in-house)")   # shown on the dashboard
    classify_concurrency: int = int(os.getenv("CLASSIFY_CONCURRENCY", "3"))
    job_lease_minutes: int = int(os.getenv("JOB_LEASE_MINUTES", "20"))
    # auto = publish incidents that pass the automatic checks (default; /review is for optional corrections)
    # review = hold every incident until a human approves it
    publish_mode: str = os.getenv("PUBLISH_MODE", "auto")

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

    # Machine token for scripts (X-Admin-Token) on the admin app only; people log in with their own accounts.
    admin_token: str = os.getenv("ADMIN_TOKEN", "")



settings = Settings()
