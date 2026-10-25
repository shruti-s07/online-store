@echo off
title Online Store API Server
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python store.py api
pause
