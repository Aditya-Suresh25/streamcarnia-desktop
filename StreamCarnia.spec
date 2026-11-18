# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for StreamCarnia Desktop.

Produces a one-folder build at dist/StreamCarnia/StreamCarnia.exe that
needs no separately-installed Python, Node.js, FFmpeg, or yt-dlp.

Build with:  build_windows.bat
   (or, from the desktop/ folder:  pyinstaller StreamCarnia.spec --noconfirm)
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

DESKTOP_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = DESKTOP_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
ASSETS_DIR = DESKTOP_DIR / "assets"

FFMPEG_SRC = BACKEND_DIR / "bin" / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")

binaries = []
if FFMPEG_SRC.is_file():
    binaries.append((str(FFMPEG_SRC), "bin"))

datas = [
    (str(ASSETS_DIR), "assets"),
    (str(DESKTOP_DIR / "services" / "clipper"), "services/clipper"),
]
datas += collect_data_files("yt_dlp")

hiddenimports = []
hiddenimports += collect_submodules("yt_dlp.extractor")
hiddenimports += [
    "yt_dlp.cookies",
    "PySide6.QtSvg",
]

# Auto Clippr: transcription runs locally and downloads its Whisper model to
# the user's cache on first use. Include inference package modules/native libs.
for package in ("faster_whisper", "ctranslate2"):
    pkg_datas, pkg_bins, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_bins
    hiddenimports += pkg_hidden

a = Analysis(
    [str(DESKTOP_DIR / "main.py")],
    pathex=[str(DESKTOP_DIR), str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "starlette"],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StreamCarnia",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ASSETS_DIR / "icon.ico"),
    version=str(DESKTOP_DIR / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="StreamCarnia",
)
