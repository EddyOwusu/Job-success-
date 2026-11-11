@echo off
rem Opens a command window ready to use JobStream. (Not named jobstream.bat: Windows would run it instead of the program.)
cd /d "%~dp0"
if not exist ".venv\Scripts\activate.bat" (
  echo JobStream is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
title JobStream
cmd /k "call .venv\Scripts\activate.bat && echo JobStream is ready. Try: jobstream doctor"
