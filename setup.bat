@echo off
rem One-time setup for JobStream on Windows. Double-click this file, or run it from Command Prompt.
cd /d "%~dp0"
echo.
echo === JobStream setup ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH", then run this again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment...
  python -m venv .venv
  if errorlevel 1 goto :failed
)
call ".venv\Scripts\activate.bat"
echo Installing JobStream and its libraries (a few minutes)...
python -m pip install --upgrade pip >nul
pip install -e ".[apply]"
if errorlevel 1 goto :failed
echo Installing the browser used to fill application forms...
playwright install chromium
if errorlevel 1 goto :failed
jobstream init
echo.
echo Setup finished. Next:
echo   1. Put your Claude API key in the .env file:   notepad .env
echo   2. Fill in config\profile.yaml and config\cv_master.yaml
echo   3. Double-click JobStream.bat and run:   jobstream doctor
echo.
pause
exit /b 0
:failed
echo.
echo Setup stopped because a step failed. Copy the messages above and ask for help.
pause
exit /b 1
