# StreamCarnia Desktop

A native Windows desktop build of StreamCarnia, sitting alongside the
existing `frontend/` (React + Vite) and `backend/` (FastAPI) web app in
this repo. **Neither of those was modified** — this app imports the
existing `backend/services` and `backend/models` code directly (same
yt-dlp integration, same filename sanitizer, same FFmpeg detection, same
SQLite history schema) instead of duplicating it. Only `backend/app_settings.py`,
`backend/main.py`, `backend/api/`, and FastAPI/uvicorn/websockets are
unused here — everything else is shared.

No React, Vite, FastAPI, `localhost`, Render, or Vercel is involved. It's
a plain PySide6 desktop app that calls yt-dlp/FFmpeg directly.

```
StreamCarnia.exe
  -> Download Stream -> Paste YouTube URL -> Analyze -> video info + qualities
  -> Select quality -> Download -> real-time progress -> FFmpeg merge
  -> Completed -> Open File / Open Folder
  -> Auto Clippr -> detect highlights -> render captioned shorts
```

## Project layout

```
desktop/
├── main.py                  Entry point
├── requirements.txt
├── StreamCarnia.spec        PyInstaller build spec (one-folder)
├── build_windows.bat        Windows build script
├── assets/
│   ├── icon.ico             App/exe icon (generated from frontend/public/favicon.png)
│   └── logo.png             In-app logo
├── core/                    Non-GUI application logic
│   ├── paths.py             Dev vs. frozen resource-path resolution
│   ├── settings_store.py    Desktop settings (JSON, per-user app-data dir)
│   ├── cookies.py           Browser cookie export -> cookies.txt for yt-dlp
│   └── queue_manager.py     Download queue orchestration (QThreadPool)
├── workers/                 Background tasks (never block the GUI thread)
│   ├── signals.py
│   ├── analyze_worker.py    Wraps backend.services.ytdlp_service.analyze_url
│   └── download_worker.py   Wraps backend.services.ytdlp_service.download_video
└── ui/                       PySide6 GUI, no downloader logic
    ├── theme.py              Centralized QSS/theme system
    ├── main_window.py
    ├── pages/                 Download Stream / Auto Clippr / Queue / History / Settings
    └── widgets/               Sidebar, video info card, quality list, etc.
desktop/services/clipper/      Local highlight detection/edit/caption pipeline
```

## What's reused vs. new

Reused unchanged, via direct import (no copy/paste, no forked logic):
- `backend/services/ytdlp_service.py` — analysis, quality-option building,
  format selectors, the actual download + progress hooks
- `backend/services/history_store.py` — same SQLite schema as the web app
- `backend/services/ffmpeg_service.py`, `backend/utils/system.py` — FFmpeg
  detection, disk-space checks
- `backend/utils/filename.py` — the same `"Channel - Title [quality]"`
  sanitized filename scheme
- `backend/models/schemas.py` — `DownloadItem`, `FormatOption`,
  `AnalyzeResponse`, `HistoryEntry`, `DownloadStage`, etc.

New for desktop (not applicable to the web app):
- Direct-to-folder downloads (no browser "save" step / staging + fetch)
- `core/queue_manager.py` + `workers/download_worker.py` — ports the
  orchestration in `backend/services/download_manager.py` from
  asyncio/WebSockets to Qt signals/QThreadPool
- `core/cookies.py` — local browser cookie extraction (Brave/Chrome/Edge/
  Firefox) via yt-dlp's own cookie-jar extractor, materialized to a temp
  `cookies.txt` and handed to the existing `cookies_path` parameter
- PySide6 GUI, `core/settings_store.py` (desktop-specific settings)

## Run in development

From the **project root** (the folder containing `backend/`, `frontend/`,
and `desktop/`):

```bash
cd desktop
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

This imports `backend/` from its existing location — no need to install
the backend's own `requirements.txt` (FastAPI/uvicorn aren't needed).

## Build the .exe (Windows)

```bash
cd desktop
pip install -r requirements.txt
build_windows.bat
```

This runs `pyinstaller StreamCarnia.spec --noconfirm` and produces the
one-folder build (the recommended, most reliable build type):

```
dist/StreamCarnia/StreamCarnia.exe
```

The spec bundles:
- `assets/` (icon, logo)
- `backend/bin/ffmpeg.exe` (the same FFmpeg already checked into this repo,
  copied to `dist/StreamCarnia/bin/ffmpeg.exe`)
- `backend/` itself (as a normal Python package dependency, discovered via
  PyInstaller's static import analysis — nothing is hand-copied)
- yt-dlp's extractors and cookie-decryption modules (`collect_submodules`)

A single-file build is also possible (see the commented-out block at the
bottom of `build_windows.bat`), but one-folder is the default because
PyInstaller one-file builds self-extract to a temp directory on every
launch, which is slower and less reliable for an app this size (yt-dlp +
FFmpeg + Qt).

To produce it explicitly:
```bash
pyinstaller main.py --onefile --windowed --name StreamCarnia ^
    --distpath dist\StreamCarnia_onefile --icon assets\icon.ico ^
    --add-data "assets;assets" --add-binary "..\backend\bin\ffmpeg.exe;bin" ^
    --paths ".." --collect-submodules yt_dlp.extractor --collect-data yt_dlp ^
    --hidden-import yt_dlp.cookies
```

## End-user requirements

**None.** The built `.exe` needs no separately installed Python, Node.js,
FFmpeg, or yt-dlp — all are bundled or vendored into the PyInstaller
output. Per-user data (settings, SQLite history, logs) is written to
`%APPDATA%\StreamCarnia\`, not the install folder, so it works fine from
`Program Files` or any read-only location.

## Features carried over from the web app

- YouTube videos, completed livestreams/VODs
- 1080p / 1440p / 1440p60 / 2160p / 2160p60 (when the source offers them)
- Separate video/audio streams merged via FFmpeg, no forced re-encode
- Real-time progress (percent, speed, ETA) via yt-dlp progress hooks
- Download cancellation, download queue (concurrent downloads configurable),
  download history
- Settings: default download directory, container preference, concurrency
- Cookie/auth support: **file** (existing behavior) and **browser**
  (Brave/Chrome/Edge/Firefox — new for desktop, since the web app can't
  read a user's local browser profile). Cookie contents are never logged.

## Auto Clippr

Auto Clippr is a separate desktop workflow for archived stream/VOD URLs. It
detects audio-energy highlights, retrieves selected source ranges, creates
vertical or landscape layouts, transcribes locally, and burns animated
captions. Choose clip count, layout, caption style/language, optional pan and
zoom, facecam bounds for stacked layout, and optional logo/name/subscriber
text for a lower third. Subscriber text is entered by the user and is not
fetched from the channel. Outputs are saved under
`<download folder>/StreamCarnia Clips/<job timestamp>/` with a job log,
candidate metadata, clip metadata, caption sidecars, and intermediate files.

Auto Clippr supports archived VODs. Version 1.0.1 adds an opt-in Live Auto
Clipper workflow that records rolling stream segments, detects audio highlights,
and sends selected moments through the existing portrait/caption pipeline.
Live monitoring, chat analysis, and upload scheduling run outside the main UI
process. YouTube chat is optional; Gemini metadata and YouTube uploads require
their respective credentials. The Live transcription selector offers Small,
Medium, and Large-v3 models; a selected model may download into the user's
model cache on first use. Transcription and video rendering can use substantial
CPU, memory, disk space, and time. FFmpeg must include the `ass` filter
(`libass`). Missing clipping dependencies are reported without changing
regular stream downloads.

The `desktop/services/clipper/` scripts are the local application adaptation
of the user-provided `livestream-clipper.skill` pipeline; the skill archive is
not loaded at runtime.

## Desktop-specific UX

- **Download-location prompt.** Clicking "Download" opens a native folder
  picker so you confirm (or change) exactly where that file goes, instead
  of silently writing to a fixed folder every time. The chosen folder also
  becomes the new default shown in Settings.
- **No stray folders in your downloads.** In-progress files are staged in
  the OS temp directory (not inside your download folder) and moved into
  place only once complete, so nothing like a `.streamcarnia_incomplete`
  folder is ever left behind next to your files.
- **Bundled brand typography.** Inter (body) and Space Grotesk (headings/
  brand) — the same font pairing the web app uses — are bundled as actual
  font files and loaded at startup, so the UI renders with real weight and
  hierarchy instead of falling back to a generic system font.
- **Real depth.** Since Qt style sheets have no `box-shadow` support,
  cards, queue/history rows, and toasts use actual `QGraphicsDropShadowEffect`
  drop shadows (see `ui/effects.py`) for genuine elevation instead of flat
  panels.
- **App-level watermark / attribution.** "© Aditya Suresh" appears in the
  sidebar footer and in a full About section in Settings, and the compiled
  `.exe` carries `CompanyName`/`LegalCopyright`/`ProductName` metadata
  (see `version_info.txt`, wired into `StreamCarnia.spec`) so it shows
  under the file's Properties → Details in Windows Explorer. This brands
  the *application*; it does not overlay a watermark onto downloaded video
  content, since that content isn't yours to alter and doing so would
  mean re-encoding it (which the "don't downgrade quality/re-encode"
  requirement rules out anyway).

## Known limitations

- **Soft cancellation for in-flight file writes.** Cancelling raises
  `yt_dlp.utils.DownloadCancelled` inside the next progress-hook callback
  (the same mechanism yt-dlp recommends), so it stops promptly on the next
  hook tick rather than instantly — matching the original web app's
  cancel semantics. Partial files are written to a per-job staging folder
  inside your download directory and cleaned up on cancel/failure.
- **YouTube JS-challenge edge cases.** Standard extraction needs no
  external JS runtime (yt-dlp ships its own interpreter), so no runtime is
  bundled. If YouTube rolls out a signature challenge that specifically
  requires an external engine like Deno, yt-dlp will report that in the
  error message; installing Deno and adding it to `PATH` is picked up
  automatically since PATH lookup happens at call time, no rebuild needed.
- **Single-file build startup time.** Not produced by default — see above.
- **macOS/Linux.** The spec and `find_ffmpeg`/`app_data_dir` logic are
  cross-platform-aware, but packaging is Windows-first per the request;
  building on macOS/Linux would need a platform build script and a
  non-`.exe` bundled `ffmpeg` binary (not included in this repo).
