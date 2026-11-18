"""Process supervisor for a live monitor so worker crashes spare the GUI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from core.paths import app_data_dir
from .worker import run_worker  # exposed as the packaged worker entry point


class LiveProcessController:
    def __init__(self, runtime_root: Path | None = None):
        self._process = None
        self._runtime_root = Path(runtime_root) if runtime_root else app_data_dir() / "live_clipper" / "runtime"
        self._runtime = None
        self._event_path = None
        self._event_offset = 0

    @property
    def running(self) -> bool:
        return bool(self._process and self._process.is_alive())

    def start(self, config: dict) -> None:
        if self.running:
            raise RuntimeError("A live monitor is already running")
        runtime = self._runtime_root / str(uuid.uuid4())
        runtime.mkdir(parents=True, exist_ok=True)
        self._runtime = runtime
        self._event_path = runtime / "events.jsonl"
        self._event_offset = 0
        payload = dict(config)
        payload.update(event_path=str(self._event_path), stop_path=str(runtime / "stop"))
        config_path = runtime / "config.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-live-worker", str(config_path)]
        else:
            entry = Path(__file__).resolve().parents[2] / "main.py"
            command = [sys.executable, str(entry), "--run-live-worker", str(config_path)]
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                  "stderr": subprocess.DEVNULL, "cwd": str(Path(__file__).resolve().parents[2])}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._process = subprocess.Popen(command, **kwargs)

    def send(self, command: str) -> None:
        if command == "stop" and self._runtime:
            (self._runtime / "stop").touch()

    def poll(self) -> list[dict]:
        events = []
        if self._event_path is None or not self._event_path.exists():
            return events
        with self._event_path.open("r", encoding="utf-8") as stream:
            stream.seek(self._event_offset)
            for line in stream:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            self._event_offset = stream.tell()
        if self._process and self._process.poll() is not None and self._process.returncode != 0:
            if not any(e.get("type") == "crashed" for e in events):
                events.append({"type": "crashed", "exit_code": self._process.returncode})
        return events

    def stop(self, timeout: float = 5.0) -> None:
        if self._process is None:
            return
        if self._process.poll() is None:
            self.send("stop")
            try:
                self._process.wait(timeout)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(1)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        self._process = None
