"""Studio catalog, stored separately from downloader and Live queue history."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudioCatalog:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with closing(self._connect()) as db:
            db.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS streamers (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, avatar_path TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '', categories_json TEXT NOT NULL DEFAULT '[]',
                    genres_json TEXT NOT NULL DEFAULT '[]', games_json TEXT NOT NULL DEFAULT '[]',
                    tags_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                    streamer_id TEXT REFERENCES streamers(id) ON DELETE SET NULL,
                    duration REAL NOT NULL DEFAULT 0, width INTEGER, height INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS clips (
                    id TEXT PRIMARY KEY, source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
                    streamer_id TEXT REFERENCES streamers(id) ON DELETE SET NULL,
                    source_path TEXT NOT NULL, file_path TEXT NOT NULL UNIQUE,
                    source_start REAL NOT NULL DEFAULT 0, source_end REAL NOT NULL DEFAULT 0,
                    duration REAL NOT NULL DEFAULT 0, aspect_ratio TEXT NOT NULL DEFAULT '9:16',
                    title TEXT NOT NULL DEFAULT '', description TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}', transcript TEXT NOT NULL DEFAULT '',
                    thumbnail_path TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
                    genre TEXT NOT NULL DEFAULT '', game TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]', publish_status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collections (
                    id TEXT PRIMARY KEY, streamer_id TEXT REFERENCES streamers(id) ON DELETE SET NULL,
                    name TEXT NOT NULL, settings_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS collection_clips (
                    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                    clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, PRIMARY KEY(collection_id, clip_id)
                );
                CREATE TABLE IF NOT EXISTS publish_jobs (
                    id TEXT PRIMARY KEY, clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, scheduled_at TEXT, youtube_video_id TEXT,
                    error TEXT, uploaded_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(clip_id, scheduled_at)
                );
                CREATE INDEX IF NOT EXISTS clips_created_idx ON clips(created_at DESC);
                CREATE INDEX IF NOT EXISTS publish_schedule_idx ON publish_jobs(scheduled_at, status);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        value = dict(row)
        for key in ("categories_json", "genres_json", "games_json", "tags_json", "metadata_json", "settings_json"):
            if key in value:
                value[key.removesuffix("_json")] = json.loads(value.pop(key) or "[]")
        return value

    def add_streamer(self, name: str, description: str = "", avatar_path: str = "",
                     categories=None, genres=None, games=None, tags=None) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Streamer name is required")
        streamer_id = str(uuid.uuid4())
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""INSERT INTO streamers
                (id,name,avatar_path,description,categories_json,genres_json,games_json,tags_json,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (streamer_id, name, avatar_path, description, self._json(categories or []),
                 self._json(genres or []), self._json(games or []), self._json(tags or []), _now()))
        return streamer_id

    def list_streamers(self) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            return [self._decode(row) for row in db.execute("SELECT * FROM streamers ORDER BY name COLLATE NOCASE")]

    def add_source(self, path: Path, title: str | None = None, streamer_id: str | None = None,
                   duration: float = 0, width: int | None = None, height: int | None = None) -> str:
        source_path = str(Path(path).expanduser().resolve(strict=True))
        if not Path(source_path).is_file():
            raise ValueError("Choose a readable local video file")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute("SELECT id FROM sources WHERE path=?", (source_path,)).fetchone()
            if row:
                db.execute("UPDATE sources SET title=?, streamer_id=?, duration=?, width=?, height=? WHERE id=?",
                           (title or Path(source_path).stem, streamer_id, duration, width, height, row["id"]))
                return str(row["id"])
            source_id = str(uuid.uuid4())
            db.execute("""INSERT INTO sources(id,path,title,streamer_id,duration,width,height,created_at)
                VALUES(?,?,?,?,?,?,?,?)""", (source_id, source_path, title or Path(source_path).stem,
                streamer_id, duration, width, height, _now()))
            return source_id

    def list_sources(self) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            return [dict(row) for row in db.execute("""SELECT s.*, p.name AS streamer_name FROM sources s
                LEFT JOIN streamers p ON p.id=s.streamer_id ORDER BY s.created_at DESC""")]

    def add_clips(self, source_id: str | None, source_path: str, streamer_id: str | None,
                  entries: list[dict], aspect_ratio: str) -> list[str]:
        identifiers, now = [], _now()
        with self._lock, closing(self._connect()) as db, db:
            for entry in entries:
                clip_id = str(uuid.uuid4())
                file_path = str(Path(entry["file"]).expanduser().resolve(strict=True))
                if not Path(file_path).is_file():
                    raise ValueError(f"Rendered clip is missing: {file_path}")
                db.execute("""INSERT INTO clips(id,source_id,streamer_id,source_path,file_path,source_start,
                    source_end,duration,aspect_ratio,title,metadata_json,transcript,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (clip_id, source_id, streamer_id, str(Path(source_path).resolve()), file_path,
                     float(entry.get("source_start", 0)), float(entry.get("source_end", 0)),
                     float(entry.get("duration", 0)), aspect_ratio, Path(file_path).stem,
                     self._json(entry), str(entry.get("caption_transcript") or entry.get("transcript", "")), now, now))
                identifiers.append(clip_id)
        return identifiers

    def list_clips(self, search: str = "", streamer_id: str | None = None) -> list[dict]:
        where, params = [], []
        if search.strip():
            where.append("(c.title LIKE ? OR c.game LIKE ? OR c.category LIKE ? OR c.tags_json LIKE ?)")
            params.extend([f"%{search.strip()}%"] * 4)
        if streamer_id:
            where.append("c.streamer_id=?")
            params.append(streamer_id)
        sql = """SELECT c.*, s.title AS source_title, p.name AS streamer_name FROM clips c
                 LEFT JOIN sources s ON s.id=c.source_id LEFT JOIN streamers p ON p.id=c.streamer_id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY c.created_at DESC"
        with self._lock, closing(self._connect()) as db:
            return [self._decode(row) for row in db.execute(sql, params)]

    def get_clip(self, clip_id: str) -> dict | None:
        with self._lock, closing(self._connect()) as db:
            return self._decode(db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())

    def update_clip(self, clip_id: str, **changes) -> None:
        allowed = {"streamer_id", "title", "description", "metadata_json", "transcript", "thumbnail_path",
                   "category", "genre", "game", "publish_status"}
        data = {key: value for key, value in changes.items() if key in allowed}
        for key in ("tags", "metadata"):
            if key in changes:
                data["tags_json" if key == "tags" else "metadata_json"] = self._json(changes[key])
        if not data:
            return
        data["updated_at"] = _now()
        assignments = ",".join(f"{key}=?" for key in data)
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute(f"UPDATE clips SET {assignments} WHERE id=?", [*data.values(), clip_id])
            if cursor.rowcount == 0:
                raise KeyError(clip_id)

    def create_collection(self, name: str, streamer_id: str | None = None, settings=None) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Collection name is required")
        collection_id = str(uuid.uuid4())
        with self._lock, closing(self._connect()) as db, db:
            db.execute("INSERT INTO collections(id,streamer_id,name,settings_json,created_at) VALUES(?,?,?,?,?)",
                       (collection_id, streamer_id, name, self._json(settings or {}), _now()))
        return collection_id

    def list_collections(self) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            return [self._decode(row) for row in db.execute("SELECT * FROM collections ORDER BY created_at DESC")]

    def set_collection_clips(self, collection_id: str, clip_ids: list[str]) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute("DELETE FROM collection_clips WHERE collection_id=?", (collection_id,))
            db.executemany("INSERT INTO collection_clips(collection_id,clip_id,position) VALUES(?,?,?)",
                           [(collection_id, clip_id, pos) for pos, clip_id in enumerate(clip_ids)])

    def create_publish_job(self, clip_id: str, scheduled_at: str, metadata: dict,
                           status: str = "approved") -> str:
        job_id, now = str(uuid.uuid4()), _now()
        if status not in {"approved", "scheduled"}:
            raise ValueError("New publishing jobs must be approved or scheduled")
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""INSERT INTO publish_jobs(id,clip_id,status,scheduled_at,metadata_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""", (job_id, clip_id, status, scheduled_at, self._json(metadata), now, now))
        return job_id

    def update_publish_job(self, job_id: str, status: str, youtube_video_id: str | None = None,
                           error: str | None = None, metadata: dict | None = None,
                           uploaded_at: str | None = None, scheduled_at: str | None = None) -> None:
        allowed = {"approved", "uploading", "scheduled", "published", "failed", "cancelled", "unknown"}
        if status not in allowed:
            raise ValueError(f"Invalid publish state: {status}")
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("""UPDATE publish_jobs SET status=?, youtube_video_id=COALESCE(?,youtube_video_id),
                error=?, uploaded_at=COALESCE(?,uploaded_at), scheduled_at=COALESCE(?,scheduled_at),
                metadata_json=COALESCE(?,metadata_json),
                updated_at=? WHERE id=?""",
                (status, youtube_video_id, error, uploaded_at, scheduled_at,
                 self._json(metadata) if metadata is not None else None, _now(), job_id))
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            row = db.execute("SELECT clip_id FROM publish_jobs WHERE id=?", (job_id,)).fetchone()
            if row:
                states = {item["status"] for item in db.execute(
                    "SELECT status FROM publish_jobs WHERE clip_id=?", (row["clip_id"],))}
                clip_state = next((candidate for candidate in ("uploading", "scheduled", "published", "unknown", "failed")
                                   if candidate in states), "draft")
                db.execute("UPDATE clips SET publish_status=?,updated_at=? WHERE id=?",
                           (clip_state, _now(), row["clip_id"]))

    def list_publish_jobs(self) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("""SELECT j.*, c.title, c.file_path, c.thumbnail_path FROM publish_jobs j
                JOIN clips c ON c.id=j.clip_id ORDER BY COALESCE(j.scheduled_at,j.created_at) DESC""").fetchall()
            result = []
            for row in rows:
                value = dict(row)
                value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
                result.append(value)
            return result
