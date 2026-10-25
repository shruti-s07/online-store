@echo off
title Online Store API Server
cd /d "%~dp0"
if not exist .venv (
    echo Virtual environment not found. Running start.bat to set up...
    call start.bat
    exit /b
)
call .venv\Scripts\activate.bat
python store.py api
pause