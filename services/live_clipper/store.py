"""Durable live-job state in a database separate from download history."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from core.paths import app_data_dir


class LiveJobStore:
    STATES = {"detected", "rendered", "titled", "scheduled", "uploaded", "failed"}

    def __init__(self, path: Path | None = None):
        self.path = Path(path or (app_data_dir() / "live_clipper" / "live_jobs.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with closing(self._connect()) as db:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS live_jobs (
                    id TEXT PRIMARY KEY, stream_url TEXT NOT NULL, state TEXT NOT NULL,
                    data_json TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""")

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def create(self, stream_url: str, data: dict | None = None) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self._connect()) as db:
            with db:
                db.execute("INSERT INTO live_jobs VALUES (?, ?, ?, ?, NULL, ?, ?)",
                           (job_id, stream_url, "detected", json.dumps(data or {}, ensure_ascii=False), now, now))
        return job_id

    def update(self, job_id: str, state: str, data: dict | None = None, error: str | None = None) -> None:
        if state not in self.STATES:
            raise ValueError(f"Unknown live job state: {state}")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, closing(self._connect()) as db:
            with db:
                old = db.execute("SELECT data_json FROM live_jobs WHERE id=?", (job_id,)).fetchone()
                if old is None:
                    raise KeyError(job_id)
                merged = json.loads(old["data_json"])
                if data:
                    merged.update(data)
                db.execute("UPDATE live_jobs SET state=?, data_json=?, error=?, updated_at=? WHERE id=?",
                           (state, json.dumps(merged, ensure_ascii=False), error, now, job_id))

    def list_jobs(self, stream_url: str | None = None) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM live_jobs" + (" WHERE stream_url=?" if stream_url else "") +
                              " ORDER BY created_at", ((stream_url,) if stream_url else ())).fetchall()
        return [{**dict(row), "data": json.loads(row["data_json"])} for row in rows]
