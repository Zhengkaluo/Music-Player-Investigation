@echo off
cd /d "%~dp0"
echo Starting Web Now-Playing display...
py webui\webui_app.py
if errorlevel 1 (
  echo.
  echo Failed to start. Make sure dependencies are installed:
  echo   py -m pip install pywebview Pillow
  pause
)
