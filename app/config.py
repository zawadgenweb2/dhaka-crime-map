"""Settings from environment / .env. Everything has a safe default."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    database_path: Path = field(default_factory=lambda: ROOT / os.getenv("DATABASE_PATH", "data/crime.db"))
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = int(os.getenv("PORT", "8100"))

    # Classifier: claude (prototype), gemma (future, OpenAI-compatible local server), rules (offline)
    classifier: str = os.getenv("CLASSIFIER", "claude")
    claude_model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    claude_effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    gemma_base_url: str = os.getenv("GEMMA_BASE_URL", "http://127.0.0.1:11434/v1")
    gemma_model: str = os.getenv("GEMMA_MODEL", "gemma4:e2b")
    classify_workers: int = int(os.getenv("CLASSIFY_WORKERS", "3"))

    # Schedule (Asia/Dhaka wall-clock times)
    scheduler_enabled: bool = _bool("SCHEDULER_ENABLED", True)
    scrape_times: list[str] = field(default_factory=lambda: _list("SCRAPE_TIMES", "08:00,20:00"))

    # Scraping
    user_agent: str = os.getenv("USER_AGENT", "DhakaCrimeMap/0.1 (research prototype)")
    request_delay: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))
    max_articles_per_run: int = int(os.getenv("MAX_ARTICLES_PER_RUN", "150"))

    # Geocoding of exact landmarks (OpenStreetMap Nominatim); gazetteer is always used
    geocode_enabled: bool = _bool("GEOCODE_ENABLED", True)

    # Map
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    google_maps_map_id: str = os.getenv("GOOGLE_MAPS_MAP_ID", "")

    # Protects POST /api/scrape. Empty = only requests from localhost may trigger runs.
    admin_token: str = os.getenv("ADMIN_TOKEN", "")


settings = Settings()
