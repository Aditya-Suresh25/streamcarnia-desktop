"""Focused tests for the Studio adapter to the existing detect-only pipeline."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from services.studio.discovery import (
    StudioDiscoveryCancelled,
    StudioDiscoveryError,
    _stop_process,
    run_discovery,
)
from workers.studio_discovery import StudioDiscoveryWorker


class _Process:
    def __init__(self, lines=(), code=0):
        self.stdout = iter(lines)
        self.code = code

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        return self.code

    def terminate(self):
        self.code = -15

    def kill(self):
        self.code = -9


class StudioDiscoveryTests(unittest.TestCase):
    def setUp(self):
        # Keep fixtures under the workspace because the managed runtime blocks
        # writes to its redirected Windows TEMP location.
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.root = Path(self.temp.name)
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"media")
        self.pipeline_dir = self.root / "services" / "clipper"
        self.pipeline_dir.mkdir(parents=True)
        (self.pipeline_dir / "pipeline.py").write_text("# fixture", encoding="utf-8")
        self.output = self.root / "discovery"

    def tearDown(self):
        self.temp.cleanup()

    def _pipeline_patch(self):
        return patch("services.studio.discovery.resource_path", return_value=self.pipeline_dir)

    def test_reads_backend_candidates_without_modification(self):
        candidates = [{"rank": 2, "score": 0.87, "reasons": ["audio_spike"],
                       "start": 12.3, "end": 47.1, "label": "real candidate"}]
        self.output.mkdir()
        process = _Process(["@@SC_PROGRESS@@{\"stage\":\"source\"}\n",
                            "[clipper] detecting highlights ...\n"])
        progress = []
        def start_pipeline(*args, **kwargs):
            (self.output / "candidates.json").write_text(json.dumps(candidates), encoding="utf-8")
            return process
        with self._pipeline_patch(), patch("services.studio.discovery.subprocess.Popen", side_effect=start_pipeline) as popen:
            result = run_discovery(self.source, self.output, top=4, on_progress=progress.append)
        self.assertEqual(result, candidates)
        args, kwargs = popen.call_args
        self.assertIn("--detect-only", args[0])
        self.assertIn("--archived-only", args[0])
        self.assertEqual(kwargs["encoding"], "utf-8")
        self.assertTrue(any(item["stage"] == "detecting" for item in progress))
        self.assertEqual(progress[-1]["percent"], 100)

    def test_nonzero_pipeline_exit_is_reported(self):
        process = _Process(["RuntimeError: detection failed\n"], code=2)
        with self._pipeline_patch(), patch("services.studio.discovery.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(StudioDiscoveryError, "exit code 2"):
                run_discovery(self.source, self.output)

    def test_missing_candidates_is_reported(self):
        process = _Process()
        with self._pipeline_patch(), patch("services.studio.discovery.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(StudioDiscoveryError, "without candidates.json"):
                run_discovery(self.source, self.output)

    def test_stale_candidates_are_not_returned_after_empty_run(self):
        self.output.mkdir()
        stale = self.output / "candidates.json"
        stale.write_text('[{"rank": 99}]', encoding="utf-8")
        process = _Process()
        with self._pipeline_patch(), patch("services.studio.discovery.subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(StudioDiscoveryError, "without candidates.json"):
                run_discovery(self.source, self.output)
        self.assertFalse(stale.exists())

    def test_posix_cleanup_terminates_process_group(self):
        process = _Process(code=None)
        process.pid = 1234
        with patch("services.studio.discovery.os.name", "posix"), \
             patch("services.studio.discovery.os.killpg", create=True) as killpg:
            _stop_process(process)
        killpg.assert_called_once()

    def test_pre_cancel_does_not_start_subprocess(self):
        cancelled = Event()
        cancelled.set()
        with self._pipeline_patch(), patch("services.studio.discovery.subprocess.Popen") as popen:
            with self.assertRaises(StudioDiscoveryCancelled):
                run_discovery(self.source, self.output, cancelled=cancelled)
        popen.assert_not_called()

    def test_worker_emits_completion_signal_with_backend_candidates(self):
        expected = [{"rank": 1, "score": 0.5, "reasons": ["audio"]}]
        worker = StudioDiscoveryWorker(self.source, self.output)
        completed, failed = [], []
        worker.signals.completed.connect(completed.append)
        worker.signals.failed.connect(failed.append)
        with patch("workers.studio_discovery.run_discovery", return_value=expected):
            worker.run()
        self.assertEqual(completed, [expected])
        self.assertEqual(failed, [])


if __name__ == "__main__":
    unittest.main()
