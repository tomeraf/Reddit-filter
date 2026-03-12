@echo off
echo ============================================
echo  Reddit Scanner - Setup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v found
    goto :has_python
)

:: Python not found — download and install it
echo Python not found. Downloading Python 3.12...
echo.

set "INSTALLER=%TEMP%\python-installer.exe"
powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe' -OutFile '%INSTALLER%'" 2>nul

if not exist "%INSTALLER%" (
    echo [X] Download failed. Please install Python manually from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing Python 3.12 (this may take a minute)...
"%INSTALLER%" /passive InstallAllUsers=0 PrependPath=1 Include_test=0
if %errorlevel% neq 0 (
    echo [X] Python installation failed. Please install manually from https://www.python.org/downloads/
    del "%INSTALLER%" >nul 2>&1
    pause
    exit /b 1
)
del "%INSTALLER%" >nul 2>&1

:: Refresh PATH so we can use python immediately
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%PATH%"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Python installed but not in PATH. Please close this window, reopen it, and run install.bat again.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v installed

:has_python

:: Install Playwright
echo.
echo Installing Playwright (browser automation for Reddit login)...
pip install playwright >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Failed to install Playwright Python package.
    pause
    exit /b 1
)
echo [OK] Playwright package installed

echo Installing Chromium browser...
playwright install chromium >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Failed to install Chromium. Try running manually: playwright install chromium
    pause
    exit /b 1
)
echo [OK] Chromium browser installed

echo.
echo ============================================
echo  All done! Double-click start.bat to run.
echo ============================================
pause
