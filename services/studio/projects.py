"""Recoverable Studio projects stored alongside the existing Studio catalog.

This module owns only the additive ``studio_projects`` table. Pass the path already used for
``StudioCatalog`` (for example ``.streamcarnia/studio_library.sqlite3``).
Existing catalog tables and referenced media files are never changed here.

Project API:
    create_project(name, source_path=None, project_id=None) -> id
    save_project(id, **fields) / autosave(id, **fields)
    get_project(id) -> dict | None; list_projects() -> list[dict]
    delete_project(id) -> bool (deletes project state, not media/catalog data)
    relink_source(id, path) -> updated project
    source_status(project_or_id) -> {path, exists, ...}

Ranges are lists of ``[start_seconds, end_seconds]`` pairs. Editor settings
are JSON-compatible dictionaries and ``current_stage`` is an opaque UI stage
identifier so this store does not couple persistence to a particular UI.
Candidate payloads preserve real scores, timestamps, and reasons in a JSON
column, with review state kept alongside each payload.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _decode_project(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    result = dict(row)
    result["ranges"] = json.loads(result.pop("ranges_json"))
    result["editor_settings"] = json.loads(result.pop("editor_settings_json"))
    result["candidates"] = json.loads(result.pop("candidates_json"))
    return result


class StudioProjectStore:
    """Thread-safe CRUD/autosave for project sessions in the catalog database."""

    _PROJECT_FIELDS = {"name", "source_path", "ranges", "editor_settings", "current_stage"}

    def __init__(self, catalog_path: Path):
        self.path = Path(catalog_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS studio_projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_path TEXT,
                    ranges_json TEXT NOT NULL DEFAULT '[]',
                    editor_settings_json TEXT NOT NULL DEFAULT '{}',
                    candidates_json TEXT NOT NULL DEFAULT '[]',
                    current_stage TEXT NOT NULL DEFAULT 'home',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS studio_projects_updated_idx
                    ON studio_projects(updated_at DESC);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _normalize_ranges(ranges: Any) -> list[list[float]]:
        if ranges is None:
            return []
        result: list[list[float]] = []
        for item in ranges:
            if isinstance(item, dict):
                start, end = item.get("start"), item.get("end")
            else:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    raise ValueError("Each range must contain start and end seconds")
                start, end = item
            try:
                start, end = float(start), float(end)
            except (TypeError, ValueError) as exc:
                raise ValueError("Range endpoints must be numbers") from exc
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                raise ValueError("Ranges must be finite, non-negative, and have end > start")
            result.append([start, end])
        return result

    @staticmethod
    def _normalize_source(path: str | Path | None, require_exists: bool = False) -> str | None:
        if path is None or not str(path).strip():
            return None
        resolved = Path(path).expanduser().resolve(strict=require_exists)
        if require_exists and not resolved.is_file():
            raise ValueError("Source must be an existing file")
        return str(resolved)

    def create_project(self, name: str, source_path: str | Path | None = None,
                       project_id: str | None = None) -> str:
        name = str(name).strip()
        if not name:
            raise ValueError("Project name is required")
        identifier, now = project_id or str(uuid.uuid4()), _now()
        source = self._normalize_source(source_path)
        with self._lock, closing(self._connect()) as db, db:
            db.execute("""INSERT INTO studio_projects
                (id,name,source_path,ranges_json,editor_settings_json,candidates_json,current_stage,created_at,updated_at)
                VALUES(?,?,?,'[]','{}','[]','home',?,?)""", (identifier, name, source, now, now))
        return identifier

    def save_project(self, project_id: str, **fields) -> dict:
        """Update project state; omitted fields retain their previous values."""
        unknown = set(fields) - self._PROJECT_FIELDS
        if unknown:
            raise ValueError(f"Unsupported project fields: {', '.join(sorted(unknown))}")
        if "name" in fields and not str(fields["name"]).strip():
            raise ValueError("Project name is required")
        data = {}
        for key, value in fields.items():
            if key == "name":
                data[key] = str(value).strip()
            elif key == "source_path":
                # Missing paths are valid persisted state so projects can be recovered/relinked.
                data[key] = self._normalize_source(value)
            elif key == "ranges":
                data["ranges_json"] = _json(self._normalize_ranges(value))
            elif key == "editor_settings":
                if not isinstance(value, dict):
                    raise ValueError("Editor settings must be a dictionary")
                data["editor_settings_json"] = _json(value)
            elif key == "current_stage":
                stage = str(value).strip()
                if not stage:
                    raise ValueError("Current stage cannot be empty")
                data[key] = stage
        with self._lock, closing(self._connect()) as db, db:
            if data:
                data["updated_at"] = _now()
                assignments = ",".join(f"{key}=?" for key in data)
                cursor = db.execute(f"UPDATE studio_projects SET {assignments} WHERE id=?",
                                    [*data.values(), project_id])
                if cursor.rowcount == 0:
                    raise KeyError(project_id)
            row = db.execute("SELECT * FROM studio_projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            return _decode_project(row)

    def autosave(self, project_id: str, **fields) -> dict:
        """Explicit alias for save_project, intended for debounced UI autosave."""
        return self.save_project(project_id, **fields)

    def get_project(self, project_id: str) -> dict | None:
        with self._lock, closing(self._connect()) as db:
            return _decode_project(db.execute("SELECT * FROM studio_projects WHERE id=?", (project_id,)).fetchone())

    def list_projects(self) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM studio_projects ORDER BY updated_at DESC").fetchall()
            return [_decode_project(row) for row in rows]

    def delete_project(self, project_id: str) -> bool:
        """Delete only saved project/candidate state; media and catalog rows remain untouched."""
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("DELETE FROM studio_projects WHERE id=?", (project_id,))
            return cursor.rowcount > 0

    def source_status(self, project_or_id: dict | str) -> dict:
        project = self.get_project(project_or_id) if isinstance(project_or_id, str) else project_or_id
        if project is None:
            raise KeyError(project_or_id)
        raw = project.get("source_path")
        path = Path(raw) if raw else None
        exists = bool(path and path.is_file())
        return {"project_id": project["id"], "path": str(path) if path else None, "exists": exists,
                "missing": bool(path) and not exists, "needs_source": not bool(path)}

    def relink_source(self, project_id: str, path: str | Path) -> dict:
        """Relink to an existing file without modifying either source file or catalog source rows."""
        source = self._normalize_source(path, require_exists=True)
        return self.save_project(project_id, source_path=source)

    def save_candidates(self, project_id: str, candidates: list[dict]) -> None:
        """Replace persisted candidates from real detector output, preserving payload verbatim."""
        if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
            raise ValueError("Candidates must be a list of dictionaries")
        now = _now()
        records = []
        for position, candidate in enumerate(candidates):
            candidate_id = str(candidate.get("id") or candidate.get("rank") or uuid.uuid4())
            records.append((candidate_id, project_id, position, _json(candidate), now, now))
        candidates_value = [{"id": identifier, "position": position, "payload": json.loads(payload),
                             "review_state": "pending", "created_at": created, "updated_at": updated}
                            for identifier, _project, position, payload, created, updated in records]
        with self._lock, closing(self._connect()) as db, db:
            cursor = db.execute("UPDATE studio_projects SET candidates_json=?,updated_at=? WHERE id=?",
                                (_json(candidates_value), now, project_id))
            if cursor.rowcount == 0:
                raise KeyError(project_id)

    def list_candidates(self, project_id: str) -> list[dict]:
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        return project["candidates"]

    def set_candidate_review(self, project_id: str, candidate_id: str, state: str) -> None:
        if state not in {"pending", "favorite", "rejected", "selected"}:
            raise ValueError("Review state must be pending, favorite, rejected, or selected")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute("SELECT candidates_json FROM studio_projects WHERE id=?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            candidates = json.loads(row["candidates_json"])
            candidate = next((item for item in candidates if item["id"] == candidate_id), None)
            if candidate is None:
                raise KeyError((project_id, candidate_id))
            candidate["review_state"] = state
            candidate["updated_at"] = _now()
            db.execute("UPDATE studio_projects SET candidates_json=?,updated_at=? WHERE id=?",
                       (_json(candidates), _now(), project_id))
