@echo off
cd /d "%~dp0"
echo Enter the final HTTPS URL where the new update ZIP will be hosted.
set /p PACKAGE_URL=Package URL: 
if "%PACKAGE_URL%"=="" goto :bad
py -3 make_release.py --package-url "%PACKAGE_URL%"
if errorlevel 1 goto :bad
echo Success. Upload both files from the release folder.
pause
exit /b 0
:bad
echo Failed. Check HTTPS URL and Python configuration.
pause
exit /b 1
