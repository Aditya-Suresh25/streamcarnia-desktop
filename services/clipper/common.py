"""Shared helpers for the livestream-clipper scripts."""
import json
import os
import re
import shutil
import subprocess
import sys


def no_console_kwargs():
    """Hide child console windows on Windows; no-op on other platforms."""
    if os.name != "nt":
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), file=sys.stderr)
    kw.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def parse_time(s):
    """'90', '1:30', '01:02:03' or '1h2m3s' -> seconds (float)."""
    s = str(s).strip().lower()
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", s)
    if m and any(m.groups()) and not re.fullmatch(r"\d+(\.\d+)?", s):
        h, mi, sec = (float(x) if x else 0 for x in m.groups())
        return h * 3600 + mi * 60 + sec
    parts = [float(p) for p in s.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def fmt_time(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def probe(path):
    if shutil.which("ffprobe"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            check=True, capture_output=True, text=True, **no_console_kwargs(),
        ).stdout
        data = json.loads(out)
        v = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
        return {
            "duration": float(data["format"].get("duration", 0) or 0),
            "width": int(v["width"]) if v else None,
            "height": int(v["height"]) if v else None,
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"]),
        }
    # Some portable Windows FFmpeg bundles ship ffmpeg.exe alone. Its input
    # banner gives us the same small metadata subset needed by the clip flow.
    result = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-t", "0", "-f", "null", "-"],
                            capture_output=True, text=True, check=False, **no_console_kwargs())
    banner = result.stderr
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", banner)
    video = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", banner)
    if not duration or not video:
        raise RuntimeError(f"Unable to inspect media file: {path}")
    hours, minutes, seconds = duration.groups()
    return {"duration": int(hours) * 3600 + int(minutes) * 60 + float(seconds),
            "width": int(video.group(1)), "height": int(video.group(2)),
            "has_audio": "Audio:" in banner}
