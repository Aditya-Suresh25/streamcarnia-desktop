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
    STATES = {"detected", "rendered", "titled", "scheduled", "uploading", "uploaded", "failed", "unknown"}

    def __init__(self, path: Path | None = None, migrate_legacy: bool = False):
        legacy_path = app_data_dir() / "live_clipper" / "live_jobs.sqlite3" if migrate_legacy or path is None else None
        self.path = Path(path or legacy_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with closing(self._connect()) as db:
            with db:
                db.execute("""CREATE TABLE IF NOT EXISTS live_jobs (
                    id TEXT PRIMARY KEY, stream_url TEXT NOT NULL, state TEXT NOT NULL,
                    data_json TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""")
        if path is not None and migrate_legacy and legacy_path and self.path.resolve() != legacy_path.resolve():
            self._migrate_legacy(legacy_path)

    def _migrate_legacy(self, legacy_path: Path) -> None:
        if not legacy_path.is_file():
            return
        try:
            with closing(sqlite3.connect(legacy_path)) as source, closing(self._connect()) as target:
                source.row_factory = sqlite3.Row
                rows = source.execute("SELECT * FROM live_jobs").fetchall()
                media_root = self.path.parent.parent.resolve()
                transferable = []
                for row in rows:
                    data = json.loads(row["data_json"])
                    candidate = data.get("session_dir")
                    if not candidate and data.get("file_path"):
                        candidate = str(Path(data["file_path"]).parent.parent.parent)
                    if candidate:
                        try:
                            Path(candidate).resolve().relative_to(media_root)
                        except (OSError, ValueError):
                            continue
                    else:
                        continue
                    transferable.append(tuple(row[key] for key in (
                        "id", "stream_url", "state", "data_json", "error", "created_at", "updated_at")))
                with target:
                    target.executemany(
                        "INSERT OR IGNORE INTO live_jobs VALUES (?, ?, ?, ?, ?, ?, ?)",
                        transferable,
                    )
        except (sqlite3.Error, OSError, ValueError):
            # Preserve existing jobs if an old app version briefly holds the DB.
            return

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

    def clear_jobs(self) -> int:
        """Clear live queue records only; callers separately remove validated session folders."""
        with self._lock, closing(self._connect()) as db:
            with db:
                cursor = db.execute("DELETE FROM live_jobs")
                return cursor.rowcount
