import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from services.live_clipper.chat import LiveChatVelocity
from services.live_clipper.metadata import MODEL, fallback_title, generate_metadata
from services.live_clipper.scheduler import UploadScheduler, schedule_time
from services.live_clipper.secrets import CredentialVault
from services.live_clipper.store import LiveJobStore
from services.live_clipper.youtube import YouTubeUploader


class FakeKeyring:
    class errors:
        class PasswordDeleteError(Exception):
            pass

    class Backend:
        priority = 1

    def __init__(self):
        self.values = {}

    def get_keyring(self):
        return self.Backend()

    def set_password(self, service, key, value):
        self.values[(service, key)] = value

    def get_password(self, service, key):
        return self.values.get((service, key))

    def delete_password(self, service, key):
        if (service, key) not in self.values:
            raise self.errors.PasswordDeleteError()
        del self.values[(service, key)]


class MetadataTests(unittest.TestCase):
    def test_metadata_requires_strict_json_and_adds_shorts(self):
        response = Mock(text=json.dumps({"title": "Clutch moment", "description": "A clear clutch.",
                                        "hashtags": ["#Valorant"]}))
        client = Mock()
        client.models.generate_content.return_value = response
        metadata = generate_metadata("Player wins the round", "Stream", "secret",
                                     client_factory=lambda **kwargs: client)
        self.assertEqual(metadata["title"], "Clutch moment")
        self.assertIn("#Shorts", metadata["hashtags"])
        self.assertEqual(client.models.generate_content.call_args.kwargs["model"], MODEL)

    def test_metadata_api_failure_falls_back_to_stream_and_timestamp(self):
        metadata = generate_metadata("transcript", "My stream", "secret",
                                     datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc),
                                     client_factory=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("quota")))
        self.assertTrue(metadata["fallback"])
        self.assertEqual(metadata["title"], "My stream 2026-11-18 10:00")
        self.assertLess(len(fallback_title("x" * 100)), 60)

    def test_keyring_adapter_stores_without_plaintext_config_fallback(self):
        ring = FakeKeyring()
        vault = CredentialVault(ring)
        vault.set("gemini.api_key", "secret")
        self.assertEqual(vault.get("gemini.api_key"), "secret")

        class Insecure(FakeKeyring):
            class Backend:
                priority = 0
        with self.assertRaises(RuntimeError):
            CredentialVault(Insecure())


class FakeUploadRequest:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        return None, self.result


class FakeYoutubeService:
    def __init__(self, request):
        self.request = request
        self.insert_kwargs = None

    def videos(self):
        return self

    def insert(self, **kwargs):
        self.insert_kwargs = kwargs
        return self.request


class SchedulerTests(unittest.TestCase):
    def test_slots_are_evenly_spaced_and_stay_within_day_window(self):
        now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
        slots = [schedule_time(now, "09:00", "21:00", ordinal) for ordinal in range(1, 7)]
        self.assertEqual(slots[0].hour, 10)
        self.assertEqual(slots[-1].hour, 19)
        self.assertTrue(all(a < b for a, b in zip(slots, slots[1:])))

    def test_approval_schedules_then_uploads_private_with_publish_at_and_cap(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            store = LiveJobStore(Path(td) / "live.sqlite3")
            job_id = store.create("stream", {"file_path": "clip.mp4", "metadata": {
                "title": "Title", "description": "Description", "hashtags": ["#Shorts"]}})
            request = FakeUploadRequest({"id": "youtube-id"})
            youtube = FakeYoutubeService(request)
            uploader = YouTubeUploader(youtube, media_upload_factory=lambda *a, **k: "media")
            now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
            scheduler = UploadScheduler(store, uploader, now_provider=lambda: now)
            when = scheduler.approve_and_schedule(job_id, "09:00", "21:00")
            self.assertEqual(store.list_jobs()[0]["state"], "scheduled")
            after_due = when - __import__("datetime").timedelta(minutes=15)
            scheduler.now_provider = lambda: after_due
            self.assertEqual(scheduler.upload_due(job_id), "youtube-id")
            self.assertEqual(store.list_jobs()[0]["state"], "uploaded")
            body = youtube.insert_kwargs["body"]
            self.assertEqual(body["status"]["privacyStatus"], "private")
            self.assertEqual(body["status"]["publishAt"], when.isoformat())
            self.assertIn("#Shorts", body["snippet"]["description"])

    def test_seventh_clip_is_scheduled_on_the_next_day(self):
        import tempfile
        from pathlib import Path
        from datetime import timedelta
        with tempfile.TemporaryDirectory() as td:
            store = LiveJobStore(Path(td) / "live.sqlite3")
            now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
            scheduler = UploadScheduler(store, None, now_provider=lambda: now)
            scheduled = []
            for index in range(7):
                job_id = store.create("stream", {"index": index})
                scheduled.append(scheduler.approve_and_schedule(job_id, "09:00", "21:00"))
            self.assertEqual(len({slot.date() for slot in scheduled[:6]}), 1)
            self.assertEqual(scheduled[6].date(), now.date() + timedelta(days=1))

    def test_chat_velocity_counts_messages_in_segment_time_window(self):
        request = Mock()
        request.execute.return_value = {"nextPageToken": "next", "pollingIntervalMillis": 5000,
            "items": [{"snippet": {"publishedAt": "2026-11-18T10:00:01Z"}},
                      {"snippet": {"publishedAt": "2026-11-18T10:00:03Z"}}]}
        service = Mock()
        service.liveChatMessages.return_value.list.return_value = request
        chat = LiveChatVelocity(service, "chat-id")
        chat.poll()
        start = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(chat.counts_for(start, 5).tolist(), [0, 1, 0, 1, 0])


if __name__ == "__main__":
    unittest.main()
