#!/usr/bin/env python3
"""Find clip-worthy moments in a livestream using audio energy spikes and
(optionally) chat activity from a yt-dlp live_chat.json replay.

Why these signals: streamers get loud when something funny/hype happens, and
chat floods at the same moments. Neither needs a transcript, so detection is
fast even on multi-hour streams (run it on the audio-only download).
"""
import argparse
import json
import subprocess
import sys

import numpy as np

from common import fmt_time, no_console_kwargs, probe

SR = 16000


def audio_db_per_second(path):
    """Per-second RMS loudness in dB, streamed so long files stay cheap."""
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, **no_console_kwargs())
    out, leftover = [], b""
    block = SR * 2 * 60
    while True:
        data = p.stdout.read(block)
        if not data:
            break
        data = leftover + data
        usable = (len(data) // (SR * 2)) * SR * 2
        leftover = data[usable:]
        if usable:
            x = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768.0
            x = x.reshape(-1, SR)
            rms = np.sqrt((x ** 2).mean(axis=1) + 1e-10)
            out.append(20 * np.log10(rms))
    p.wait()
    return np.concatenate(out) if out else np.zeros(0)


def chat_per_second(path, n):
    """Messages per second from a yt-dlp live_chat.json (JSON lines)."""
    counts = np.zeros(n, dtype=np.float32)
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)["replayChatItemAction"]
                t = int(d["videoOffsetTimeMsec"]) // 1000
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if 0 <= t < n:
                counts[t] += 1
    return counts


def smooth(x, w):
    if w <= 1:
        return x
    return np.convolve(x, np.ones(w) / w, mode="same")


def spike_z(x, baseline_s=120):
    """How far above its own recent baseline each second is (robust z-score)."""
    base = smooth(x, baseline_s)
    d = x - base
    mad = np.median(np.abs(d - np.median(d))) * 1.4826 + 1e-6
    return d / mad


def snap_to_quiet(db, t, radius=4):
    lo, hi = max(0, int(t) - radius), min(len(db), int(t) + radius + 1)
    return lo + int(np.argmin(db[lo:hi])) if hi > lo else int(t)


def find(path, chat=None, top=8, pre=20, post=25, min_len=20, max_len=60, min_gap=90, skip_start=30):
    db = audio_db_per_second(path)
    n = len(db)
    if n < min_len:
        raise SystemExit(f"media is only {n}s long; nothing to clip")
    z_audio = smooth(spike_z(db), 5)
    score, parts = z_audio.copy(), {"audio": z_audio}
    if chat:
        z_chat = smooth(spike_z(chat_per_second(chat, n), 60), 7)
        score = 0.55 * z_audio + 0.45 * z_chat
        parts["chat"] = z_chat
    score[:skip_start] = -np.inf  # intros are usually setup, not highlights

    picks = []
    for t in np.argsort(-score):
        if not np.isfinite(score[t]) or score[t] <= 0.5:
            break
        if all(abs(int(t) - p) >= min_gap for p in picks):
            picks.append(int(t))
        if len(picks) >= top:
            break

    cands = []
    for rank, t in enumerate(picks, 1):
        s = snap_to_quiet(db, max(0, t - pre))
        e = snap_to_quiet(db, min(n - 1, t + post))
        if e - s < min_len:
            e = min(n, s + min_len)
        if e - s > max_len:
            e = s + max_len
        reasons = [k for k, v in parts.items() if v[t] > 1.0] or ["audio"]
        cands.append({"rank": rank, "start": float(s), "end": float(e), "peak": float(t),
                      "score": round(float(score[t]), 2), "reasons": reasons,
                      "label": f"{fmt_time(s)}-{fmt_time(e)}"})
    return cands


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("media", help="audio or video file")
    ap.add_argument("--chat", help="yt-dlp live_chat.json (optional)")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--pre", type=float, default=20, help="seconds before the peak")
    ap.add_argument("--post", type=float, default=25, help="seconds after the peak")
    ap.add_argument("--min-len", type=float, default=20)
    ap.add_argument("--max-len", type=float, default=60)
    ap.add_argument("--min-gap", type=float, default=90, help="min seconds between clips")
    ap.add_argument("--out", default="candidates.json")
    a = ap.parse_args()
    c = find(a.media, a.chat, a.top, a.pre, a.post, a.min_len, a.max_len, a.min_gap)
    with open(a.out, "w") as f:
        json.dump(c, f, indent=2)
    for x in c:
        print(f"#{x['rank']}  {x['label']:>16}  score={x['score']:<5} {','.join(x['reasons'])}", file=sys.stderr)
    print(a.out)


if __name__ == "__main__":
    main()
