@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Ambera Farm Windows EXE Build
where py >nul 2>&1
if not errorlevel 1 goto PY
where python >nul 2>&1
if not errorlevel 1 goto PYTHON
echo ERROR: Install Python 3.10+ to build locally.
goto FAIL
:PY
py -3 -m pip install -r requirements-build.txt
if errorlevel 1 goto FAIL
py -3 build_windows.py
if errorlevel 1 goto FAIL
goto DONE
:PYTHON
python -m pip install -r requirements-build.txt
if errorlevel 1 goto FAIL
python build_windows.py
if errorlevel 1 goto FAIL
:DONE
echo BUILD COMPLETE: build_output\exe\
echo For updater ZIP run: python pack_windows_release.py --repo OWNER/REPO --version 0.6.0
pause
exit /b 0
:FAIL
echo EXE build failed. Please read errors above.
pause
exit /b 1
