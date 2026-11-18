#!/usr/bin/env python3
"""Word-level transcription with faster-whisper -> words.json.

Run this on the *edited* clip so caption times match the final video.
"""
import argparse
import json
import sys


def transcribe(path, model="small", lang=None, device="auto", compute_type=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("faster-whisper missing: pip install faster-whisper")
    if compute_type is None:
        compute_type = "int8" if device in ("cpu", "auto") else "float16"

    def run_on(selected_device, selected_compute_type):
        m = WhisperModel(model, device=selected_device, compute_type=selected_compute_type)
        segs, info = m.transcribe(str(path), word_timestamps=True, vad_filter=True,
                                  language=lang, beam_size=5)
        words = []
        for s in segs:
            for w in s.words or []:
                t = w.word.strip()
                if t:
                    words.append({"w": t, "s": round(w.start, 3), "e": round(w.end, 3)})
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
