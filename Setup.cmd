@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -m venv .venv
) else (
    python -m venv .venv
)
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" setup_local.py
if errorlevel 1 goto failed
echo Setup complete. Open Start Redactor.cmd.
pause
exit /b 0
:failed
echo Setup did not complete. Install Python 3.12 from python.org with tkinter and try again.
pause
exit /b 1
