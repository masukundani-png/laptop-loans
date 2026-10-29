@echo off
setlocal
cd /d "%~dp0"
title Laptop Loans - Setup
echo ============================================
echo   Laptop Loans - one-time setup
echo ============================================
echo.

set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto have_python
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto have_python

echo [!] Python was not found on this computer.
echo.
echo     1. Go to https://www.python.org/downloads/
echo     2. Download and run the Windows installer.
echo     3. IMPORTANT: on the first screen, tick the box
echo        "Add python.exe to PATH" before clicking Install.
echo     4. When it finishes, run setup.bat again.
echo.
goto done

:have_python
echo Using Python: %PY%
%PY% --version
echo.

if exist ".venv\Scripts\python.exe" goto have_venv
echo Creating virtual environment in .venv ...
%PY% -m venv .venv
if errorlevel 1 goto venv_failed
:have_venv

echo Installing required packages (this needs internet) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pip_failed
echo.
echo Packages installed.
echo.

echo Checking for PDF support ...
set "PDFTOOL="
if exist "%ProgramFiles%\LibreOffice\program\soffice.exe" set "PDFTOOL=LibreOffice"
if exist "%ProgramFiles(x86)%\LibreOffice\program\soffice.exe" set "PDFTOOL=LibreOffice"
where soffice >nul 2>&1
if not errorlevel 1 set "PDFTOOL=LibreOffice"
if defined PDFTOOL goto pdf_report
reg query "HKEY_CLASSES_ROOT\Word.Application" >nul 2>&1
if not errorlevel 1 set "PDFTOOL=Microsoft Word"
:pdf_report
if defined PDFTOOL goto pdf_found
echo [!] Neither LibreOffice nor Microsoft Word was found.
echo     The app will still work, but it can only create Word (.docx)
echo     forms, not PDFs. For PDFs, install the free LibreOffice from
echo     https://www.libreoffice.org/download/ and run start.bat again.
goto finished
:pdf_found
echo PDF output: %PDFTOOL% found - forms will be saved as .docx and .pdf.
goto finished

:venv_failed
echo.
echo [!] Could not create the virtual environment.
echo     Try re-installing Python from https://www.python.org/downloads/
echo     and tick "Add python.exe to PATH".
goto done

:pip_failed
echo.
echo [!] Installing packages failed. Check the internet connection
echo     and run setup.bat again.
goto done

:finished
echo.
echo ============================================
echo   Setup complete. Double-click start.bat to run the app.
echo ============================================

:done
echo.
pause
endlocal
