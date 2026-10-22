@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run Setup.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" setup_local.py --ai
if errorlevel 1 (
    echo Local AI setup did not complete. Manual redaction and OCR still work.
    pause
    exit /b 1
)
echo Local AI is ready. No connection is needed to analyze documents.
pause
