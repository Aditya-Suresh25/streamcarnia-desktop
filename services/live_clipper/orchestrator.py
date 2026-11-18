"""Incremental live highlight detection and adapter to the existing VOD pipeline."""
from __future__ import annotations

import time
import uuid
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import numpy as np

from .capture import RollingSegmentBuffer, Segment
from .detector import IncrementalHighlightDetector, audio_energy_per_second
from .handoff import VodHandoff
from .metadata import generate_metadata
from .scheduler import UploadScheduler
from .store import LiveJobStore


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
                 handoff_factory=VodHandoff, clock=time.monotonic, store=None,
                 metadata_factory=generate_metadata, vault_factory=None, youtube_builder=None,
                 uploader_factory=None, gemini_client_factory=None):
        self.config = dict(config)
        self.ffmpeg = ffmpeg
        self.output_dir = Path(output_dir)
        self.emit = emit
        self.chat_provider = chat_provider
        self.energy_provider = energy_provider
        self.handoff_factory = handoff_factory
        self.clock = clock
        self.store = store or LiveJobStore()
        self.metadata_factory = metadata_factory
        self.gemini_client_factory = gemini_client_factory
        self.vault_factory = vault_factory
        self.youtube_builder = youtube_builder
        self.uploader_factory = uploader_factory
        self.detector = IncrementalHighlightDetector(
            threshold=float(config.get("threshold", 2.0)), cooldown_seconds=120,
            max_clips=int(config.get("max_clips_per_stream", 10)))
        self.pending: list[PendingHighlight] = []
        self.completed = 0
        self.failed = 0
        self.fatal_error: str | None = None
        self._clip_started: dict[str, float] = {}
        self._progress_state: dict[str, tuple[str, float]] = {}

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
                try:
                    job_id = self.store.create(self.config.get("stream_url", ""), {
                        "trigger_at": highlight.trigger_at, "score": highlight.score,
                        "audio_score": highlight.audio_score, "chat_score": highlight.chat_score,
                        "clip_length_seconds": length, "state": "detected",
                    })
                except (sqlite3.Error, OSError) as exc:
                    self.fatal_error = f"Live job storage failed: {exc}"
                    self.emit({"type": "storage_error", "message": self.fatal_error})
                    raise
                pending.key = job_id
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
            if self.fatal_error:
                raise
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
                self.store.update(pending.key, "rendered", {"file_path": str(final)})
                self.emit({"type": "rendered", "id": pending.key, "clip": clip_number,
                           "path": str(final), "state": "rendered", "completed": self.completed})
                metadata = self._make_metadata(final, pending.trigger_at)
                self.store.update(pending.key, "titled", {"metadata": metadata, "file_path": str(final)})
                self.emit({"type": "titled", "id": pending.key, "clip": clip_number,
                           "metadata": metadata, "fallback": metadata.get("fallback", False),
                           "state": "titled"})
                if not self.config.get("approve_before_upload", True):
                    self.approve(pending.key)
            except Exception as exc:
                if isinstance(exc, (sqlite3.Error, OSError)):
                    self.fatal_error = f"Live job storage failed: {exc}"
                    self.emit({"type": "storage_error", "message": self.fatal_error})
                    raise
                self.failed += 1
                self.emit({"type": "clip_failed", "id": pending.key, "clip": clip_number,
                           "stage": "render", "message": str(exc), "failed": self.failed})
            finally:
                buffer.unpin(pending.key)
                self._clip_started.pop(pending.key, None)
                self._progress_state.pop(pending.key, None)

    def _make_metadata(self, final: Path, trigger_at: float) -> dict:
        transcript = ""
        clips_file = final.parent / "clips.json"
        try:
            import json
            entries = json.loads(clips_file.read_text(encoding="utf-8"))
            transcript = str(entries[0].get("transcript", "")) if entries else ""
        except (OSError, ValueError, IndexError, TypeError):
            pass
        api_key = None
        try:
            if self.vault_factory:
                vault = self.vault_factory()
            else:
                from .secrets import CredentialVault
                vault = CredentialVault()
            api_key = vault.get("gemini.api_key")
        except Exception as exc:
            self.emit({"type": "metadata_fallback", "reason": str(exc)})
        return self.metadata_factory(transcript, self.config.get("stream_name", "Live stream"),
                                     api_key, client_factory=self.gemini_client_factory)

    def approve(self, job_id: str) -> str:
        try:
            from .secrets import CredentialVault
            vault = self.vault_factory() if self.vault_factory else CredentialVault()
            oauth_ready = bool(vault.get("youtube.oauth"))
        except Exception:
            oauth_ready = False
        uploader = self._make_uploader(vault if oauth_ready else None)
        scheduler = UploadScheduler(self.store, uploader)
        when = scheduler.approve_and_schedule(job_id,
            self.config.get("schedule_start", "09:00"), self.config.get("schedule_end", "21:00"))
        self.emit({"type": "scheduled", "id": job_id, "scheduled_at": when.isoformat(), "state": "scheduled"})
        return when.isoformat()

    def tick(self) -> None:
        for job in self.store.list_jobs():
            if job["state"] != "scheduled":
                continue
            if self._clip_started.get("upload:" + job["id"], 0) > self.clock():
                continue
            try:
                scheduled_at = datetime.fromisoformat(job["data"]["scheduled_at"])
                if datetime.now().astimezone() < scheduled_at - timedelta(minutes=15):
                    continue
                from .secrets import CredentialVault
                vault = self.vault_factory() if self.vault_factory else CredentialVault()
                if not vault.get("youtube.oauth"):
                    continue
                uploader = self._make_uploader(vault)
                video_id = UploadScheduler(self.store, uploader).upload_due(job["id"])
                if video_id:
                    self.emit({"type": "uploaded", "id": job["id"],
                               "youtube_video_id": video_id, "state": "uploaded"})
            except RuntimeError:
                pass
            except Exception as exc:
                self._clip_started["upload:" + job["id"]] = self.clock() + 60
                self.emit({"type": "upload_error", "id": job["id"], "message": str(exc)})

    def _make_uploader(self, vault):
        if self.uploader_factory:
            return self.uploader_factory(vault)
        if not vault or not self.config.get("oauth_client_file"):
            return None
        from .youtube import YouTubeUploader, youtube_service
        service = (self.youtube_builder(self.config["oauth_client_file"], vault)
                   if self.youtube_builder else youtube_service(self.config["oauth_client_file"], vault))
        return YouTubeUploader(service)

    def _forward_progress(self, event: dict, key: str, clip_number: int, total: int) -> None:
        stage = event.get("stage", "working")
        now = self.clock()
        starts = {"edit": 0.08, "transcribe": 0.38, "romanize": 0.63, "burn": 0.72}
        ends = {"edit": 0.38, "transcribe": 0.63, "romanize": 0.72, "burn": 0.90}
        estimates = {"edit": 45.0, "transcribe": 180.0, "romanize": 12.0, "burn": 90.0}
        if event.get("heartbeat") and stage in starts:
            previous = self._progress_state.get(key)
            stage_started = previous[1] if previous and previous[0] == stage else now
            elapsed_stage = max(0.0, now - stage_started)
            fraction = starts[stage] + (ends[stage] - starts[stage]) * min(
                0.97, elapsed_stage / estimates[stage])
        else:
            self._progress_state[key] = (stage, now)
            fixed = {"source": 0.02, "ready": 0.08, "done": 1.0, "clip_failed": 1.0}
            fraction = starts.get(stage, fixed.get(stage, 0.1))
            if stage in starts:
                fraction = starts[stage]
        started = self._clip_started.get(key, now)
        elapsed = max(0.0, now - started)
        eta = int(elapsed * (1 - fraction) / max(fraction, 0.01)) if fraction > 0.02 else None
        self.emit({"type": "clip_progress", "id": key, "clip": clip_number, "total": total,
                   "stage": stage, "percent": int(fraction * 100),
                   "eta_seconds": eta})
