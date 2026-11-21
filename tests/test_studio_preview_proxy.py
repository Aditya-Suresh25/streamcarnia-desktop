"""Tests that rendered output is converted into a workspace-local playback proxy."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from workers.studio_preview_proxy import StudioPreviewProxyWorker


def test_preview_proxy_uses_layout_dimensions_and_writes_to_workspace():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
        root = Path(temp)
        rendered = root / "rendered.mp4"
        ffmpeg = root / "ffmpeg.exe"
        output = root / ".streamcarnia" / "preview" / "playback.mp4"
        rendered.write_bytes(b"rendered clip")
        ffmpeg.write_bytes(b"fake executable")
        completed, failed = [], []

        class Process:
            returncode = 0

            def __init__(self, args, **_kwargs):
                self.args = args
                Path(args[-1]).write_bytes(b"preview proxy")

            def communicate(self, timeout=None):
                return "", ""

        worker = StudioPreviewProxyWorker(rendered, output, ffmpeg, "1:1")
        worker.signals.completed.connect(completed.append)
        worker.signals.failed.connect(failed.append)
        with patch("workers.studio_preview_proxy.subprocess.Popen", side_effect=Process) as popen:
            worker.run()

        assert failed == []
        assert completed == [str(output.resolve())]
        assert output.is_relative_to(root / ".streamcarnia")
        command = popen.call_args.args[0]
        vf = command[command.index("-vf") + 1]
        assert "scale=720:720" in vf
        assert "pad=720:720" in vf
        assert "-preset" in command and "ultrafast" in command


def test_preview_proxy_reports_missing_rendered_source():
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp:
        root = Path(temp)
        ffmpeg = root / "ffmpeg.exe"
        ffmpeg.write_bytes(b"fake executable")
        failed = []
        worker = StudioPreviewProxyWorker(root / "missing.mp4", root / "preview.mp4", ffmpeg, "9:16")
        worker.signals.failed.connect(failed.append)
        worker.run()

        assert len(failed) == 1
        assert "rendered preview file is missing" in failed[0]
