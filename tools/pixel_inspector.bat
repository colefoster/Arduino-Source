@echo off
cd /d "%~dp0\.."
python tools\pixel_inspector.py %*
pause
