@echo off
title Online Store Desktop Client
cd /d "%~dp0"
if not exist .venv (
    echo Virtual environment not found. Running start.bat to set up...
    call start.bat
    exit /b
)
call .venv\Scripts\activate.bat
python store.py ui
pause