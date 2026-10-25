@echo off
title Online Store Desktop GUI
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python store.py ui
pause
