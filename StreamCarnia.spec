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

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

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
]
datas += collect_data_files("yt_dlp")

hiddenimports = []
hiddenimports += collect_submodules("yt_dlp.extractor")
hiddenimports += [
    "yt_dlp.cookies",
    "PySide6.QtSvg",
]

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
