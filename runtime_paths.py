"""Locations and subprocess commands for source and portable builds."""
from pathlib import Path
import sys

FROZEN=bool(getattr(sys,'frozen',False))
RESOURCE_DIR=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
APP_DIR=Path(sys.executable).resolve().parent if FROZEN else RESOURCE_DIR

def worker_command(mode):
    if FROZEN:
        return [str(APP_DIR/'RedactorWorker.exe'),mode]
    if mode=='--ocr-worker':
        return [sys.executable,str(RESOURCE_DIR/'local_ocr.py'),'--worker']
    return [sys.executable,str(RESOURCE_DIR/'redactor.py'),mode]
