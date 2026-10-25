import os
import sys
import tempfile
from pathlib import Path

# Isolated database and no network side effects, set before the app is imported.
_tmp = tempfile.mkdtemp(prefix="dcm-test-")
os.environ["DATABASE_PATH"] = str(Path(_tmp) / "test.db")
os.environ["GEOCODE_ENABLED"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["REQUEST_DELAY_SECONDS"] = "0"
os.environ["CLASSIFY_WORKERS"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
