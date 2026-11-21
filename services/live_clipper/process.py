"""Process supervisor for a live monitor so worker crashes spare the GUI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from core.paths import app_data_dir
from core.media_storage import configure_media_storage, media_cache_dir
from .worker import run_worker  # exposed as the packaged worker entry point


class LiveProcessController:
    def __init__(self, runtime_root: Path | None = None):
        self._process = None
        self._runtime_root = Path(runtime_root) if runtime_root else None
        self._runtime = None
        self._event_path = None
        self._event_offset = 0

    @property
    def running(self) -> bool:
        return bool(self._process and self._process.poll() is None)

    def start(self, config: dict) -> None:
        if self.running:
            raise RuntimeError("A live monitor is already running")
        if not config.get("enabled", config.get("live_clipper.enabled", False)):
            raise RuntimeError("Live Auto Clipper is disabled in Settings")
        runtime_root = Path(config.get("runtime_root") or self._runtime_root or
                            (app_data_dir() / "live_clipper" / "runtime"))
        runtime = runtime_root / str(uuid.uuid4())
        runtime.mkdir(parents=True, exist_ok=True)
        self._runtime = runtime
        self._event_path = runtime / "events.jsonl"
        self._event_offset = 0
        payload = dict(config)
        payload.update(event_path=str(self._event_path), stop_path=str(runtime / "stop"),
                       command_dir=str(runtime / "commands"))
        Path(payload["command_dir"]).mkdir(parents=True, exist_ok=True)
        config_path = runtime / "config.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--run-live-worker", str(config_path)]
        else:
            entry = Path(__file__).resolve().parents[2] / "main.py"
            command = [sys.executable, str(entry), "--run-live-worker", str(config_path)]
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                  "stderr": subprocess.DEVNULL, "cwd": str(Path(__file__).resolve().parents[2])}
        media_root = Path(config.get("media_root") or config.get("output_dir") or runtime_root.parent)
        configure_media_storage(media_root)
        cache = media_cache_dir(media_root)
        cache_tmp = cache / "tmp"
        cache_tmp.mkdir(parents=True, exist_ok=True)
        kwargs["env"] = os.environ.copy()
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self._process = subprocess.Popen(command, **kwargs)

    def send(self, command) -> None:
        if command == "stop" and self._runtime:
            (self._runtime / "stop").touch()
        elif isinstance(command, dict) and self._runtime:
            command_dir = self._runtime / "commands"
            command_dir.mkdir(exist_ok=True)
            path = command_dir / f"{uuid.uuid4()}.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(command, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)

    def request_stop(self) -> None:
        self.send("stop")

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
            self.request_stop()
            try:
                self._process.wait(timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    try:
                        subprocess.run(["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                                       timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    except subprocess.TimeoutExpired:
                        self._process.kill()
                else:
                    self._process.terminate()
                try:
                    self._process.wait(3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
        self._process = None
