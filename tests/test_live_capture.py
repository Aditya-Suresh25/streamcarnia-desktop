import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.live_clipper.capture import LiveSegmentRecorder, RollingSegmentBuffer, Segment


class LiveCaptureTests(unittest.TestCase):
    def test_buffer_prunes_oldest_unpinned_segments_but_keeps_pinned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            buffer = RollingSegmentBuffer(root, retention_seconds=600)
            items = []
            for number in range(1, 3):
                path = root / f"{number}.ts"
                path.write_bytes(b"segment")
                item = Segment(path, number, float(number * 300))
                items.append(item)
                buffer.add(item)
            buffer.pin("pending-clip", [1])
            path = root / "3.ts"
            path.write_bytes(b"segment")
            items.append(Segment(path, 3, 900.0))
            buffer.add(items[-1])
            self.assertTrue(items[0].path.exists())
            self.assertTrue(items[1].path.exists())
            buffer.unpin("pending-clip")
            self.assertFalse(items[0].path.exists())
            self.assertEqual([item.sequence for item in buffer.segments], [2, 3])

    def test_recorder_emits_closed_segments_and_recovers_after_disconnect(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            events = []
            resolutions = iter([("media-1", True), ("media-2", True), ("", False)])
            stop = {"value": False}

            class FinishedProcess:
                def poll(self):
                    return 0

            def popen(command, **kwargs):
                pattern = command[-1]
                Path(pattern.replace("%06d", "000000")).write_bytes(b"one")
                Path(pattern.replace("%06d", "000001")).write_bytes(b"two")
                return FinishedProcess()

            recorder = LiveSegmentRecorder(
                "https://example.test/live", root, "ffmpeg.exe", events.append,
                lambda: stop["value"], resolver=lambda _url: next(resolutions), popen=popen,
                sleep=lambda _delay: None,
            )
            with patch.object(recorder, "_probe_duration", return_value=300.0):
                recorder.run()
            segments = [event for event in events if event["type"] == "segment_ready"]
            self.assertEqual(len(segments), 4)
            self.assertEqual([event["sequence"] for event in segments], [1, 2, 3, 4])
            self.assertIn("reconnected", [event["type"] for event in events])
            self.assertIn("stream_ended", [event["type"] for event in events])

    def test_stop_during_retry_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            events = []
            stopped = {"value": False}

            def mark_stop(_delay):
                stopped["value"] = True

            recorder = LiveSegmentRecorder(
                "url", Path(td), "ffmpeg", events.append, lambda: stopped["value"],
                resolver=lambda _url: (_ for _ in ()).throw(RuntimeError("offline")),
                sleep=mark_stop,
            )
            recorder.run()
            self.assertIn("capture_stopped", [event["type"] for event in events])


if __name__ == "__main__":
    unittest.main()
