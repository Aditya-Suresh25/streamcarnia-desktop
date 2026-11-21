#!/usr/bin/env python3
"""yt-dlp wrapper: info / audio / chat / section / full / live.

Only download content you own or have permission to clip. Downloading may
also be restricted by the platform's terms of service.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path
from pathlib import Path

from common import no_console_kwargs, parse_time, run

FMT = "bv*[height<={h}]+ba/b[height<={h}]"


def ytdlp(*args, cookies=None):
    cmd = [sys.executable]
    if getattr(sys, "frozen", False):
        cmd += ["--run-ytdlp"]
    else:
        cmd += ["-m", "yt_dlp"]
    cmd += ["--no-playlist", "--no-warnings"]
    cache_dir = os.environ.get("STREAMCARNIA_CACHE_DIR")
    if cache_dir:
        cmd += ["--cache-dir", cache_dir]
    if cookies:
        if Path(cookies).is_file():
            cmd += ["--cookies", cookies]
        else:
            cmd += ["--cookies-from-browser", cookies]
    return cmd + list(args)


def info(url, cookies=None):
    out = subprocess.run(ytdlp("-J", url, cookies=cookies), check=True, capture_output=True,
                         text=True, **no_console_kwargs()).stdout
    d = json.loads(out)
    return {
        "id": d.get("id"), "title": d.get("title"), "channel": d.get("channel"),
        "duration": d.get("duration"), "is_live": bool(d.get("is_live")),
        "was_live": bool(d.get("was_live")), "live_status": d.get("live_status"),
    }


def audio(url, out_dir, cookies=None):
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    for old in glob.glob(str(out_dir / "audio.*")):
        Path(old).unlink()
    run(ytdlp("-f", "bestaudio/worst", "-o", str(out_dir / "audio.%(ext)s"), url, cookies=cookies))
    files = [f for f in glob.glob(str(out_dir / "audio.*")) if not f.endswith(".part")]
    if not files:
        raise SystemExit("audio download produced no file")
    return files[0]


def chat(url, out_dir, cookies=None):
    """Chat replay (archived streams only). Returns path or None."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    try:
        run(ytdlp("--skip-download", "--write-subs", "--sub-langs", "live_chat",
                  "-o", str(out_dir / "chat"), url, cookies=cookies))
    except subprocess.CalledProcessError:
        return None
    files = glob.glob(str(out_dir / "chat*.live_chat.json"))
    return files[0] if files else None


def section(url, start, end, out_file, max_height=1080, cookies=None):
    out_file = Path(out_file); out_file.parent.mkdir(parents=True, exist_ok=True)
    run(ytdlp("-f", FMT.format(h=max_height), "--download-sections", f"*{start:.2f}-{end:.2f}",
              "--force-keyframes-at-cuts", "--merge-output-format", "mp4",
              "-o", str(out_file), "--force-overwrites", url, cookies=cookies))
    return str(out_file)


def full(url, out_file, max_height=1080, cookies=None):
    out_file = Path(out_file); out_file.parent.mkdir(parents=True, exist_ok=True)
    run(ytdlp("-f", FMT.format(h=max_height), "--merge-output-format", "mp4",
              "-o", str(out_file), url, cookies=cookies))
    return str(out_file)


def live(url, out_file, seconds, max_height=1080, cookies=None):
    """Record the first `seconds` of a stream that is currently live."""
    out_file = Path(out_file); out_file.parent.mkdir(parents=True, exist_ok=True)
    run(ytdlp("-f", f"b[height<={max_height}]/b", "--hls-use-mpegts", "--downloader", "ffmpeg",
              "--downloader-args", f"ffmpeg:-t {int(seconds)}", "-o", str(out_file), url, cookies=cookies))
    return str(out_file)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["info", "audio", "chat", "section", "full", "live"])
    ap.add_argument("url")
    ap.add_argument("--out", help="output dir (audio/chat) or file (section/full/live)")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--seconds", type=float, default=1800, help="live: how long to record")
    ap.add_argument("--max-height", type=int, default=1080)
    ap.add_argument("--cookies-from-browser", dest="cookies", help="e.g. chrome, firefox (members-only / age-gated)")
    a = ap.parse_args()
    if a.cmd == "info":
        print(json.dumps(info(a.url, a.cookies), indent=2))
    elif a.cmd == "audio":
        print(audio(a.url, a.out, a.cookies))
    elif a.cmd == "chat":
        print(chat(a.url, a.out, a.cookies) or "")
    elif a.cmd == "section":
        print(section(a.url, parse_time(a.start), parse_time(a.end), a.out, a.max_height, a.cookies))
    elif a.cmd == "full":
        print(full(a.url, a.out, a.max_height, a.cookies))
    elif a.cmd == "live":
        print(live(a.url, a.out, a.seconds, a.max_height, a.cookies))


if __name__ == "__main__":
    main()
