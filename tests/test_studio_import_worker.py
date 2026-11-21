import pytest

pytest.importorskip("PySide6")

from services.studio.catalog import StudioCatalog
from workers.studio_import_worker import StudioImportWorker


def test_import_worker_probes_off_ui_path_continues_errors_and_preserves_existing_source(
        tmp_path, monkeypatch):
    from services.studio import media

    db_path = tmp_path / "studio.sqlite3"
    catalog = StudioCatalog(db_path)
    streamer_id = catalog.add_streamer("Existing creator")
    existing = tmp_path / "existing.mp4"
    existing.write_bytes(b"existing")
    existing_id = catalog.add_source(existing, "Curated title", streamer_id, 12, 1280, 720)
    new_source = tmp_path / "new.mp4"
    new_source.write_bytes(b"new")
    missing = tmp_path / "missing.mp4"

    def fake_probe(path, ffmpeg_path=None):
        if path.name == "new.mp4":
            return {"duration": 90, "width": 1920, "height": 1080}
        return {"duration": 12, "width": 1280, "height": 720}

    monkeypatch.setattr(media, "probe_media", fake_probe)
    worker = StudioImportWorker([existing, missing, new_source], db_path, streamer_id=None)
    observed = {"progress": [], "finished": [], "failed": [], "cancelled": []}
    for key in observed:
        getattr(worker.signals, key).connect(lambda value, k=key: observed[k].append(value))
    worker.run()

    assert observed["failed"] == []
    assert len(observed["progress"]) == 3
    [result] = observed["finished"]
    assert len(result["imported"]) == 2
    assert len(result["errors"]) == 1
    assert result["imported"][0]["id"] == existing_id
    assert result["imported"][0]["existing"] is True
    assert result["imported"][1]["duration"] == 90
    existing_row = next(row for row in catalog.list_sources() if row["id"] == existing_id)
    assert existing_row["title"] == "Curated title"
    assert existing_row["streamer_id"] == streamer_id


def test_import_worker_cancellation_keeps_completed_imports(tmp_path, monkeypatch):
    from services.studio import media

    db_path = tmp_path / "studio.sqlite3"
    files = [tmp_path / f"{index}.mp4" for index in range(2)]
    for file in files:
        file.write_bytes(b"video")
    worker = StudioImportWorker(files, db_path)

    def cancel_during_first_probe(path, ffmpeg_path=None):
        worker.cancel()
        return {"duration": 1, "width": 2, "height": 2}

    monkeypatch.setattr(media, "probe_media", cancel_during_first_probe)
    observed = []
    worker.signals.cancelled.connect(observed.append)
    worker.run()
    [result] = observed
    assert len(result["imported"]) == 1
    assert result["completed"] == 1
    assert result["total"] == 2
