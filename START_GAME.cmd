@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Ambera Farm - Start

echo ===========================================
echo             AMBERA FARM
 echo         Windows Game Launcher
 echo ===========================================
echo.
if not exist "%~dp0start_game.py" (
  echo ERROR: Missing start_game.py
  echo Extract ALL files from the ZIP before launching.
  goto :FAILED
)

rem All launcher text is ASCII to avoid CMD Japanese encoding problems.
rem Prefer the Windows Python launcher, then the normal Python command.
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 goto :USE_PY
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if not errorlevel 1 goto :USE_PYTHON

echo ERROR: Python 3.10 or newer could not be found.
echo Install Python from https://www.python.org/downloads/windows/
echo If you already installed Python, check the PATH / Python Launcher.
goto :FAILED

:USE_PY
echo [OK] Using Python Launcher (py -3).
py -3 -u "%~dp0start_game.py"
if errorlevel 1 goto :FAILED
goto :DONE

:USE_PYTHON
echo [OK] Using python command.
python -u "%~dp0start_game.py"
if errorlevel 1 goto :FAILED
goto :DONE

:DONE
echo.
echo Game closed normally.
exit /b 0

:FAILED
echo.
echo LAUNCH FAILED. See launcher_log.txt in this folder.
echo Take a screenshot of this screen or send launcher_log.txt.
echo.
pause
exit /b 1
