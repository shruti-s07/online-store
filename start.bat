@echo off
setlocal enabledelayedexpansion
title Online Store - One-Click Launcher
cd /d "%~dp0"

echo ======================================================================
echo           haat. Online Store Platform - Starting System
echo ======================================================================
echo.

:: 1. Check if Python is installed
python --version >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python is not installed or not in your system PATH.
    echo Please install Python 3.12 or 3.13 from https://www.python.org/downloads/
    echo During installation, be sure to check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: 2. Check/create virtual environment
if not exist .venv (
    echo [1/4] Creating virtual environment (.venv)...
    python -m venv .venv
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to create .venv virtual environment.
        pause
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    echo [2/4] Installing required dependencies (PySide6, Django, DRF, etc.)...
    echo This may take 1-2 minutes on the first run...
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
) else (
    call .venv\Scripts\activate.bat
)

:: 3. Check/create .env
if not exist .env (
    echo [3/4] Initializing local configuration (.env)...
    copy config\.env.example .env >nul
)

:: 4. Check/seed SQLite database
if not exist online_store.sqlite3 (
    echo [3/4] Setting up database schema and seeding demo store...
    echo Applying database migrations...
    python manage.py migrate --no-input
    echo Seeding Indian marketplace catalog and synthetic history...
    python store.py seed --scale 0.2
    echo Generating product packshots...
    python generate_realistic_photos.py
)

:: 5. Ensure realistic product photos exist
if not exist media\products\ELE-1001\main.png (
    echo Generating realistic product photography...
    python generate_realistic_photos.py
)

:: 6. Launch API server and Desktop GUI
echo.
echo ======================================================================
echo [4/4] Launching haat. Platform:
echo       - Backend API: http://127.0.0.1:8001/api/
echo       - Swagger UI:  http://127.0.0.1:8001/api/docs/
echo       - Desktop App: PySide6 GUI starting...
echo ======================================================================
echo.

start "Online Store Backend API" /min cmd /c "call .venv\Scripts\activate.bat && python store.py api"

:: Brief wait for server socket to open
timeout /t 3 /nobreak >nul

:: Launch Desktop Client
python store.py ui
