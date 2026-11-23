@echo off
rem StreamGet Recorder - Windows single-file exe build script
cd /d %~dp0

if not exist panel\package.json (
    echo [ERROR] panel directory not found.
    pause
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found. Install Node.js first.
    pause
    exit /b 1
)

echo [INFO] Building web panel...
pushd panel
call npm install
if errorlevel 1 (
    popd
    pause
    exit /b 1
)
call npm run build
if errorlevel 1 (
    popd
    pause
    exit /b 1
)
popd

if not exist panel\out (
    echo [ERROR] panel build produced no output.
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
