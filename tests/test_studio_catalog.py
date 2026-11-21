from datetime import date, datetime, time, timezone

from services.studio.catalog import StudioCatalog
from services.studio.publishing import StudioPublishStoreAdapter, collection_schedule
from services.live_clipper.metadata import generate_metadata_variations


def test_catalog_keeps_local_sources_and_metadata_separate(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"source")
    rendered = tmp_path / "clip.mp4"
    rendered.write_bytes(b"clip")
    catalog = StudioCatalog(tmp_path / ".streamcarnia" / "studio_library.sqlite3")

    streamer_id = catalog.add_streamer("Streamer", categories=["Gaming"], tags=["valorant"])
    source_id = catalog.add_source(media, streamer_id=streamer_id, duration=120, width=1920, height=1080)
    [clip_id] = catalog.add_clips(source_id, str(media), streamer_id, [{
        "file": str(rendered), "source_start": 10, "source_end": 25, "duration": 15,
        "transcript": "देवनागरी original", "caption_transcript": "Hinglish original",
    }], "1:1")

    clip = catalog.get_clip(clip_id)
    assert clip["transcript"] == "Hinglish original"
    assert clip["metadata"]["transcript"] == "देवनागरी original"
    assert clip["source_path"] == str(media.resolve())
    assert clip["aspect_ratio"] == "1:1"
    catalog.update_clip(clip_id, title="Edited title", description="Description", tags=["short"])
    assert catalog.get_clip(clip_id)["title"] == "Edited title"
    assert catalog.get_clip(clip_id)["tags"] == ["short"]


def test_collection_schedule_distributes_clips_in_window_and_respects_weekdays():
    now = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    slots = collection_schedule(date(2026, 1, 6), time(9), {1, 3, 5}, 2, 3,
        now=now, window_end=time(15))

    assert [slot.date() for slot in slots] == [date(2026, 1, 6), date(2026, 1, 8), date(2026, 1, 10)]
    assert [slot.time() for slot in slots] == [time(10, 30), time(12), time(13, 30)]


def test_collection_schedule_moves_past_a_saturated_hour():
    now = datetime(2026, 1, 5, 8, tzinfo=timezone.utc)
    existing = [{"status": "scheduled", "scheduled_at": f"2026-01-06T09:30:{second:02d}+00:00"}
                for second in range(6)]
    [slot] = collection_schedule(date(2026, 1, 6), time(9), {1}, 1, 1, existing,
                                 now=now, window_end=time(10))
    assert slot.date() == date(2026, 1, 13)
    assert slot.hour == 9


def test_metadata_assistant_validates_variants_and_adds_shorts():
    import json
    from unittest.mock import Mock

    variants = [{"title": f"Clip option {index}", "description": "Bhai, nice gameplay.",
                 "tags": ["Valorant"], "hashtags": [], "category": "Gaming", "language": "hi-Latn"}
                for index in range(1, 4)]
    client = Mock()
    client.models.generate_content.return_value = Mock(text=json.dumps(variants))
    result = generate_metadata_variations("Bhai, nice gameplay.", "Stream", "key",
        client_factory=lambda **kwargs: client)

    assert len(result) == 3
    assert all("#Shorts" in item["hashtags"] for item in result)
    assert all(item["language"] == "hi-Latn" for item in result)


def test_publish_adapter_exposes_studio_jobs_to_existing_scheduler(tmp_path):
    rendered = tmp_path / "clip.mp4"
    rendered.write_bytes(b"clip")
    catalog = StudioCatalog(tmp_path / "studio.sqlite3")
    [clip_id] = catalog.add_clips(None, str(rendered), None,
        [{"file": str(rendered), "source_start": 0, "source_end": 1, "duration": 1}], "9:16")
    job_id = catalog.create_publish_job(clip_id, "2026-01-06T12:00:00+00:00", {"title": "A title"}, "scheduled")

    adapter = StudioPublishStoreAdapter(catalog)
    [job] = adapter.list_jobs()
    assert job["id"] == job_id
    assert job["state"] == "scheduled"
    assert job["data"]["approved"] is True
    adapter.update(job_id, "uploading", error=None)
    assert catalog.list_publish_jobs()[0]["status"] == "uploading"
    assert catalog.get_clip(clip_id)["publish_status"] == "uploading"

