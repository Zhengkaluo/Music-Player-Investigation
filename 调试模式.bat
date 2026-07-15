@echo off
cd /d "%~dp0"
set NP_DEBUG=1
echo Starting in DEBUG mode... (right-click the window then choose Inspect)
py webui\webui_app.py
if errorlevel 1 (
  echo.
  echo Failed to start. Make sure dependencies are installed:
  echo   py -m pip install pywebview Pillow
  pause
)
