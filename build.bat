@echo off
rem StreamGet Recorder - Windows single-file exe build script
cd /d %~dp0

if not exist panel\out (
    echo [ERROR] panel\out not found. Build the frontend first:
    echo         cd panel ^&^& npm install ^&^& npm run build
    pause
    exit /b 1
)

echo [INFO] Syncing build dependencies...
uv sync --group build
if errorlevel 1 (
    pause
    exit /b 1
)

echo [INFO] Running PyInstaller (may take a few minutes)...
uv run pyinstaller recorder.spec --noconfirm
if errorlevel 1 (
    pause
    exit /b 1
)

echo [OK] Build finished: dist\StreamGetRecorder.exe
echo      Put ffmpeg on PATH or set its path on the web Settings page.
echo      Optional: put node.exe under a "node" folder next to the exe for platforms that need it.
pause
