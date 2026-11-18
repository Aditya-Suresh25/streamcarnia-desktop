"""Spawn-safe live worker entry point. Capture/detection stages plug in here."""
from __future__ import annotations

import json
import time
from pathlib import Path


def run_worker(config_path: str) -> int:
    """Keep worker lifetime out of the UI process; append machine-readable events."""
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    event_path = Path(config["event_path"])
    stop_path = Path(config["stop_path"])

    def emit(event: dict) -> None:
        with event_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()

    emit({"type": "started", "stream_url": config.get("stream_url", "")})
    while True:
        if stop_path.exists():
            emit({"type": "stopped"})
            return 0
        time.sleep(0.25)
