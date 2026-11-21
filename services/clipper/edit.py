#!/usr/bin/env python3
"""Cut, tighten, reframe and loudness-normalise a clip with ffmpeg.

Order matters: captions are generated *after* this step, from the edited
clip, so removing silences here never desyncs them.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from common import no_console_kwargs, parse_time, probe, run

VERTICAL = (1080, 1920)
LANDSCAPE = (1920, 1080)
SQUARE = (1080, 1080)


def detect_silences(path, noise_db=-35, min_dur=0.6):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af",
                        f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
                       capture_output=True, text=True, **no_console_kwargs())
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    sil = list(zip(starts, ends + [None] * (len(starts) - len(ends))))
    return sil


def keep_segments(silences, duration, pad=0.15, min_seg=0.3):
    """Invert silences into segments to keep, leaving `pad` of breathing room."""
    keep, cursor = [], 0.0
    for s, e in silences:
        e = duration if e is None else e
        a, b = cursor, min(duration, s + pad)
        if b - a >= min_seg:
            keep.append([a, b])
        cursor = max(cursor, e - pad)
    if duration - cursor >= min_seg:
        keep.append([cursor, duration])
    merged = []
    for a, b in keep:
        if merged and a - merged[-1][1] < 0.05:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return merged


def estimate_focus_x(path, every=1.0):
    """Median horizontal face position (0..1) so the vertical crop follows the streamer."""
    try:
        import cv2
    except ImportError:
        print("opencv not installed; using centre crop (pip install opencv-python-headless)", file=sys.stderr)
        return 0.5
    cap = cv2.VideoCapture(str(path))
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    xs, t = [], 0.0
    dur = probe(path)["duration"]
    while t < dur:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = det.detectMultiScale(gray, 1.2, 5, minSize=(frame.shape[1] // 20,) * 2)
        if len(faces):
            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            xs.append((x + w / 2) / frame.shape[1])
        t += every
    cap.release()
    if not xs:
        return 0.5
    xs.sort()
    return xs[len(xs) // 2]


def layout_filter(layout, focus_x=0.5, facecam=None, stack_facecam_percent=35):
    """Return a filtergraph fragment from [in] to [vout], and the output size."""
    W, H = VERTICAL
    if layout == "square":
        w, h = SQUARE
        return (f"[in]crop=w='min(iw,ih)':h='min(iw,ih)':x='(iw-ow)/2':y='(ih-oh)/2',"
                f"scale={w}:{h},setsar=1[vout]", SQUARE)
    if layout == "center":
        fx = min(max(focus_x, 0.0), 1.0)
        return (f"[in]crop=w='min(iw,ih*9/16)':h=ih:x='(iw-ow)*{fx:.3f}':y=0,scale={W}:{H},setsar=1[vout]", VERTICAL)
    if layout == "blur":
        return (f"[in]split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"boxblur=30:3,eq=brightness=-0.08[bg];[b]scale={W}:-2[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[vout]", VERTICAL)
    if layout == "stack":
        if not facecam:
            raise SystemExit("--layout stack needs --facecam x,y,w,h (fractions of the frame, e.g. 0.75,0.7,0.25,0.3)")
        fx, fy, fw, fh = facecam
        top_height = int(H * min(50, max(20, int(stack_facecam_percent))) / 100)
        bottom_height = H - top_height
        return (f"[in]split[g][f];"
                f"[f]crop=w=iw*{fw}:h=ih*{fh}:x=iw*{fx}:y=ih,scale={W}:{top_height}:force_original_aspect_ratio=increase,crop={W}:{top_height}[top];"
                f"[g]crop=w='min(iw,ih*{W}/{bottom_height})':h=ih:x='(iw-ow)/2':y=0,scale={W}:{bottom_height}[bot];"
                f"[top][bot]vstack,setsar=1[vout]", VERTICAL)
    if layout == "landscape":
        w, h = LANDSCAPE
        return (f"[in]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1[vout]", LANDSCAPE)
    raise SystemExit(f"unknown layout {layout}")


def edit(src, dst, start=None, end=None, layout="blur", trim_silence=True, track_face=False,
         focus_x=0.5, facecam=None, loudnorm=True, silence_db=-35, min_silence=0.6,
         peak_zoom=False, stack_facecam_percent=35):
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP") or None) as td:
        work = src
        if start is not None and end is not None:  # precise cut (re-encode so it's frame-accurate)
            work = Path(td) / "cut.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", src, "-t", f"{end - start:.3f}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", work])
        info = probe(work)
        if track_face and layout == "center":
            focus_x = estimate_focus_x(work)
            print(f"face focus x = {focus_x:.2f}", file=sys.stderr)

        segs = None
        if trim_silence and info["has_audio"]:
            segs = keep_segments(detect_silences(work, silence_db, min_silence), info["duration"])
            kept = sum(b - a for a, b in segs)
            if not segs or kept > info["duration"] - 0.4 or kept < 3:
                segs = None  # nothing worth cutting, or it would gut the clip

        lay, size = layout_filter(layout, focus_x, facecam, stack_facecam_percent)
        g = []
        if segs:
            for i, (a, b) in enumerate(segs):
                g.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}];"
                         f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
            cat = "".join(f"[v{i}][a{i}]" for i in range(len(segs)))
            g.append(f"{cat}concat=n={len(segs)}:v=1:a=1[in][ain]")
            ain = "[ain]"
        else:
            g.append("[0:v]null[in]")
            ain = "[0:a]"
        if peak_zoom:
            # Each chosen segment is centred on a detected highlight; apply a
            # bounded, smooth crop movement before formatting the layout.
            g.append(f"[in]zoompan=z='1+0.06*(0.5-0.5*cos(2*PI*on/90))':"
                     f"x='iw/2-(iw/zoom/2)+sin(on/50)*iw*0.01':"
                     f"y='ih/2-(ih/zoom/2)':d=1:s={info['width']}x{info['height']}:fps=30[z]")
            lay = lay.replace("[in]", "[z]")
        g.append(lay)
        if info["has_audio"]:
            af = "loudnorm=I=-14:TP=-1.5:LRA=11" if loudnorm else "anull"
            g.append(f"{ain}{af}[aout]")
        # FFmpeg 9 removed -filter_complex_script; passing the graph as an
        # argv value works across current and older FFmpeg builds (no shell).
        graph = ";".join(g)
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", work, "-filter_complex", graph, "-map", "[vout]"]
        if info["has_audio"]:
            cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", dst]
        run(cmd)
    return {"path": str(dst), "width": size[0], "height": size[1], "trimmed": bool(segs)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--layout", choices=["blur", "center", "stack", "landscape", "square"], default="blur")
    ap.add_argument("--facecam", help="x,y,w,h as fractions of the frame (for --layout stack)")
    ap.add_argument("--stack-facecam-percent", type=int, default=35)
    ap.add_argument("--focus-x", type=float, default=0.5)
    ap.add_argument("--track-face", action="store_true")
    ap.add_argument("--peak-zoom", action="store_true", help="add gentle zoom movement to the selected highlight")
    ap.add_argument("--no-trim", action="store_true", help="keep silences")
    ap.add_argument("--no-loudnorm", action="store_true")
    a = ap.parse_args()
    fc = tuple(float(x) for x in a.facecam.split(",")) if a.facecam else None
    r = edit(a.src, a.dst, parse_time(a.start) if a.start else None, parse_time(a.end) if a.end else None,
             a.layout, not a.no_trim, a.track_face, a.focus_x, fc, not a.no_loudnorm,
             peak_zoom=a.peak_zoom, stack_facecam_percent=a.stack_facecam_percent)
    print(r)


if __name__ == "__main__":
    main()
