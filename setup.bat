@echo off
rem One-time setup: creates .venv and installs the app.
cd /d "%~dp0"
python -m venv .venv || goto :err
.venv\Scripts\python -m pip install -e ".[dev]" || goto :err
echo.
echo Setup complete. Start the app with run_app.bat
pause
exit /b 0
:err
echo Setup failed. If the error mentions long paths, put this folder somewhere with a shorter path (e.g. C:\elfantasy).
pause
exit /b 1
