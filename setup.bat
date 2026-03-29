@echo off
REM Setup virtual environment and install dependencies
REM Usage: setup.bat

echo === Music Cover Fetcher Setup ===

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
) else (
    echo Virtual environment already exists.
)

echo Activating venv and installing dependencies...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -e . -q

echo.
echo === Setup complete ===
echo Run 'run.bat' to use the tool, or activate manually:
echo   .venv\Scripts\activate
echo   python music_cover_fetcher.py --help
pause
