@echo off
cd /d "%~dp0"
if not exist venv\Scripts\python.exe (
  echo Falta instalar. Sigue los pasos del archivo LEEME.md
  pause
  exit /b 1
)
venv\Scripts\python.exe run.py
pause
