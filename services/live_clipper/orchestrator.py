"""Incremental live highlight detection and adapter to the existing VOD pipeline."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .capture import RollingSegmentBuffer, Segment
from .detector import IncrementalHighlightDetector, audio_energy_per_second
from .handoff import VodHandoff


@dataclass
class PendingHighlight:
    key: str
    trigger_at: float
    score: float
    ready_at: float


class LiveAutoClipper:
    def __init__(self, *, config: dict, ffmpeg: str, output_dir: Path,
                 emit: Callable[[dict], None], chat_provider: Callable[[Segment], np.ndarray | None] | None = None,
                 energy_provider: Callable[[Path, str], np.ndarray] = audio_energy_per_second,
                 handoff_factory=VodHandoff, clock=time.monotonic):
        self.config = dict(config)
        self.ffmpeg = ffmpeg
        self.output_dir = Path(output_dir)
        self.emit = emit
        self.chat_provider = chat_provider
        self.energy_provider = energy_provider
        self.handoff_factory = handoff_factory
        self.clock = clock
        self.detector = IncrementalHighlightDetector(
            threshold=float(config.get("threshold", 2.0)), cooldown_seconds=120,
            max_clips=int(config.get("max_clips_per_stream", 10)))
        self.pending: list[PendingHighlight] = []
        self.completed = 0
        self.failed = 0
        self._clip_started: dict[str, float] = {}

    def on_segment(self, segment: Segment, buffer: RollingSegmentBuffer) -> None:
        try:
            energies = self.energy_provider(segment.path, self.ffmpeg)
            chat = None
            if self.chat_provider:
                try:
                    chat = self.chat_provider(segment)
                except Exception as exc:
                    self.emit({"type": "chat_unavailable", "message": str(exc)})
            highlights = self.detector.process(energies, segment.started_at, chat)
            for highlight in highlights:
                length = int(self.config.get("clip_length_seconds", 60))
                key = str(uuid.uuid4())
                pending = PendingHighlight(key, highlight.trigger_at, highlight.score,
                                           highlight.trigger_at + length - 20)
                self.pending.append(pending)
                needed_start = highlight.trigger_at - 20
                sequences = [item.sequence for item in buffer.segments
                             if item.started_at + item.duration > needed_start]
                buffer.pin(key, sequences)
                self.emit({"type": "detected", "id": key, "trigger_at": highlight.trigger_at,
                           "score": round(highlight.score, 3), "audio_score": round(highlight.audio_score, 3),
                           "chat_score": None if highlight.chat_score is None else round(highlight.chat_score, 3),
                           "state": "detected"})
            self._refresh_pins(buffer)
            self._render_ready(buffer, segment.started_at + segment.duration)
        except Exception as exc:
            self.emit({"type": "analysis_error", "sequence": segment.sequence,
                       "stage": "audio analysis", "message": str(exc)})

    def finish(self, buffer: RollingSegmentBuffer) -> None:
        available_end = max((s.started_at + s.duration for s in buffer.segments), default=0.0)
        self._render_ready(buffer, available_end, ended=True)

    def _refresh_pins(self, buffer: RollingSegmentBuffer) -> None:
        for pending in self.pending:
            start = pending.trigger_at - 20
            end = pending.ready_at + 20
            sequences = [segment.sequence for segment in buffer.segments
                         if segment.started_at < end and segment.started_at + segment.duration > start]
            buffer.pin(pending.key, sequences)

    def _render_ready(self, buffer: RollingSegmentBuffer, available_end: float, ended: bool = False) -> None:
        ready = [item for item in self.pending if ended or item.ready_at <= available_end]
        for pending in ready:
            self.pending.remove(pending)
            duration = int(self.config.get("clip_length_seconds", 60))
            start = pending.trigger_at - 20
            end = min(available_end, pending.ready_at + 20)
            chosen = [segment for segment in buffer.segments
                      if segment.started_at < end and segment.started_at + segment.duration > start]
            clip_number = self.completed + self.failed + 1
            total = int(self.config.get("max_clips_per_stream", 10))
            self._clip_started[pending.key] = self.clock()
            self.emit({"type": "clip_progress", "id": pending.key, "clip": clip_number,
                       "total": total, "stage": "preparing", "percent": 2, "eta_seconds": None})
            try:
                handoff = self.handoff_factory(self.ffmpeg, self.output_dir / "clips")
                final = handoff.render(chosen, pending.trigger_at, self.config,
                                       progress=lambda event: self._forward_progress(event, pending.key, clip_number, total))
                self.completed += 1
                self.emit({"type": "rendered", "id": pending.key, "clip": clip_number,
                           "path": str(final), "state": "rendered", "completed": self.completed})
            except Exception as exc:
                self.failed += 1
                self.emit({"type": "clip_failed", "id": pending.key, "clip": clip_number,
                           "stage": "render", "message": str(exc), "failed": self.failed})
            finally:
                buffer.unpin(pending.key)
                self._clip_started.pop(pending.key, None)

    def _forward_progress(self, event: dict, key: str, clip_number: int, total: int) -> None:
        fractions = {"source": 0.02, "ready": 0.08, "edit": 0.38, "transcribe": 0.63,
                     "romanize": 0.72, "burn": 0.90, "done": 1.0, "clip_failed": 1.0}
        fraction = fractions.get(event.get("stage", ""), 0.1)
        started = self._clip_started.get(key, self.clock())
        elapsed = max(0.0, self.clock() - started)
        eta = int(elapsed * (1 - fraction) / max(fraction, 0.01)) if fraction > 0.02 else None
        self.emit({"type": "clip_progress", "id": key, "clip": clip_number, "total": total,
                   "stage": event.get("stage", "working"), "percent": int(fraction * 100),
                   "eta_seconds": eta})
