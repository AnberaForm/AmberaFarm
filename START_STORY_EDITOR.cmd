@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import tkinter" >nul 2>&1
if not errorlevel 1 (
    py -3 story_editor.py
    if errorlevel 1 goto :failed
    exit /b 0
)
python -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :failed
python story_editor.py
if errorlevel 1 goto :failed
exit /b 0
:failed
echo [ERROR] Cannot open story editor. Python and tkinter are required.
pause
exit /b 1
