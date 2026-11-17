import json
from datetime import UTC, datetime


def log(event: str, level: str = "info", **fields) -> None:
    """Structured JSON log line (project convention: all edge logs are JSON)."""
    line = {"ts": datetime.now(UTC).isoformat(), "level": level, "event": event, **fields}
    print(json.dumps(line, default=str), flush=True)
