"""Extract real timeline frame thumbnails off the UI thread."""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class StudioTimelineThumbnailSignals(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class StudioTimelineThumbnailWorker(QRunnable):
    """Create cached representative frames under the selected Studio workspace."""

    def __init__(self, source_path: str | Path, duration: float, output_root: str | Path,
                 ffmpeg_path: str | Path, count: int = 10):
        super().__init__()
        self.source_path = Path(source_path).expanduser().resolve()
        self.duration = max(0.0, float(duration))
        self.output_root = Path(output_root).expanduser().resolve()
        self.ffmpeg_path = Path(ffmpeg_path).expanduser().resolve()
        self.count = max(2, min(16, int(count)))
        self._cancelled = False
        self._process: subprocess.Popen | None = None
        self.signals = StudioTimelineThumbnailSignals()

    def cancel(self) -> None:
        self._cancelled = True
        process = self._process
        if not process or process.poll() is not None:
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
            if not self.source_path.is_file():
                raise ValueError("The selected source is missing.")
            if not self.ffmpeg_path.is_file():
                raise ValueError("FFmpeg is unavailable for timeline thumbnails.")
            stat = self.source_path.stat()
            cache_key = hashlib.sha1(
                f"{self.source_path}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
            ).hexdigest()[:16]
            cache_dir = self.output_root / cache_key
            cache_dir.mkdir(parents=True, exist_ok=True)
            frames = []
            for index in range(self.count):
                if self._cancelled:
                    self.signals.cancelled.emit()
                    return
                at_seconds = min(max(0.0, self.duration - 0.05),
                                 (index + 0.5) * self.duration / self.count)
                output = cache_dir / f"frame_{index:02d}.jpg"
                if not output.is_file() or output.stat().st_size == 0:
                    command = [str(self.ffmpeg_path), "-hide_banner", "-loglevel", "error", "-y",
                               "-ss", f"{at_seconds:.3f}", "-i", str(self.source_path),
                               "-frames:v", "1", "-vf", "scale='min(360,iw)':-2", "-q:v", "6", str(output)]
                    options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0}
                    if os.name != "nt":
                        options["start_new_session"] = True
                    self._process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, encoding="utf-8", errors="replace", **options)
                    try:
                        _stdout, stderr = self._process.communicate(timeout=45)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                        _stdout, stderr = self._process.communicate()
                        raise
                    code = self._process.returncode
                    self._process = None
                    if self._cancelled:
                        self.signals.cancelled.emit()
                        return
                    if code:
                        raise subprocess.CalledProcessError(code, command, stderr=stderr)
                if output.is_file() and output.stat().st_size:
                    frames.append({"time": at_seconds, "path": str(output)})
                self.signals.progress.emit({"completed": index + 1, "total": self.count})
            self.signals.finished.emit(frames)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if self._cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.failed.emit(f"Could not create timeline thumbnails: {exc}")
        finally:
            self._process = None
