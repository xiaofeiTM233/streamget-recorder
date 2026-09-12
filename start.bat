@echo off
rem StreamGet Recorder Panel - Windows launcher
cd /d %~dp0

where uv >nul 2>nul
if errorlevel 1 (
    echo [ERROR] uv not found. Install it first:
    echo         powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo [WARN] ffmpeg not found in PATH. You can set its full path later on the web Settings page.
)

if not exist .venv (
    echo [INFO] First run: installing dependencies...
    uv sync
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

if not exist panel\out (
    echo [INFO] panel\out not found: running in API-only mode.
    echo        To build the web UI: cd panel ^&^& npm install ^&^& npm run build
)

echo [INFO] Starting server. Web UI will open at http://127.0.0.1:8000
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"
uv run python main.py
pause
