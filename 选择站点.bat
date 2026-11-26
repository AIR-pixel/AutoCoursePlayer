@echo off
cd /d "%~dp0"

rem Select which course platform to auto-play (yuketang / chaoxing / zhihuishu)
set "NO_PROXY=localhost,127.0.0.1,::1"
set "no_proxy=localhost,127.0.0.1,::1"

if exist "%~dp0.venv\Scripts\python.exe" (
    set "PY=%~dp0.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

"%PY%" "%~dp0main.py" --site

echo.
echo ================================================
echo Done. Press any key to close this window.
pause >nul
