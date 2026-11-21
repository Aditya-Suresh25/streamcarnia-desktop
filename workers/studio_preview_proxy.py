"""Create a lightweight playback proxy from a real Studio pipeline render."""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class StudioPreviewProxySignals(QObject):
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()


class StudioPreviewProxyWorker(QRunnable):
    """Downscale a rendered sample for responsive editor playback."""

    _sizes = {"9:16": (540, 960), "16:9": (960, 540), "1:1": (720, 720)}

    def __init__(self, source: str | Path, destination: str | Path,
                 ffmpeg: str | Path, ratio: str):
        super().__init__()
        self.source = Path(source).expanduser().resolve()
        self.destination = Path(destination).expanduser().resolve()
        self.ffmpeg = Path(ffmpeg).expanduser().resolve()
        self.ratio = ratio if ratio in self._sizes else "9:16"
        self.signals = StudioPreviewProxySignals()
        self._cancelled = False
        self._process: subprocess.Popen | None = None

    def cancel(self) -> None:
        self._cancelled = True
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True, check=False, timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except OSError:
                pass

    @Slot()
    def run(self) -> None:
        try:
            if not self.source.is_file():
                raise ValueError("The rendered preview file is missing.")
            if not self.ffmpeg.is_file():
                raise ValueError("FFmpeg is unavailable for preview playback.")
            self.destination.parent.mkdir(parents=True, exist_ok=True)
            width, height = self._sizes[self.ratio]
            vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
                  f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
            command = [str(self.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                       "-i", str(self.source), "-vf", vf, "-c:v", "libx264",
                       "-preset", "ultrafast", "-crf", "27", "-c:a", "aac", "-b:a", "96k",
                       "-movflags", "+faststart", str(self.destination)]
            options = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                       "text": True, "encoding": "utf-8", "errors": "replace"}
            if os.name == "nt":
                options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                options["start_new_session"] = True
            self._process = subprocess.Popen(command, **options)
            try:
                _stdout, stderr = self._process.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                self.cancel()
                _stdout, stderr = self._process.communicate()
                raise RuntimeError("Creating the preview proxy timed out.")
            code = self._process.returncode
            self._process = None
            if self._cancelled:
                self.signals.cancelled.emit()
            elif code:
                raise subprocess.CalledProcessError(code, command, stderr=stderr)
            elif not self.destination.is_file() or self.destination.stat().st_size == 0:
                raise ValueError("FFmpeg did not create the playback preview.")
            else:
                self.signals.completed.emit(str(self.destination))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            if self._cancelled:
                self.signals.cancelled.emit()
            else:
                detail = getattr(exc, "stderr", None)
                self.signals.failed.emit(f"Could not prepare the rendered preview: {detail or exc}")
        finally:
            self._process = None
