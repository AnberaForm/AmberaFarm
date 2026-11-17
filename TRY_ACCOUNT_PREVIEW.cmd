@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.12 or 3.13 for Windows is required: https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
if not exist ".ambera_venv\Scripts\python.exe" (
  py -3 -m venv ".ambera_venv"
  if errorlevel 1 goto failed
)
".ambera_venv\Scripts\python.exe" -c "import pygame, websocket, websockets.asyncio.server" >nul 2>nul
if errorlevel 1 (
  ".ambera_venv\Scripts\python.exe" -m pip install -r requirements.txt websockets==15.0.1
  if errorlevel 1 goto failed
)
".ambera_venv\Scripts\python.exe" deployment\preview_account_game.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Preview could not start. Check the message above.
pause
exit /b 1
