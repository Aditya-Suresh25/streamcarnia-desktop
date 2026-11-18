import json
import tempfile
import time
import unittest
from pathlib import Path

from services.live_clipper.config import LiveClipperConfig, LiveClipperSettings
from services.live_clipper.process import LiveProcessController
from services.live_clipper.store import LiveJobStore


class LiveFoundationTests(unittest.TestCase):
    def test_live_settings_are_disabled_by_default_and_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "live.json"
            store = LiveClipperSettings(path)
            self.assertFalse(store.get().enabled)
            saved = store.update(enabled=True, clip_length_seconds=45)
            self.assertTrue(saved.enabled)
            self.assertEqual(store.get().clip_length_seconds, 45)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(raw["live_clipper.enabled"])

    def test_config_limits_clip_length_to_20_through_60_seconds(self):
        for duration in (19, 61):
            with self.assertRaises(ValueError):
                LiveClipperConfig(clip_length_seconds=duration).validated()

    def test_live_job_state_is_separate_and_persists_unicode(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "live.sqlite3"
            store = LiveJobStore(db_path)
            job_id = store.create("https://example.test/live", {"title": "हिन्दी"})
            store.update(job_id, "rendered", {"file": "clip.mp4"})
            job = store.list_jobs()[0]
            self.assertEqual(job["state"], "rendered")
            self.assertEqual(job["data"]["title"], "हिन्दी")
            import sqlite3
            db = sqlite3.connect(db_path)
            try:
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),
                                 [("live_jobs",)])
            finally:
                db.close()

    def test_supervised_live_worker_starts_and_stops_outside_ui_process(self):
        with tempfile.TemporaryDirectory() as td:
            supervisor = LiveProcessController(Path(td))
            supervisor.start({"stream_url": "https://example.test/live"})
            deadline = time.monotonic() + 8
            events = []
            while time.monotonic() < deadline and not any(e["type"] == "started" for e in events):
                events.extend(supervisor.poll())
                time.sleep(0.05)
            self.assertTrue(any(e["type"] == "started" for e in events))
            supervisor.stop()
            self.assertFalse(supervisor.running)


if __name__ == "__main__":
    unittest.main()
