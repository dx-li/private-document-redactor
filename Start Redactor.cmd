@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run Setup.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" redactor.py
if errorlevel 1 pause
