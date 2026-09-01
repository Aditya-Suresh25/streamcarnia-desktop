@echo off
REM ============================================================
REM  StreamCarnia Desktop - Windows build script
REM
REM  Produces the one-folder build (recommended, reliable):
REM      dist\StreamCarnia\StreamCarnia.exe
REM
REM  Run from the desktop\ folder, with the venv from
REM  requirements.txt already installed and activated.
REM ============================================================

setlocal

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo [!] PyInstaller not found. Run: pip install -r requirements.txt
    exit /b 1
)

echo [1/2] Cleaning previous build...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo [2/2] Building one-folder app with PyInstaller...
pyinstaller StreamCarnia.spec --noconfirm
if errorlevel 1 (
    echo [!] Build failed.
    exit /b 1
)

echo.
echo Done. Executable at: dist\StreamCarnia\StreamCarnia.exe
echo.

REM ------------------------------------------------------------
REM  Optional: single-file .exe build (slower to start, since it
REM  self-extracts to a temp folder on every launch). Uncomment
REM  to also produce dist\StreamCarnia_onefile\StreamCarnia.exe:
REM
REM echo Building single-file variant...
REM pyinstaller main.py --onefile --windowed --noconfirm ^
REM     --name StreamCarnia ^
REM     --distpath dist\StreamCarnia_onefile ^
REM     --icon assets\icon.ico ^
REM     --version-file version_info.txt ^
REM     --add-data "assets;assets" ^
REM     --add-binary "..\backend\bin\ffmpeg.exe;bin" ^
REM     --paths ".." ^
REM     --collect-submodules yt_dlp.extractor ^
REM     --collect-data yt_dlp ^
REM     --hidden-import yt_dlp.cookies
REM ------------------------------------------------------------

endlocal
