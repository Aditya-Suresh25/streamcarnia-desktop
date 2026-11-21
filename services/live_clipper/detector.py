"""Incremental audio-energy and optional live-chat highlight scoring."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import os
import subprocess

import numpy as np


@dataclass(frozen=True)
class Highlight:
    trigger_at: float
    score: float
    audio_score: float
    chat_score: float | None
    trigger_reason: str


def audio_energy_per_second(path: Path, ffmpeg: str) -> np.ndarray:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn",
               "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    result = subprocess.run(command, capture_output=True, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                            if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError("FFmpeg could not decode audio from a live segment")
    samples = np.frombuffer(result.stdout[: len(result.stdout) // 32000 * 32000], dtype="<i2")
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    samples = samples.astype(np.float32).reshape(-1, 16000) / 32768.0
    rms = np.sqrt(np.mean(samples * samples, axis=1) + 1e-10)
    return (20.0 * np.log10(rms)).astype(np.float32)


class IncrementalHighlightDetector:
    def __init__(self, threshold: float = 2.0, cooldown_seconds: int = 600,
                 max_clips: int = 10, audio_baseline_seconds: int = 120,
                 chat_baseline_seconds: int = 60):
        self.threshold = float(threshold)
        self.cooldown_seconds = int(cooldown_seconds)
        self.max_clips = int(max_clips)
        self.audio_history = deque(maxlen=audio_baseline_seconds)
        self.chat_history = deque(maxlen=chat_baseline_seconds)
        self.last_trigger: float | None = None
        self.clip_count = 0

    def process(self, values, start_at: float, chat_values=None) -> list[Highlight]:
        energies = np.asarray(values, dtype=np.float32).reshape(-1)
        chats = None if chat_values is None else np.asarray(chat_values, dtype=np.float32).reshape(-1)
        if chats is not None and len(chats) != len(energies):
            raise ValueError("Chat velocity must have one value per audio second")
        found = []
        for offset, energy in enumerate(energies):
            chat_value = float(chats[offset]) if chats is not None else None
            audio_score = self._zscore(float(energy), self.audio_history)
            chat_score = self._zscore(chat_value, self.chat_history) if chats is not None else None
            # A real spike in either signal should trigger a clip. Averaging
            # the two used to dilute chat-only bursts and audio-only peaks.
            reasons = []
            if audio_score >= self.threshold:
                reasons.append("audio")
            if chat_score is not None and chat_score >= self.threshold:
                reasons.append("chat")
            score = max(audio_score, chat_score if chat_score is not None else float("-inf"))
            timestamp = start_at + offset
            if (self.clip_count < self.max_clips and reasons and
                    (self.last_trigger is None or timestamp - self.last_trigger >= self.cooldown_seconds)):
                found.append(Highlight(timestamp, float(score), float(audio_score), chat_score,
                                       "+".join(reasons)))
                self.last_trigger = timestamp
                self.clip_count += 1
            self.audio_history.append(float(energy))
            if chat_value is not None:
                self.chat_history.append(chat_value)
        return found

    @staticmethod
    def _zscore(value: float, history) -> float:
        if not history:
            return 0.0
        prior = np.asarray(history, dtype=np.float32)
        mean = float(np.mean(prior))
        std = max(float(np.std(prior)), 1.0)
        return (value - mean) / std
