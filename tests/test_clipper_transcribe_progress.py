from __future__ import annotations

import sys
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "clipper"))

if "common" in sys.modules and not hasattr(sys.modules["common"], "no_console_kwargs"):
    sys.modules["common"].no_console_kwargs = lambda: {}
    sys.modules["common"].run = lambda *_args, **_kwargs: None

import transcribe
edit_spec = importlib.util.spec_from_file_location("clipper_edit_under_test", ROOT / "services" / "clipper" / "edit.py")
edit_module = importlib.util.module_from_spec(edit_spec)
edit_spec.loader.exec_module(edit_module)
layout_filter = edit_module.layout_filter


class TranscriptionProgressTests(unittest.TestCase):
    def tearDown(self):
        transcribe._load_model.cache_clear()

    def test_reuses_model_between_clips_and_reports_inference_progress(self):
        class Segment:
            start = 0.0
            end = 5.0
            words = [types.SimpleNamespace(word=" bhai", start=0.0, end=0.5)]

        class FakeModel:
            def transcribe(self, *_args, **_kwargs):
                return iter([Segment()]), types.SimpleNamespace(language="hi", duration=5.0)

        created = []
        faster = types.ModuleType("faster_whisper")
        faster.WhisperModel = lambda *args, **kwargs: (created.append((args, kwargs)) or FakeModel())
        with patch.dict(sys.modules, {"faster_whisper": faster}):
            first_events, second_events = [], []
            first = transcribe.transcribe("clip1.mp4", "medium", on_progress=first_events.append)
            second = transcribe.transcribe("clip2.mp4", "medium", on_progress=second_events.append)
        self.assertEqual(len(created), 1)
        self.assertEqual(first["words"][0]["w"], "bhai")
        self.assertEqual(second["words"][0]["w"], "bhai")
        self.assertEqual(first_events[-1], 1.0)
        self.assertGreater(len(first_events), 2)

    def test_stacked_layout_allocates_less_height_to_facecam(self):
        graph, size = layout_filter("stack", facecam=(0.7, 0.7, 0.3, 0.3),
                                    stack_facecam_percent=35)
        self.assertIn("scale=1080:672", graph)
        self.assertIn("scale=1080:1248", graph)
        self.assertEqual(size, (1080, 1920))


if __name__ == "__main__":
    unittest.main()
