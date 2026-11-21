from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CLIPPER = ROOT / "services" / "clipper"
TEMP_ROOT = ROOT / "build" / "test-temp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TEMP_ROOT)
sys.path.insert(0, str(CLIPPER))

# Pipeline unit tests replace media/network services, so lightweight import stubs
# keep the suite runnable without downloading the app's large inference stack.
ct2_stub = types.ModuleType("ctranslate2")
ct2_stub.Translator = object
sys.modules.setdefault("ctranslate2", ct2_stub)
for name in ("burn", "edit", "fetch", "highlights"):
    sys.modules.setdefault(name, types.ModuleType(name))
captions_stub = types.ModuleType("captions")
captions_stub.STYLES = {"pop": (3, "pop", True)}
captions_stub.build = lambda *_args, **_kwargs: ("", [])
captions_stub.build_srt = lambda _chunks: ""
sys.modules.setdefault("captions", captions_stub)
common_stub = types.ModuleType("common")
common_stub.fmt_time = lambda value: str(value)
common_stub.parse_time = lambda value: float(value.split(":")[-1])
common_stub.probe = lambda _path: {"duration": 10}
sys.modules.setdefault("common", common_stub)

import pipeline
import romanize


class ReliabilityTests(unittest.TestCase):
    def test_json_is_utf8_and_preserves_devanagari(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "words.json"
            pipeline.write_json(target, {"text": "नमस्ते, gamer!"})
            raw = target.read_bytes()
            self.assertIn("नमस्ते".encode("utf-8"), raw)
            self.assertEqual(json.loads(raw.decode("utf-8"))["text"], "नमस्ते, gamer!")

    def test_romanization_preserves_english_and_punctuation(self):
        with patch.object(romanize, "romanize_devanagari", return_value="namaste"):
            self.assertEqual(romanize.romanize_text("नमस्ते, gamer!"), "namaste, gamer!")
            self.assertEqual(romanize.romanize_text("hello, gamer!"), "hello, gamer!")

    def test_middle_clip_failure_keeps_later_successes(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            source.touch()
            out = Path(folder) / "out"
            edited = Path(folder) / "edited.mp4"
            edited.touch()
            candidate_list = [
                {"rank": i, "start": (i - 1) * 60, "end": i * 60,
                 "score": i, "reasons": ["test"], "label": f"test-{i}"}
                for i in range(1, 4)
            ]
            ok_edit = {"path": str(edited), "width": 1920, "height": 1080}
            edit = SimpleNamespace(edit=unittest.mock.Mock(side_effect=[ok_edit, RuntimeError("synthetic edit error"), ok_edit]))
            burn = SimpleNamespace(burn=lambda _src, _ass, dest, *_args: Path(dest).write_bytes(b"mp4"))
            transcribe_module = SimpleNamespace(transcribe=lambda *_args, **_kwargs: {"text": "Hi!", "words": [{"s": 0.0, "e": 0.5, "w": "Hi!"}]})
            argv = ["pipeline.py", str(source), "--out", str(out), "--ranges", "0:00-0:10,0:10-0:20,0:20-0:30"]
            with patch.object(sys, "argv", argv), patch.object(pipeline, "edit_mod", edit), \
                    patch.object(pipeline, "burn_mod", burn), patch.object(pipeline, "probe", return_value={"duration": 10}), \
                    patch.dict(sys.modules, {"transcribe": transcribe_module}), \
                    patch.object(pipeline.cap_mod, "build", return_value=("[Events]\n", [[{"s": 0.0, "e": 0.5, "w": "Hi!"}]])), \
                    patch.object(pipeline.cap_mod, "build_srt", return_value="1\n"):
                pipeline.main()
            entries = json.loads((out / "clips.json").read_text(encoding="utf-8"))
            report = json.loads((out / "job_summary.json").read_text(encoding="utf-8"))
            self.assertEqual([entry["rank"] for entry in entries], [1, 3])
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["failed"][0]["stage"], "edit/probe")
            self.assertEqual(edit.edit.call_count, 3)

    def test_romanization_failure_keeps_source_transcript_and_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "source.mp4"
            source.touch()
            out = Path(folder) / "out"
            edited = Path(folder) / "edited.mp4"
            edited.touch()
            edits = SimpleNamespace(edit=unittest.mock.Mock(return_value={
                "path": str(edited), "width": 1920, "height": 1080,
            }))
            burn = SimpleNamespace(burn=lambda _src, _ass, dest, *_args: Path(dest).write_bytes(b"mp4"))
            tr = {"text": "नमस्ते", "words": [{"s": 0.0, "e": 0.5, "w": "नमस्ते"}]}
            transcribe_module = SimpleNamespace(transcribe=lambda *_args, **_kwargs: tr)
            romanizer = unittest.mock.Mock(side_effect=[RuntimeError("synthetic model error"),
                [{"s": 0.0, "e": 0.5, "w": "namaste"}]])
            argv = ["pipeline.py", str(source), "--out", str(out), "--ranges", "0:00-0:10,0:10-0:20"]
            with patch.object(sys, "argv", argv), patch.object(pipeline, "edit_mod", edits), \
                    patch.object(pipeline, "burn_mod", burn), patch.object(pipeline, "probe", return_value={"duration": 10}), \
                    patch.dict(sys.modules, {"transcribe": transcribe_module}), \
                    patch.object(romanize, "caption_words", romanizer), \
                    patch.object(pipeline.cap_mod, "build", return_value=("[Events]\n", [[{"s": 0.0, "e": 0.5, "w": "namaste"}]])), \
                    patch.object(pipeline.cap_mod, "build_srt", return_value="1\n"):
                pipeline.main()
            entries = json.loads((out / "clips.json").read_text(encoding="utf-8"))
            report = json.loads((out / "job_summary.json").read_text(encoding="utf-8"))
            original = json.loads((out / "work" / "words_01.json").read_text(encoding="utf-8"))
            self.assertEqual([entry["rank"] for entry in entries], [2])
            self.assertEqual(report["failed"][0]["stage"], "romanization")
            self.assertEqual(original["words"][0]["w"], "नमस्ते")
            self.assertEqual(entries[0]["caption_transcript"], "namaste")


if __name__ == "__main__":
    unittest.main()
