"""Tests for real, workspace-local timeline frame caching."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from workers.studio_timeline_thumbnails import StudioTimelineThumbnailWorker


def test_thumbnail_worker_extracts_frames_to_cache_under_workspace():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
        tmp_path = Path(temp)
        source = tmp_path / "source.mp4"
        ffmpeg = tmp_path / "ffmpeg.exe"
        source.write_bytes(b"media")
        ffmpeg.write_bytes(b"fake executable")
        output_root = tmp_path / ".streamcarnia" / "timeline_frames"
        completed, progress, failed = [], [], []

        class Process:
            returncode = 0

            def __init__(self, args, **_kwargs):
                self.args = args
                self.output = Path(args[-1])

            def communicate(self, timeout=None):
                self.output.write_bytes(b"jpeg frame")
                return "", ""

        worker = StudioTimelineThumbnailWorker(source, 12.0, output_root, ffmpeg, count=4)
        worker.signals.finished.connect(completed.append)
        worker.signals.progress.connect(progress.append)
        worker.signals.failed.connect(failed.append)
        with patch("workers.studio_timeline_thumbnails.subprocess.Popen", side_effect=Process) as popen:
            worker.run()

        assert failed == []
        assert len(completed) == 1
        frames = completed[0]
        assert len(frames) == 4
        assert all(Path(frame["path"]).is_relative_to(output_root) for frame in frames)
        assert all(Path(frame["path"]).is_file() for frame in frames)
        assert len(progress) == 4
        assert all("-ss" in popen.call_args_list[index].args[0] for index in range(4))
