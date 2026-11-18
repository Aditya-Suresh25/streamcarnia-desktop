"""Reconnectable five-minute live capture and rolling segment buffer."""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Segment:
    path: Path
    sequence: int
    started_at: float
    duration: float = 300.0


class RollingSegmentBuffer:
    """Keep the newest segments and never prune segments pinned by a clip."""

    def __init__(self, root: Path, retention_seconds: int = 1800):
        if retention_seconds < 300:
            raise ValueError("Retention must be at least one segment")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention_seconds = int(retention_seconds)
        self._segments: list[Segment] = []
        self._pins: dict[str, set[int]] = {}

    @property
    def segments(self) -> tuple[Segment, ...]:
        return tuple(self._segments)

    def add(self, segment: Segment) -> list[Path]:
        if any(old.sequence == segment.sequence for old in self._segments):
            return []
        self._segments.append(segment)
        self._segments.sort(key=lambda item: item.sequence)
        return self.prune()

    def pin(self, key: str, sequences: list[int]) -> None:
        self._pins[key] = set(sequences)

    def unpin(self, key: str) -> list[Path]:
        self._pins.pop(key, None)
        return self.prune()

    def get(self, sequence: int) -> Segment | None:
        return next((item for item in self._segments if item.sequence == sequence), None)

    def prune(self) -> list[Path]:
        removed = []
        max_segments = max(1, self.retention_seconds // 300)
        pinned = set().union(*self._pins.values()) if self._pins else set()
        retained = {item.sequence for item in self._segments[-max_segments:]} | pinned
        for victim in list(self._segments):
            if victim.sequence in retained:
                continue
            self._segments.remove(victim)
            try:
                victim.path.unlink(missing_ok=True)
            finally:
                removed.append(victim.path)
        return removed


def resolve_live_media(url: str) -> tuple[str, bool]:
    """Return a direct media URL and whether the source still reports live."""
    import yt_dlp

    options = {"quiet": True, "no_warnings": True, "noplaylist": True,
               "format": "best[protocol^=http]/best"}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Stream metadata could not be read")
    if info.get("is_live") is False and info.get("live_status") not in ("is_live", "is_upcoming"):
        return "", False
    direct = info.get("url")
    if not direct and info.get("requested_formats"):
        raise RuntimeError("This live source requires a merged audio/video format")
    if not direct:
        raise RuntimeError("No direct live media URL was provided by yt-dlp")
    return str(direct), True


class LiveSegmentRecorder:
    """Capture source via FFmpeg; re-resolve after errors and emit completed segments."""

    def __init__(self, url: str, output_dir: Path, ffmpeg: str, emit: Callable[[dict], None],
                 stop_requested: Callable[[], bool], resolver=resolve_live_media,
                 popen=subprocess.Popen, segment_seconds: int = 300,
                 retention_seconds: int = 1800, reconnect_delay: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep, on_segment: Callable | None = None):
        self.url = url
        self.root = Path(output_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = ffmpeg
        self.emit = emit
        self.stop_requested = stop_requested
        self.resolver = resolver
        self.popen = popen
        self.segment_seconds = int(segment_seconds)
        self.reconnect_delay = reconnect_delay
        self.sleep = sleep
        self.on_segment = on_segment
        self.buffer = RollingSegmentBuffer(self.root, retention_seconds)
        self._known: set[Path] = set()
        self._sequence = 0
        self._timeline_seconds = 0.0

    def run(self) -> None:
        while not self.stop_requested():
            try:
                media_url, is_live = self.resolver(self.url)
                if not is_live:
                    self._emit_completed()
                    self.emit({"type": "stream_ended"})
                    return
                self.emit({"type": "connected" if not self._known else "reconnected"})
                self._record_connection(media_url)
            except Exception as exc:
                self.emit({"type": "capture_error", "message": str(exc)})
            if not self.stop_requested():
                self._emit_completed(final=True)
                self.emit({"type": "reconnecting"})
                self.sleep(self.reconnect_delay)
        self._emit_completed(final=True)
        self.emit({"type": "capture_stopped"})

    def _record_connection(self, media_url: str) -> None:
        start_seq = self._sequence + 1
        pattern = self.root / f"segment_{start_seq:08d}_%06d.ts"
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-rw_timeout", "15000000", "-reconnect", "1", "-reconnect_streamed", "1",
                   "-reconnect_delay_max", "10", "-i", media_url, "-map", "0:v:0?",
                   "-map", "0:a:0?", "-c", "copy", "-f", "segment", "-segment_time",
                   str(self.segment_seconds), "-reset_timestamps", "1", "-segment_format", "mpegts",
                   str(pattern)]
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = self.popen(command, **kwargs)
        while process.poll() is None and not self.stop_requested():
            self._emit_completed()
            self.sleep(0.5)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except Exception:
                process.kill()
        self._emit_completed(final=True)

    def _emit_completed(self, final: bool = False) -> None:
        paths = sorted(self.root.glob("segment_*.ts"))
        active = paths[-1] if paths and not final else None
        for path in paths:
            if path in self._known or path == active or path.stat().st_size == 0:
                continue
            self._known.add(path)
            self._sequence += 1
            duration = self._probe_duration(path)
            segment = Segment(path=path, sequence=self._sequence,
                              started_at=self._timeline_seconds,
                              duration=duration)
            self._timeline_seconds += duration
            removed = self.buffer.add(segment)
            self.emit({"type": "segment_ready", "path": str(path), "sequence": segment.sequence,
                       "duration": segment.duration, "buffer_segments": len(self.buffer.segments),
                       "pruned": [str(item) for item in removed]})
            if self.on_segment:
                self.on_segment(segment, self.buffer)

    def _probe_duration(self, path: Path) -> float:
        result = subprocess.run([self.ffmpeg, "-hide_banner", "-i", str(path), "-t", "0",
                                 "-f", "null", "-"], capture_output=True, text=True,
                                check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                                if os.name == "nt" else 0)
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if not match:
            return float(self.segment_seconds)
        hours, minutes, seconds = match.groups()
        return max(0.001, int(hours) * 3600 + int(minutes) * 60 + float(seconds))
