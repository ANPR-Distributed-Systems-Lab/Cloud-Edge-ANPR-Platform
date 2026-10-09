import json
from datetime import datetime, timezone


def log(event: str, **fields) -> None:
    """Structured JSON log line (project convention: all edge logs are JSON)."""
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}, default=str), flush=True)
