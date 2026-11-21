#!/usr/bin/env python3
"""Word-level transcription with faster-whisper -> words.json.

Run this on the *edited* clip so caption times match the final video.
"""
import argparse
from functools import lru_cache
import json
import sys
import time


@lru_cache(maxsize=1)
def _load_model(model, device, compute_type):
    from faster_whisper import WhisperModel
    return WhisperModel(model, device=device, compute_type=compute_type)


def transcribe(path, model="small", lang=None, device="auto", compute_type=None, on_progress=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("faster-whisper missing: pip install faster-whisper")
    if compute_type is None:
        compute_type = "int8" if device in ("cpu", "auto") else "float16"

    def run_on(selected_device, selected_compute_type):
        if on_progress:
            on_progress(0.0)
        started = time.monotonic()
        m = _load_model(model, selected_device, selected_compute_type)
        if on_progress:
            on_progress(0.02)
        segs, info = m.transcribe(str(path), word_timestamps=True, vad_filter=True,
                                  language=lang, beam_size=5)
        words = []
        last_report = 0.0
        duration = max(float(getattr(info, "duration", 0.0) or 0.0), 0.0)
        for s in segs:
            for w in s.words or []:
                t = w.word.strip()
                if t:
                    words.append({"w": t, "s": round(w.start, 3), "e": round(w.end, 3)})
            now = time.monotonic()
            if on_progress and (now - last_report >= 1.5 or (duration and s.end >= duration)):
                last_report = now
                # Keep model initialization and Whisper's first decode visible;
                # segment timestamps provide a useful estimate once decoding starts.
                fraction = 0.03 + 0.97 * min(1.0, float(s.end) / duration) if duration else min(
                    0.95, 0.03 + (now - started) / max(120.0, now - started + 30.0))
                on_progress(fraction)
        if on_progress:
            on_progress(1.0)
        return {"language": info.language, "text": " ".join(w["w"] for w in words), "words": words}

    try:
        return run_on(device, compute_type)
    except RuntimeError as exc:
        # CTranslate2 may select CUDA automatically when a GPU is present, even
        # when its CUDA 12/cuBLAS runtime is not installed. Retry the same job
        # on CPU so caption generation remains available on those machines.
        cuda_error = any(term in str(exc).lower() for term in
                         ("cublas", "cudnn", "cuda", "cublas64_12.dll"))
        if device not in {"auto", "cuda"} or not cuda_error:
            raise
        print(f"[clipper] CUDA transcription unavailable ({exc}); retrying captions on CPU.",
              file=sys.stderr, flush=True)
        return run_on("cpu", "int8")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("media")
    ap.add_argument("--out", default="words.json")
    ap.add_argument("--model", default="small", help="tiny/base/small/medium/large-v3")
    ap.add_argument("--lang", help="e.g. en, hi (default: auto-detect)")
    ap.add_argument("--device", default="auto")
    a = ap.parse_args()
    r = transcribe(a.media, a.model, a.lang, a.device)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    print(a.out)


if __name__ == "__main__":
    main()
