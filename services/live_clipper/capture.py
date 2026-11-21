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
    wall_started_at: float | None = None


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

    def clear(self) -> list[Path]:
        removed = []
        for segment in list(self._segments):
            if any(segment.sequence in sequences for sequences in self._pins.values()):
                continue
            self._segments.remove(segment)
            segment.path.unlink(missing_ok=True)
            removed.append(segment.path)
        return removed

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


def resolve_live_media(url: str) -> tuple[dict, bool, str]:
    """Return one or more direct media tracks and whether the source is live.

    YouTube live streams commonly expose video and audio as separate HLS
    formats. Asking yt-dlp for ``best`` alone only works when a muxed format is
    available, so request both tracks with a muxed fallback.
    """
    import yt_dlp

    options = {"quiet": True, "no_warnings": True, "noplaylist": True,
               "format": "bestvideo+bestaudio/best",
               "cachedir": os.environ.get("STREAMCARNIA_CACHE_DIR", False)}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("Stream metadata could not be read")
    if info.get("is_live") is False and info.get("live_status") not in ("is_live", "is_upcoming"):
        return "", False, str(info.get("title") or "Live stream")
    requested = info.get("requested_formats")
    if isinstance(requested, list) and requested:
        streams = []
        for item in requested:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            streams.append({"url": str(item["url"]),
                            "headers": item.get("http_headers") or info.get("http_headers") or {}})
        if streams:
            return {"streams": streams}, True, str(info.get("title") or "Live stream")
    direct = info.get("url")
    if not direct:
        raise RuntimeError("No direct live media URL was provided by yt-dlp")
    return {"streams": [{"url": str(direct),
                         "headers": info.get("http_headers") or {}}]}, True, str(info.get("title") or "Live stream")


class LiveSegmentRecorder:
    """Capture source via FFmpeg; re-resolve after errors and emit completed segments."""

    def __init__(self, url: str, output_dir: Path, ffmpeg: str, emit: Callable[[dict], None],
                 stop_requested: Callable[[], bool], resolver=resolve_live_media,
                 popen=subprocess.Popen, segment_seconds: int = 300,
                 retention_seconds: int = 1800, reconnect_delay: float = 5.0,
                 sleep: Callable[[float], None] = time.sleep, on_segment: Callable | None = None,
                 on_tick: Callable[[], None] | None = None):
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
        self.on_tick = on_tick
        self.buffer = RollingSegmentBuffer(self.root, retention_seconds)
        self._known: set[Path] = set()
        self._sequence = 0
        self._timeline_seconds = 0.0

    def run(self) -> None:
        while not self.stop_requested():
            try:
                resolved = self.resolver(self.url)
                if len(resolved) == 2:
                    media_url, is_live = resolved
                    title = "Live stream"
                else:
                    media_url, is_live, title = resolved
                self.emit({"type": "stream_title", "title": title})
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

    def _record_connection(self, media_source: str | dict) -> None:
        start_seq = self._sequence + 1
        pattern = self.root / f"segment_{start_seq:08d}_%06d.ts"
        if isinstance(media_source, dict):
            streams = media_source.get("streams") or []
        else:  # Backward compatibility for injected/custom resolvers.
            streams = [{"url": media_source, "headers": {}}]
        streams = [item for item in streams if isinstance(item, dict) and item.get("url")]
        if not streams:
            raise RuntimeError("No usable live media tracks were provided")
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
        for stream in streams:
            command.extend(["-rw_timeout", "15000000", "-reconnect", "1",
                            "-reconnect_streamed", "1", "-reconnect_delay_max", "10"])
            headers = stream.get("headers") or {}
            if isinstance(headers, dict) and headers:
                header_text = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
                command.extend(["-headers", header_text])
            command.extend(["-i", str(stream["url"])])
        audio_input = 1 if len(streams) > 1 else 0
        command.extend(["-map", "0:v:0?", "-map", f"{audio_input}:a:0?", "-c", "copy",
                        "-f", "segment", "-segment_time", str(self.segment_seconds),
                        "-reset_timestamps", "1", "-segment_format", "mpegts", str(pattern)])
        kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = self.popen(command, **kwargs)
        while process.poll() is None and not self.stop_requested():
            self._emit_completed()
            if self.on_tick:
                self.on_tick()
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
                              duration=duration,
                              wall_started_at=path.stat().st_mtime - duration)
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
