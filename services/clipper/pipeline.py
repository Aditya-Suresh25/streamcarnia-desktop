#!/usr/bin/env python3
"""End-to-end: livestream URL (or local file) -> captioned, edited short clips.

  detect   audio-only download -> find highlight moments (audio spikes + chat)
  fetch    download only those sections of the video (not the whole stream)
  edit     trim dead air, reframe to 9:16, normalise loudness
  caption  word-level transcription -> animated captions burned in
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import burn as burn_mod
import captions as cap_mod
import edit as edit_mod
import fetch
import highlights
from common import fmt_time, parse_time, probe

sys.stdout.reconfigure(line_buffering=True)


def log(*a):
    print("[clipper]", *a, file=sys.stderr, flush=True)


class OutputStorageError(RuntimeError):
    """The job cannot safely continue because an output artifact could not be saved."""


def progress(stage, clip=0, total=0):
    print("@@SC_PROGRESS@@" + json.dumps({"stage": stage, "clip": clip, "total": total}), flush=True)


def write_json(path: Path, value) -> None:
    """Atomically write a JSON artifact in UTF-8 regardless of Windows locale."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        raise OutputStorageError(f"Could not save {path}: {exc}") from exc


def write_text(path: Path, value: str) -> None:
    try:
        path.write_text(value, encoding="utf-8")
    except OSError as exc:
        raise OutputStorageError(f"Could not save {path}: {exc}") from exc


def write_summary(out: Path, summary: dict) -> None:
    write_json(out / "job_summary.json", summary)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="YouTube URL or local video/audio file")
    ap.add_argument("--out", default="clips")
    ap.add_argument("--top", type=int, default=5, help="how many clips to make")
    ap.add_argument("--ranges", help='skip detection: "1:02:10-1:03:00,2:15:00-2:15:45"')
    ap.add_argument("--only", help="comma list of candidate ranks to render, e.g. 1,3")
    ap.add_argument("--detect-only", action="store_true", help="stop after writing candidates.json")
    ap.add_argument("--chat", action="store_true", help="use chat replay as a highlight signal (archived streams)")
    ap.add_argument("--live-minutes", type=float, default=30, help="if the stream is live now, record this long first")
    ap.add_argument("--pre", type=float, default=20); ap.add_argument("--post", type=float, default=25)
    ap.add_argument("--min-len", type=float, default=20); ap.add_argument("--max-len", type=float, default=60)
    ap.add_argument("--min-gap", type=float, default=90, help="min seconds between detected clips")
    ap.add_argument("--layout", choices=["blur", "center", "stack", "landscape"], default="blur")
    ap.add_argument("--facecam"); ap.add_argument("--track-face", action="store_true")
    ap.add_argument("--no-trim", action="store_true")
    ap.add_argument("--style", choices=list(cap_mod.STYLES), default="pop")
    ap.add_argument("--font", default="Inter"); ap.add_argument("--fontsdir")
    ap.add_argument("--highlight", default="#FFD400"); ap.add_argument("--color", default="#FFFFFF")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--model", default="small"); ap.add_argument("--lang")
    ap.add_argument("--live-hinglish", action="store_true",
                    help="use live-only Devanagari-to-Hinglish caption conversion")
    ap.add_argument("--max-height", type=int, default=1080)
    ap.add_argument("--cookies-from-browser", dest="cookies")
    ap.add_argument("--cookies", help="Netscape cookies file path")
    ap.add_argument("--peak-zoom", action="store_true", help="gentle pan/zoom inside selected highlight segments")
    ap.add_argument("--channel-name")
    ap.add_argument("--subscriber-text")
    ap.add_argument("--logo", help="optional PNG/JPG logo")
    ap.add_argument("--archived-only", action="store_true", help="reject active livestreams")
    a = ap.parse_args()

    out = Path(a.out); work = out / "work"; work.mkdir(parents=True, exist_ok=True)
    is_url = a.source.startswith("http")
    local = None if is_url else a.source
    chat_file = None
    progress("source")

    # 1. get something to analyse -------------------------------------------------
    if is_url:
        meta = fetch.info(a.source, a.cookies)
        log("source:", meta["title"], f"({meta['live_status']})")
        if meta["is_live"]:
            if a.archived_only:
                raise SystemExit("Active livestream capture isn't enabled in this StreamCarnia version. Use an archived VOD.")
            log(f"stream is live: recording {a.live_minutes:g} min first")
            local = fetch.live(a.source, work / "live.ts", a.live_minutes * 60, a.max_height, a.cookies)
            analyse = local
        else:
            analyse = fetch.audio(a.source, work, a.cookies) if not a.ranges else None
            if a.chat and not a.ranges:
                chat_file = fetch.chat(a.source, work, a.cookies)
                log("chat replay:", chat_file or "not available")
    else:
        analyse = local

    # 2. choose moments --------------------------------------------------------
    if a.ranges:
        cands = []
        for i, r in enumerate(a.ranges.split(","), 1):
            s, e = (parse_time(x) for x in r.split("-"))
            cands.append({"rank": i, "start": s, "end": e, "score": None, "reasons": ["manual"],
                          "label": f"{fmt_time(s)}-{fmt_time(e)}"})
    else:
        log("detecting highlights ...")
        cands = highlights.find(analyse, chat_file, a.top, a.pre, a.post, a.min_len, a.max_len, a.min_gap)
    write_json(out / "candidates.json", cands)
    for c in cands:
        log(f"#{c['rank']} {c['label']} score={c['score']} {','.join(c['reasons'])}")
    if a.detect_only:
        print(out / "candidates.json"); return
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        cands = [c for c in cands if c["rank"] in keep]
    cands = cands[: a.top] if not a.only and not a.ranges else cands
    progress("ready", total=len(cands))

    # 3-5. per clip: fetch -> edit -> caption -> burn --------------------------
    facecam = tuple(float(x) for x in a.facecam.split(",")) if a.facecam else None
    results = []
    failures = []
    summary = {"status": "running", "requested": len(cands), "completed": 0,
               "succeeded": 0, "failed": [], "output_dir": str(out.resolve())}
    write_json(out / "clips.json", results)
    write_summary(out, summary)
    for clip_index, c in enumerate(cands, 1):
        n = f"{c['rank']:02d}"
        log(f"--- clip {n}: {c['label']}")
        stage = "download"
        try:
            if is_url and not meta["is_live"]:
                progress("fetch", clip_index, len(cands))
                stage = "download"
                raw = fetch.section(a.source, c["start"], c["end"], work / f"raw_{n}.mp4", a.max_height, a.cookies)
                progress("edit", clip_index, len(cands))
                stage = "edit/probe"
                e = edit_mod.edit(raw, work / f"edit_{n}.mp4", layout=a.layout, trim_silence=not a.no_trim,
                                  track_face=a.track_face, facecam=facecam, peak_zoom=a.peak_zoom)
            else:
                progress("edit", clip_index, len(cands))
                stage = "edit/probe"
                e = edit_mod.edit(local, work / f"edit_{n}.mp4", c["start"], c["end"], a.layout,
                                  not a.no_trim, a.track_face, facecam=facecam, peak_zoom=a.peak_zoom)
            final = out / f"clip_{n}.mp4"
            stage = "edit/probe"
            clip_duration = round(probe(e["path"])["duration"], 1)
            entry = {"rank": c["rank"], "source_start": c["start"], "source_end": c["end"], "score": c["score"],
                     "reasons": c["reasons"], "duration": clip_duration, "file": str(final)}
            if a.no_captions:
                if a.channel_name or a.subscriber_text or a.logo:
                    progress("burn", clip_index, len(cands))
                    blank_ass, _ = cap_mod.build([], e["width"], e["height"], a.style, a.font)
                    ass_path = work / f"cap_{n}.ass"
                    write_text(ass_path, blank_ass)
                    stage = "render"
                    burn_mod.burn(e["path"], ass_path, final, a.fontsdir, a.channel_name,
                                  a.subscriber_text, a.logo)
                else:
                    Path(e["path"]).replace(final)
            else:
                progress("transcribe", clip_index, len(cands))
                stage = "transcription"
                from transcribe import transcribe
                tr = transcribe(e["path"], a.model, a.lang)
                tr = dict(tr)
                tr["words"] = [dict(word) for word in tr.get("words", [])]
                # Save source-language transcription first so a later
                # romanization/render error never discards the transcript.
                write_json(work / f"words_{n}.json", tr)
                caption_w = tr["words"]
                if any("\u0900" <= char <= "\u097f" for word in caption_w for char in str(word.get("w", ""))):
                    progress("romanize", clip_index, len(cands))
                    stage = "romanization"
                    if a.live_hinglish:
                        from live_hinglish import caption_words
                    else:
                        from romanize import caption_words
                    caption_w = caption_words(caption_w)
                caption_text = " ".join(str(word.get("w", "")) for word in caption_w).strip()
                tr["caption_words"] = caption_w
                tr["caption_text"] = caption_text
                write_json(work / f"words_{n}.json", tr)
                if not caption_w:
                    log("no speech detected; skipping captions for this clip")
                    if a.channel_name or a.subscriber_text or a.logo:
                        progress("burn", clip_index, len(cands))
                        blank_ass, _ = cap_mod.build([], e["width"], e["height"], a.style, a.font)
                        ass_path = work / f"cap_{n}.ass"
                        write_text(ass_path, blank_ass)
                        stage = "render"
                        burn_mod.burn(e["path"], ass_path, final, a.fontsdir, a.channel_name,
                                      a.subscriber_text, a.logo)
                    else:
                        Path(e["path"]).replace(final)
                else:
                    ass, chunks = cap_mod.build(caption_w, e["width"], e["height"], a.style, a.font,
                                                color=a.color, highlight=a.highlight)
                    ass_path = work / f"cap_{n}.ass"
                    write_text(ass_path, ass)
                    write_text(out / f"clip_{n}.srt", cap_mod.build_srt(chunks))
                    progress("burn", clip_index, len(cands))
                    stage = "render"
                    burn_mod.burn(e["path"], ass_path, final, a.fontsdir, a.channel_name,
                                  a.subscriber_text, a.logo)
                entry["transcript"] = tr.get("text", "")
                entry["caption_transcript"] = caption_text
                entry["caption_words"] = caption_w
            results.append(entry)
            summary["succeeded"] = len(results)
            summary["completed"] = clip_index
            write_json(out / "clips.json", results)
            write_summary(out, summary)
            log("wrote", final)
            progress("done", clip_index, len(cands))
        except OutputStorageError:
            summary["status"] = "partial" if results else "failed"
            summary["fatal_error"] = "Output storage failed; job stopped."
            try:
                write_summary(out, summary)
            except OutputStorageError:
                pass
            raise
        except Exception as exc:  # clip-specific errors are recorded, and the next candidate still runs
            failure = {"rank": c.get("rank"), "clip": n, "stage": stage,
                       "error_type": type(exc).__name__, "message": str(exc)}
            failures.append(failure)
            summary["failed"] = failures
            summary["completed"] = clip_index
            write_summary(out, summary)
            log(f"clip {n} failed at {stage}: {type(exc).__name__}: {exc}")
            traceback.print_exc(file=sys.stderr)
            progress("clip_failed", clip_index, len(cands))
    if not cands:
        progress("done", 0, 0)
    summary["status"] = "partial" if results and failures else ("failed" if failures else "complete")
    summary["failed"] = failures
    summary["succeeded"] = len(results)
    summary["completed"] = len(cands)
    write_json(out / "clips.json", results)
    write_summary(out, summary)
    print(out / "clips.json")
    if failures and not results:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
