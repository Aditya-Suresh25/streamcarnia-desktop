"""Join a buffered highlight window and pass it through the existing VOD CLI."""
from __future__ import annotations

import os
import json
import queue
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable

from core.paths import asset_path, resource_path
from .capture import Segment


def clip_window(trigger_at: float, duration: int, available_start: float,
                available_end: float) -> tuple[float, float]:
    if not 20 <= int(duration) <= 60:
        raise ValueError("Clip length must be between 20 and 60 seconds")
    start = max(float(available_start), trigger_at - 20.0)
    end = min(float(available_end), trigger_at + (duration - 20.0))
    if end <= start:
        raise ValueError("No buffered video is available for this highlight")
    return start, end


def _ffmpeg_run(ffmpeg: str, args: list[str]) -> None:
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args], check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)


def _probe_output(ffmpeg: str, path: Path) -> tuple[float, int, int]:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path), "-t", "0", "-f", "null", "-"],
                            capture_output=True, text=True, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    size_match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", result.stderr)
    if not duration_match or not size_match:
        raise RuntimeError("Could not verify the rendered live clip")
    h, m, s = duration_match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s), int(size_match.group(1)), int(size_match.group(2))


class VodHandoff:
    def __init__(self, ffmpeg: str, output_root: Path, pipeline_runner: Callable | None = None):
        self.ffmpeg = ffmpeg
        self.output_root = Path(output_root).resolve()
        self.pipeline_runner = pipeline_runner or subprocess.run

    def render(self, segments: list[Segment], trigger_at: float, config: dict,
               stream_name: str = "Live stream", progress: Callable[[dict], None] | None = None) -> Path:
        if not segments:
            raise ValueError("No live segments are available")
        ordered = sorted(segments, key=lambda segment: segment.started_at)
        available_start = ordered[0].started_at
        available_end = max(segment.started_at + segment.duration for segment in ordered)
        duration = int(config.get("clip_length_seconds", 60))
        start_at, end_at = clip_window(trigger_at, duration, available_start, available_end)
        selected = [segment for segment in ordered
                    if segment.started_at < end_at and segment.started_at + segment.duration > start_at]
        if not selected:
            raise ValueError("No video segments overlap the detected highlight")

        self.output_root.mkdir(parents=True, exist_ok=True)
        output = self.output_root / f"live_{int(trigger_at):010d}"
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="live_handoff_", dir=self.output_root) as temp:
            temp_path = Path(temp)
            concat_file = temp_path / "segments.txt"
            lines = ["file '" + str(segment.path.resolve()).replace("'", "'\\''") + "'" for segment in selected]
            concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            local_start = max(0.0, start_at - selected[0].started_at)
            local_duration = end_at - start_at
            source = temp_path / "highlight.mp4"
            _ffmpeg_run(self.ffmpeg, ["-f", "concat", "-safe", "0", "-i", str(concat_file),
                                     "-ss", f"{local_start:.3f}", "-t", f"{local_duration:.3f}",
                                     "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264",
                                     "-preset", "veryfast", "-crf", "18", "-c:a", "aac", source.as_posix()])
            if self.pipeline_runner is not None:
                self._run_existing_pipeline(source, output, local_duration, config, progress)
        clips_file = output / "clips.json"
        if not clips_file.is_file():
            raise RuntimeError("The existing VOD clip pipeline did not produce clips.json")
        import json
        clips = json.loads(clips_file.read_text(encoding="utf-8"))
        if not clips:
            raise RuntimeError("The existing VOD pipeline produced no clip")
        final = Path(clips[0]["file"])
        if not final.is_absolute():
            final = (output / final).resolve()
        actual_duration, width, height = _probe_output(self.ffmpeg, final)
        if actual_duration > 60.0 or width != 1080 or height != 1920:
            raise RuntimeError(f"Rendered live clip failed output checks ({actual_duration:.2f}s, {width}x{height})")
        return final

    def _run_existing_pipeline(self, source: Path, output: Path, duration: float, config: dict,
                               progress: Callable[[dict], None] | None = None) -> None:
        pipeline = resource_path("services", "clipper", "pipeline.py")
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-clipper", str(pipeline)]
        else:
            command = [sys.executable, str(pipeline)]
        command += [str(source), "--out", str(output), "--top", "1", "--ranges", f"0-{duration:.3f}",
                    "--layout", config.get("layout", "blur"), "--style", config.get("caption_style", "pop")]
        if config.get("language"):
            command += ["--lang", str(config["language"])]
        if config.get("facecam"):
            command += ["--facecam", str(config["facecam"])]
        if config.get("pan_zoom"):
            command.append("--peak-zoom")
        for key, option in (("channel_name", "--channel-name"), ("subscriber_text", "--subscriber-text"),
                            ("logo_path", "--logo")):
            if config.get(key):
                command += [option, str(config[key])]
        fonts = asset_path("fonts")
        command += ["--fontsdir", str(fonts)]
        env = os.environ.copy()
        env["PATH"] = str(Path(self.ffmpeg).parent) + os.pathsep + env.get("PATH", "")
        if self.pipeline_runner is not subprocess.run:
            result = self.pipeline_runner(command, cwd=str(pipeline.parent), env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                          encoding="utf-8", errors="replace", check=False,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                          if os.name == "nt" else 0)
            if result.returncode:
                raise RuntimeError(f"VOD clip pipeline failed: {result.stdout[-2000:]}")
            return
        child = subprocess.Popen(command, cwd=str(pipeline.parent), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                if os.name == "nt" else 0)
        tail = []
        lines = queue.Queue()

        def read_output():
            assert child.stdout is not None
            for line in child.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_output, name="VodPipelineProgress", daemon=True)
        reader.start()
        current_stage = "source"
        closed = False
        try:
            while not closed:
                try:
                    line = lines.get(timeout=1.0)
                except queue.Empty:
                    if progress:
                        progress({"stage": current_stage, "heartbeat": True})
                    continue
                if line is None:
                    closed = True
                    continue
                tail.append(line.rstrip())
                tail = tail[-60:]
                prefix = "@@SC_PROGRESS@@"
                message = line.strip()
                if message.startswith(prefix):
                    try:
                        event = json.loads(message[len(prefix):])
                        current_stage = event.get("stage", current_stage)
                        if progress:
                            progress(event)
                    except (TypeError, ValueError):
                        pass
            code = child.wait()
        except BaseException:
            child.terminate()
            child.wait(timeout=5)
            raise
        if code:
            raise RuntimeError("VOD clip pipeline failed: " + "\n".join(tail[-15:]))
