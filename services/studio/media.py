"""Media probing and thumbnail extraction for desktop Studio assets."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def probe_media(path: Path, ffmpeg_path: str | None = None) -> dict:
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose a video file.")
    try:
        import av
        with av.open(str(path)) as container:
            stream = next((item for item in container.streams if item.type == "video"), None)
            if stream is None:
                raise ValueError("The selected file does not contain a video stream.")
            duration = float(container.duration or 0) / float(av.time_base)
            return {"duration": duration, "width": int(stream.width), "height": int(stream.height)}
    except ImportError:
        pass
    ffprobe = "ffprobe"
    if ffmpeg_path and Path(ffmpeg_path).exists():
        ffprobe_candidate = Path(ffmpeg_path).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if ffprobe_candidate.exists():
            ffprobe = str(ffprobe_candidate)
    result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0, check=True)
    payload = json.loads(result.stdout)
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "video"), None)
    if not stream:
        raise ValueError("The selected file does not contain a video stream.")
    return {"duration": float(payload.get("format", {}).get("duration", 0) or 0),
            "width": int(stream["width"]), "height": int(stream["height"])}


def extract_thumbnail(video: Path, at_seconds: float, output: Path, ffmpeg_path: str) -> Path:
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{max(0, at_seconds):.3f}",
        "-i", str(Path(video).resolve()), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2", "-q:v", "2", str(output)],
        capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0, check=True)
    return output
