import os
import sys
from pathlib import Path

# No network side effects in tests; DB tests use TEST_DATABASE_URL (see compose.yaml `test` service).
os.environ.setdefault("GEOCODE_ENABLED", "false")
os.environ.setdefault("REQUEST_DELAY_SECONDS", "0")
os.environ.setdefault("CLASSIFY_CONCURRENCY", "1")
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
