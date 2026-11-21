#!/usr/bin/env python3
"""Burn an .ass caption file into a video (libass via ffmpeg)."""
import argparse
import os
import shutil
import tempfile
from pathlib import Path

from common import run


def esc_path(p):
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def burn(video, ass, out, fontsdir=None, channel_name=None, subscriber_text=None, logo=None):
    video, ass, out = Path(video).resolve(), Path(ass).resolve(), Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or None) as td:
        # Copy the subtitle file next to a clean cwd so odd characters in paths can't break the filter.
        shutil.copy(ass, Path(td) / "c.ass")
        vf = "ass=c.ass" + (f":fontsdir='{esc_path(Path(fontsdir).resolve())}'" if fontsdir else "")
        brand = [value for value in (channel_name, subscriber_text) if value]
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", video]
        if logo:
            cmd += ["-loop", "1", "-i", str(Path(logo).resolve())]
        if brand:
            text = "  ·  ".join(brand)
            (Path(td) / "brand.txt").write_text(text.replace("\r", " ").replace("\n", " "), encoding="utf-8")
            fontfile = (Path(fontsdir) / "Inter-SemiBold.ttf") if fontsdir else None
            font_opt = f":fontfile='{esc_path(fontfile.resolve())}'" if fontfile and fontfile.is_file() else ""
            vf += (f",drawbox=x=24:y=h-112:w=iw-48:h=82:color=black@0.52:t=fill"
                   f",drawtext=textfile='brand.txt'{font_opt}:fontsize=30:fontcolor=white:"
                   "x=48:y=h-86:box=0")
        if logo:
            cmd += ["-filter_complex", f"[0:v]{vf}[base];[1:v]scale=64:64[brandlogo];"
                    "[base][brandlogo]overlay=main_w-overlay_w-32:main_h-overlay_h-121:shortest=1[vout]",
                    "-map", "[vout]", "-map", "0:a?", "-shortest"]
        else:
            cmd += ["-vf", vf]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-c:a", "copy", "-movflags", "+faststart", out]
        run(cmd, cwd=td)
    return str(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video"); ap.add_argument("ass"); ap.add_argument("out")
    ap.add_argument("--fontsdir", help="folder with .ttf/.otf fonts used by the caption style")
    ap.add_argument("--channel-name")
    ap.add_argument("--subscriber-text")
    ap.add_argument("--logo")
    a = ap.parse_args()
    print(burn(a.video, a.ass, a.out, a.fontsdir, a.channel_name, a.subscriber_text, a.logo))
