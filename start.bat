@echo off
setlocal
cd /d "%~dp0"
title Laptop Loans (close this window to stop the app)

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if defined PYEXE goto run
python --version >nul 2>&1
if not errorlevel 1 set "PYEXE=python"
if defined PYEXE goto run
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYEXE=py -3"
if defined PYEXE goto run

echo Python was not found. Please double-click setup.bat first.
echo.
pause
goto end

:run
echo Starting Laptop Loans ...
echo Your browser will open at http://localhost:8000
echo Keep this window open while you work. Close it to stop the app.
echo.
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process http://localhost:8000"
%PYEXE% app.py %*
echo.
echo The app has stopped. If this was unexpected, see the Troubleshooting
echo section of USER_GUIDE.md.
pause

:end
endlocal
