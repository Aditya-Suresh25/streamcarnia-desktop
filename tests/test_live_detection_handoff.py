import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from services.live_clipper.capture import RollingSegmentBuffer, Segment
from services.live_clipper.detector import IncrementalHighlightDetector
from services.live_clipper.handoff import VodHandoff, clip_window
from services.live_clipper.orchestrator import LiveAutoClipper
from services.live_clipper.store import LiveJobStore


class LiveDetectionTests(unittest.TestCase):
    def test_audio_spike_and_cooldown_and_clip_limit(self):
        detector = IncrementalHighlightDetector(threshold=2, cooldown_seconds=120, max_clips=2)
        detector.process(np.full(120, -30.0), 0)
        first = detector.process(np.array([-5.0, -30.0]), 120)
        self.assertEqual(len(first), 1)
        self.assertGreaterEqual(first[0].score, 2)
        detector.process(np.full(120, -30.0), 122)
        second = detector.process(np.array([-5.0, -5.0]), 242)
        self.assertEqual(len(second), 1)
        detector.process(np.full(120, -30.0), 244)
        self.assertEqual(detector.process(np.array([-5.0]), 364), [])

    def test_chat_velocity_can_contribute_when_available(self):
        detector = IncrementalHighlightDetector(threshold=2, max_clips=1)
        detector.process(np.zeros(60), 0, np.zeros(60))
        found = detector.process(np.array([0.0]), 60, np.array([100.0]))
        self.assertEqual(len(found), 1)
        self.assertIsNotNone(found[0].chat_score)

    def test_window_has_twenty_seconds_before_and_trims_at_stream_end(self):
        self.assertEqual(clip_window(100, 60, 0, 500), (80, 140))
        self.assertEqual(clip_window(100, 60, 0, 125), (80, 125))
        self.assertEqual(clip_window(10, 40, 0, 50), (0, 30))

    def test_orchestrator_hands_highlight_to_adapter_and_records_rendered_state(self):
        with tempfile.TemporaryDirectory() as td:
            segment_path = Path(td) / "seg.ts"
            segment_path.write_bytes(b"x")
            segment = Segment(segment_path, 1, 0, 121)
            buffer = RollingSegmentBuffer(Path(td) / "buffer", 1800)
            buffer.add(segment)
            events = []

            class FakeHandoff:
                def __init__(self, ffmpeg, output_root):
                    self.output_root = output_root

                def render(self, segments, trigger, config, progress):
                    self.assertion = bool(segments)
                    progress({"stage": "burn"})
                    return Path(td) / "clip.mp4"

            energies = np.concatenate([np.full(120, -30.0), np.array([-5.0])])
            service = LiveAutoClipper(config={"threshold": 2, "max_clips_per_stream": 3,
                "clip_length_seconds": 20}, ffmpeg="ffmpeg", output_dir=Path(td), emit=events.append,
                energy_provider=lambda path, ffmpeg: energies, handoff_factory=FakeHandoff,
                store=LiveJobStore(Path(td) / "jobs.sqlite3"),
                metadata_factory=lambda transcript, name, key, client_factory=None: {
                    "title": "Fallback", "description": "", "hashtags": ["#Shorts"], "fallback": True})
            service.on_segment(segment, buffer)
            self.assertIn("detected", [event["type"] for event in events])
            self.assertIn("rendered", [event["type"] for event in events])


class HandoffTests(unittest.TestCase):
    def test_adapter_calls_existing_vod_pipeline_with_local_clip_range(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            segment_path = root / "segment.ts"
            segment_path.write_bytes(b"segment")
            output_root = root / "final"
            commands = []

            def fake_pipeline(command, **kwargs):
                commands.extend(command)
                out_dir = Path(command[command.index("--out") + 1])
                out_dir.mkdir(parents=True, exist_ok=True)
                final = out_dir / "clip_01.mp4"
                final.write_bytes(b"rendered")
                (out_dir / "clips.json").write_text(
                    '[{"file": "' + str(final).replace("\\", "\\\\") + '"}]', encoding="utf-8")

                class Result:
                    returncode = 0
                    stdout = ""
                return Result()

            adapter = VodHandoff("ffmpeg", output_root, pipeline_runner=fake_pipeline)
            with patch("services.live_clipper.handoff._ffmpeg_run"), \
                 patch("services.live_clipper.handoff._probe_output", return_value=(59.9, 1080, 1920)):
                final = adapter.render([Segment(segment_path, 1, 0, 300)], 100,
                                       {"clip_length_seconds": 60, "layout": "blur", "caption_style": "pop"})
            self.assertEqual(final.name, "clip_01.mp4")
            self.assertIn("--ranges", commands)
            self.assertIn("--layout", commands)
            self.assertIn("--style", commands)


if __name__ == "__main__":
    unittest.main()
