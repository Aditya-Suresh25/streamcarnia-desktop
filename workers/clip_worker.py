"""Runs the isolated livestream clipping pipeline outside the Qt UI thread."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import QRunnable, Slot

from core.paths import asset_path, resource_path
from workers.signals import ClipSignals


class ClipWorker(QRunnable):
    def __init__(self, options: dict, output_dir: Path, ffmpeg_path: str | None):
        super().__init__()
        self.options = options
        self.output_dir = output_dir
        self.ffmpeg_path = ffmpeg_path
        self.cancel_event = Event()
        self.signals = ClipSignals()
        self._process: subprocess.Popen | None = None
        self._progress_started_at: float | None = None
        self._progress_total = 0

    def cancel(self) -> None:
        self.cancel_event.set()
        if self._process and self._process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                               capture_output=True, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            else:
                self._process.terminate()

    @Slot()
    def run(self) -> None:
        try:
            import numpy  # noqa: F401
            import faster_whisper  # noqa: F401
        except ImportError as exc:
            fix = ("Install the current StreamCarnia build with Auto Clippr support."
                   if getattr(sys, "frozen", False)
                   else "Install desktop dependencies with `pip install -r requirements.txt`, then restart StreamCarnia.")
            self.signals.failed.emit(
                f"Auto Clippr needs its processing packages. {fix} Missing: {exc.name}."
            )
            return

        if not self.ffmpeg_path or not Path(self.ffmpeg_path).is_file():
            self.signals.failed.emit("FFmpeg is unavailable. Install or restore the bundled FFmpeg, then retry.")
            return
        try:
            filters = subprocess.run(
                [self.ffmpeg_path, "-hide_banner", "-filters"], capture_output=True,
                text=True, timeout=20, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            required = ["ass"]
            if self.options.get("channel_name") or self.options.get("subscriber_text"):
                required.append("drawtext")
            if self.options.get("logo_path"):
                required.append("overlay")
            missing = [name for name in required if f" {name} " not in filters.stdout]
            if missing:
                detail = "libass" if "ass" in missing else ", ".join(missing)
                self.signals.failed.emit(f"This FFmpeg build is missing required filter support: {detail}.")
                return
        except (OSError, subprocess.SubprocessError) as exc:
            self.signals.failed.emit(f"Could not check FFmpeg caption support: {exc}")
            return

        scripts = resource_path("services", "clipper")
        pipeline = scripts / "pipeline.py"
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-clipper", str(pipeline)]
        else:
            command = [sys.executable, str(pipeline)]
        args = [*command, self.options["url"], "--out", str(self.output_dir),
                "--top", str(self.options["count"]), "--layout", self.options["layout"],
                "--style", self.options["style"], "--archived-only"]
        if self.options.get("language"):
            args += ["--lang", self.options["language"]]
        if self.options.get("facecam"):
            args += ["--facecam", self.options["facecam"]]
        if self.options.get("pan_zoom"):
            args += ["--peak-zoom"]
        if self.options.get("channel_name"):
            args += ["--channel-name", self.options["channel_name"]]
        if self.options.get("subscriber_text"):
            args += ["--subscriber-text", self.options["subscriber_text"]]
        if self.options.get("logo_path"):
            args += ["--logo", self.options["logo_path"]]
        fonts_dir = asset_path("fonts")
        args += ["--fontsdir", str(fonts_dir)]
        if self.options.get("cookies"):
            args += ["--cookies", self.options["cookies"]]

        env = os.environ.copy()
        ffmpeg_dir = str(Path(self.ffmpeg_path).parent)
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (self.output_dir / "job.log").open("w", encoding="utf-8") as log_file:
                self._process = subprocess.Popen(
                    args, cwd=scripts, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                )
                assert self._process.stdout is not None
                for line in self._process.stdout:
                    log_file.write(line)
                    log_file.flush()
                    if self.cancel_event.is_set():
                        break
                    message = line.strip()
                    if message:
                        prefix = "@@SC_PROGRESS@@"
                        if message.startswith(prefix):
                            try:
                                self.signals.progress.emit(self._format_progress(json.loads(message[len(prefix):])))
                            except (ValueError, TypeError):
                                pass
                code = self._process.wait()
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                clips_file = self.output_dir / "clips.json"
                summary_file = self.output_dir / "job_summary.json"
                if clips_file.is_file() and summary_file.is_file():
                    entries = json.loads(clips_file.read_text(encoding="utf-8"))
                    summary = json.loads(summary_file.read_text(encoding="utf-8"))
                    payload = {"clips": entries, "summary": summary}
                    if code:
                        payload["fatal_error"] = (summary.get("fatal_error") or
                            f"Clip job stopped with exit code {code}. See job log: {self.output_dir}.")
                    self.signals.finished.emit(payload)
                elif code:
                    detail = ""
                    try:
                        lines = (self.output_dir / "job.log").read_text(encoding="utf-8", errors="replace").splitlines()
                        useful = next((line.strip() for line in reversed(lines) if "Error" in line or "Exception" in line), "")
                        detail = f" {useful}" if useful else ""
                    except OSError:
                        pass
                    self.signals.failed.emit(f"Clip generation failed (exit code {code}).{detail} See job log: {self.output_dir}.")
                elif not clips_file.is_file():
                    self.signals.failed.emit("The clip pipeline finished without creating clips.json.")
                else:
                    self.signals.failed.emit("The clip pipeline finished without creating a job summary.")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.signals.failed.emit(f"Could not complete the clip job: {exc}")
        finally:
            self._process = None

    def _format_progress(self, event: dict) -> dict:
        stage = event.get("stage", "working")
        clip = int(event.get("clip", 0) or 0)
        total = int(event.get("total", 0) or 0)
        if stage == "ready":
            self._progress_started_at = time.monotonic()
            self._progress_total = total
            percent = 8
        elif stage == "source":
            percent = 2
        else:
            total = total or self._progress_total
            fractions = {"fetch": 0.12, "edit": 0.38, "transcribe": 0.63, "romanize": 0.72,
                         "burn": 0.90, "done": 1.0, "clip_failed": 1.0}
            fraction = fractions.get(stage, 0.0)
            percent = 8 + (92 * min(1.0, ((max(clip, 1) - 1 + fraction) / total))) if total else 100
        percent = max(0, min(100, int(percent)))
        eta = None
        if self._progress_started_at is not None and percent > 8:
            elapsed = time.monotonic() - self._progress_started_at
            eta = max(0, int(elapsed * (100 - percent) / max(percent - 8, 1)))
        labels = {"source": "Checking stream", "ready": "Highlights found", "fetch": "Downloading clip",
                  "edit": "Editing video", "transcribe": "Creating captions", "romanize": "Making Hinglish captions",
                  "burn": "Rendering captions", "clip_failed": "Clip failed; continuing",
                  "done": "Clip complete"}
        return {"stage": stage, "clip": clip, "total": total, "percent": percent, "eta_seconds": eta, "message": labels.get(stage, "Working")}
