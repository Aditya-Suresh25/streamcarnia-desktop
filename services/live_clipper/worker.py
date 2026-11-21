"""Spawn-safe live worker entry point. Capture/detection stages plug in here."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .capture import LiveSegmentRecorder
from .orchestrator import LiveAutoClipper
from .chat import LiveChatVelocity
from .secrets import CredentialVault
from .youtube import active_live_chat_id, youtube_service
from core.media_storage import configure_media_storage
from .store import LiveJobStore


def run_worker(config_path: str) -> int:
    """Keep worker lifetime out of the UI process; append machine-readable events."""
    config_path = Path(config_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    event_path = Path(config["event_path"])
    stop_path = Path(config["stop_path"])
    media_root = Path(config.get("media_root") or config.get("output_dir") or config_path.parent)
    configure_media_storage(media_root, configure_tempfile=True)

    def emit(event: dict) -> None:
        with event_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()

    emit({"type": "started", "stream_url": config.get("stream_url", "")})
    if not config.get("enabled", config.get("live_clipper.enabled", False)):
        emit({"type": "error", "stage": "configuration", "message": "Live Auto Clipper is disabled"})
        return 2
    if config.get("stream_url") and config.get("ffmpeg_path"):
        output_dir = Path(config.get("output_dir", config_path.parent / "output"))
        buffer_dir = Path(config.get("buffer_dir", output_dir / "buffer"))
        store = LiveJobStore(Path(config["queue_db_path"])) if config.get("queue_db_path") else LiveJobStore()
        live = LiveAutoClipper(config=config, ffmpeg=config["ffmpeg_path"],
                               output_dir=output_dir, emit=emit, store=store)

        chat = _create_chat_client(config, emit)
        chat_thread_stop = threading.Event()
        chat_thread = None
        if chat:
            live.chat_provider = lambda segment: chat.counts_for(
                segment.wall_started_at or time.time(), segment.duration)
            chat_thread = threading.Thread(target=_poll_chat, args=(chat, emit, chat_thread_stop),
                                           name="LiveChatPoller", daemon=True)
            chat_thread.start()

        command_dir = Path(config.get("command_dir", config_path.parent / "commands"))

        def poll_control() -> bool:
            for command_path in sorted(command_dir.glob("*.json")) if command_dir.exists() else []:
                try:
                    message = json.loads(command_path.read_text(encoding="utf-8"))
                    if message.get("type") == "approve":
                        live.approve(str(message["job_id"]))
                except Exception as exc:
                    emit({"type": "control_error", "message": str(exc)})
                finally:
                    command_path.unlink(missing_ok=True)
            return stop_path.exists() or live.fatal_error is not None

        recorder = LiveSegmentRecorder(config["stream_url"], buffer_dir,
            config["ffmpeg_path"], lambda event: _forward_capture_event(event, config, live, emit), poll_control,
            segment_seconds=int(config.get("segment_seconds", 300)),
            retention_seconds=int(config.get("retention_seconds", 1800)),
            on_segment=live.on_segment, on_tick=live.tick)
        try:
            recorder.run()
        finally:
            chat_thread_stop.set()
            if chat_thread:
                chat_thread.join(timeout=2)
            if not live.fatal_error:
                live.finish(recorder.buffer)
                recorder.buffer.clear()
        if live.fatal_error:
            return 2
        # Keep scheduled uploads and approval commands alive after the source ends.
        while not poll_control():
            live.tick()
            time.sleep(0.5)
        emit({"type": "stopped"})
        return 0
    emit({"type": "error", "stage": "configuration", "message": "A stream URL and FFmpeg path are required"})
    return 2


def _create_chat_client(config: dict, emit):
    client_file = config.get("oauth_client_file")
    if not client_file:
        return None
    try:
        vault = CredentialVault()
        if not vault.get("youtube.oauth"):
            return None
        service = youtube_service(client_file, vault)
        match = re.search(r"(?:youtu\.be/|[?&]v=|/live/)([\w-]{6,})", config.get("stream_url", ""))
        chat_id = active_live_chat_id(service, match.group(1) if match else None)
        if not chat_id:
            return None
        return LiveChatVelocity(service, chat_id)
    except Exception as exc:
        emit({"type": "chat_unavailable", "message": str(exc)})
        return None


def _poll_chat(chat: LiveChatVelocity, emit, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            delay = chat.poll()
        except Exception as exc:
            emit({"type": "chat_unavailable", "message": str(exc)})
            return
        stop.wait(max(1.0, delay))


def _forward_capture_event(event: dict, config: dict, live: LiveAutoClipper, emit) -> None:
    if event.get("type") == "stream_title" and event.get("title"):
        config["stream_name"] = str(event["title"])
        live.config["stream_name"] = str(event["title"])
    emit(event)
