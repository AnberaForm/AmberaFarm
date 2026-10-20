@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Ambera Farm - Check Python
py -3 -c "import sys,importlib.util;print('Python:',sys.version);print('Location:',sys.executable);print('Pygame:',importlib.util.find_spec('pygame'))"
if errorlevel 1 python -c "import sys,importlib.util;print('Python:',sys.version);print('Location:',sys.executable);print('Pygame:',importlib.util.find_spec('pygame'))"
echo.
echo Send this screen if a problem remains.
pause
