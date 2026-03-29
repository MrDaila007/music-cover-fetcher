@echo off
REM Run music_cover_fetcher with venv
REM Usage: run.bat [arguments...]
REM Examples:
REM   run.bat C:\Music --tag
REM   run.bat C:\Music -i
REM   run.bat C:\Music --strip-covers

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe music_cover_fetcher.py %*
