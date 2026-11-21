import sqlite3

import pytest

from services.studio.catalog import StudioCatalog
from services.studio.projects import StudioProjectStore


def test_project_autosave_recovery_relink_and_additive_schema(tmp_path):
    db_path = tmp_path / ".streamcarnia" / "studio_library.sqlite3"
    catalog = StudioCatalog(db_path)
    media = tmp_path / "stream.mp4"
    media.write_bytes(b"placeholder")
    source_id = catalog.add_source(media, title="Source", duration=5, width=1920, height=1080)
    store = StudioProjectStore(db_path)

    project_id = store.create_project("Valorant edit", media)
    saved = store.autosave(project_id, ranges=[[1, 3], {"start": 3.5, "end": 4}],
                           editor_settings={"layout": "square", "caption_style": "word"},
                           current_stage="editor")
    assert saved["ranges"] == [[1.0, 3.0], [3.5, 4.0]]
    assert saved["editor_settings"]["layout"] == "square"
    assert saved["current_stage"] == "editor"
    assert store.source_status(project_id)["exists"] is True

    media.unlink()
    assert store.source_status(project_id)["missing"] is True
    replacement = tmp_path / "relinked.mp4"
    replacement.write_bytes(b"replacement")
    assert store.relink_source(project_id, replacement)["source_path"] == str(replacement.resolve())
    assert store.get_project(project_id)["ranges"] == [[1.0, 3.0], [3.5, 4.0]]
    assert catalog.list_sources()[0]["id"] == source_id

    with sqlite3.connect(db_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "studio_projects" in tables
    assert "studio_project_candidates" not in tables
    assert {"sources", "clips", "publish_jobs"}.issubset(tables)


def test_project_candidate_payload_and_review_state_persist(tmp_path):
    db_path = tmp_path / "studio.sqlite3"
    store = StudioProjectStore(db_path)
    project_id = store.create_project("Discovery")
    original = {"rank": 1, "start": 12.5, "end": 32.5, "score": 0.84,
                "reasons": ["audio_spike"], "label": "Exciting moment"}
    store.save_candidates(project_id, [original])
    [candidate] = store.list_candidates(project_id)
    assert candidate["payload"] == original
    store.set_candidate_review(project_id, candidate["id"], "favorite")
    reopened = StudioProjectStore(db_path)
    [candidate] = reopened.list_candidates(project_id)
    assert candidate["review_state"] == "favorite"
    assert candidate["payload"] == original


def test_project_validation_and_delete_only_removes_project_state(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"source")
    store = StudioProjectStore(tmp_path / "studio.sqlite3")
    project_id = store.create_project("Project", media)
    with pytest.raises(ValueError):
        store.autosave(project_id, ranges=[[3, 2]])
    with pytest.raises(ValueError):
        store.create_project("  ")
    assert store.delete_project(project_id) is True
    assert store.get_project(project_id) is None
    assert store.delete_project(project_id) is False
    assert media.read_bytes() == b"source"


