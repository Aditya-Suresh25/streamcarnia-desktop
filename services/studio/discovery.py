"""Adapter for the existing local-file highlight discovery pipeline."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event, Thread
from typing import Callable

from core.paths import resource_path


class StudioDiscoveryError(RuntimeError):
    """The existing clipper could not produce a valid candidate list."""


class StudioDiscoveryCancelled(StudioDiscoveryError):
    """Discovery was cancelled by the caller."""


ProgressCallback = Callable[[dict], None]


def run_discovery(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    top: int = 8,
    ffmpeg_path: str | Path | None = None,
    cancelled: Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> list[dict]:
    """Run real VOD highlight detection for a local video and return its candidates.

    Candidate dictionaries are loaded from the clipper's ``candidates.json``
    without rewriting their scores, reasons, order, or other backend fields.
    """
    source = Path(source_path).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if cancelled and cancelled.is_set():
        raise StudioDiscoveryCancelled("Highlight discovery was cancelled.")
    if not source.is_file():
        raise StudioDiscoveryError(f"Source video does not exist: {source}")
    if not isinstance(top, int) or isinstance(top, bool) or top < 1:
        raise StudioDiscoveryError("Candidate count must be a positive integer.")
    pipeline_dir = resource_path("services", "clipper")
    pipeline = pipeline_dir / "pipeline.py"
    if not pipeline.is_file():
        raise StudioDiscoveryError("The bundled highlight detection pipeline is unavailable.")

    output.mkdir(parents=True, exist_ok=True)
    candidates_file = output / "candidates.json"
    # Do not mistake results from an earlier run for this run's output. The
    # pipeline writes candidates atomically, so removing only this generated
    # artifact is safe while leaving all other project files untouched.
    try:
        candidates_file.unlink(missing_ok=True)
    except OSError as exc:
        raise StudioDiscoveryError(f"Could not prepare highlight output: {exc}") from exc
    command = ([sys.executable, "--run-clipper", str(pipeline)]
               if getattr(sys, "frozen", False)
               else [sys.executable, str(pipeline)])
    command += [str(source), "--out", str(output), "--top", str(top),
                "--detect-only", "--archived-only"]
    env = os.environ.copy()
    if ffmpeg_path:
        ffmpeg_dir = str(Path(ffmpeg_path).expanduser().resolve().parent)
        env["PATH"] = ffmpeg_dir + os.pathsep + env.get("PATH", "")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    popen_extra = {} if os.name == "nt" else {"start_new_session": True}
    process = None
    monitor_stop = Event()
    monitor = None
    log_lines: list[str] = []
    try:
        process = subprocess.Popen(
            command, cwd=str(pipeline_dir), env=env, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
            bufsize=1, creationflags=flags, **popen_extra,
        )
        if cancelled is not None:
            def stop_when_cancelled() -> None:
                while not monitor_stop.wait(0.1):
                    if cancelled.is_set():
                        _stop_process(process)
                        return
            monitor = Thread(target=stop_when_cancelled, name="studio-discovery-cancel", daemon=True)
            monitor.start()
        if on_progress:
            on_progress({"stage": "running", "message": "Analysing video for highlights", "percent": None})
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            log_lines.append(line)
            if len(log_lines) > 200:
                del log_lines[:100]
            if line.startswith("@@SC_PROGRESS@@"):
                try:
                    event = json.loads(line[len("@@SC_PROGRESS@@"):])
                except (ValueError, TypeError):
                    event = None
                if event is not None and on_progress:
                    on_progress({"stage": event.get("stage", "running"),
                                 "message": event.get("stage", "Working"), "percent": None,
                                 "backend_event": event})
            elif "detecting highlights" in line.lower() and on_progress:
                on_progress({"stage": "detecting", "message": "Finding highlight moments", "percent": None})
            if cancelled and cancelled.is_set():
                _stop_process(process)
                raise StudioDiscoveryCancelled("Highlight discovery was cancelled.")
        code = process.wait()
        if cancelled and cancelled.is_set():
            raise StudioDiscoveryCancelled("Highlight discovery was cancelled.")
        if code != 0:
            detail = next((line.strip() for line in reversed(log_lines)
                           if "error" in line.lower() or "exception" in line.lower()), "")
            suffix = f" {detail}" if detail else ""
            raise StudioDiscoveryError(f"Highlight detection failed (exit code {code}).{suffix}")
        if not candidates_file.is_file():
            raise StudioDiscoveryError("Highlight detection finished without candidates.json.")
        try:
            candidates = json.loads(candidates_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StudioDiscoveryError(f"Could not read highlight candidates: {exc}") from exc
        if not isinstance(candidates, list) or any(not isinstance(item, dict) for item in candidates):
            raise StudioDiscoveryError("The highlight pipeline returned an invalid candidate list.")
        if on_progress:
            on_progress({"stage": "completed", "message": "Highlight discovery complete", "percent": 100})
        return candidates
    except StudioDiscoveryError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise StudioDiscoveryError(f"Could not run highlight detection: {exc}") from exc
    finally:
        monitor_stop.set()
        if monitor is not None:
            monitor.join(timeout=11)
        if process is not None and process.poll() is None:
            _stop_process(process)


def _stop_process(process: subprocess.Popen) -> None:
    """Stop only the isolated detection process, tolerating exit races."""
    if process.poll() is not None:
        return
    if os.name == "nt" and getattr(process, "pid", None):
        try:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            process.wait(timeout=5)
            return
        except (OSError, subprocess.SubprocessError):
            pass
    elif os.name != "nt" and getattr(process, "pid", None):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
            return
        except (OSError, subprocess.SubprocessError):
            try:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
                return
            except (OSError, subprocess.SubprocessError):
                pass
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
