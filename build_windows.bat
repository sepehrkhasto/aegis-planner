@echo off
chcp 65001 >nul
REM ==========================================================================
REM   Aegis Planner - one-click Windows build
REM   Double-click this file. It will:  tests -> app (PyInstaller) -> Setup.exe (Inno Setup)
REM   Result:  installer_output\AegisPlanner-Setup-<version>.exe   (opens automatically)
REM   Needs only Python 3.10+ from python.org (tick "Add python.exe to PATH").
REM   Code signing (optional, removes the Windows "Smart App Control" / SmartScreen blocks): set AEGIS_SIGN_CMD to your
REM   signtool command without the file name, e.g.
REM     set AEGIS_SIGN_CMD=signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f cert.pfx /p PASSWORD
REM   The app, the installer and the uninstaller are then all signed.
REM   Inno Setup is installed for you (via winget) if it is missing.
REM ==========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Aegis Planner - Build

where python >nul 2>nul || (
    echo [X] Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo     and tick "Add python.exe to PATH" during setup, then run this file again.
    goto :err
)

echo.
echo [1/5] Preparing environment...
if not exist .venv ( python -m venv .venv || goto :err )
call .venv\Scripts\activate.bat || goto :err
python -m pip install --quiet --upgrade pip || goto :err
python -m pip install --quiet -r requirements-dev.txt || goto :err

for /f %%v in ('python -c "from aegis_desktop import __version__ as v; print(v)"') do set VER=%%v
echo      version: %VER%

echo.
echo [2/5] Tests skipped by default ^(set RUN_TESTS=1 to run them first; takes a few minutes^)
if not "%RUN_TESTS%"=="1" ( echo      skipped ) else (
    set QT_QPA_PLATFORM=offscreen
    python -m pytest tests -q -x || ( echo [X] Tests failed - build stopped. Send the error text, or build without RUN_TESTS. & goto :err )
    set QT_QPA_PLATFORM=
)

echo.
echo [3/5] Building the application (PyInstaller)...
pyinstaller packaging\aegis.spec --noconfirm --clean --log-level WARN || goto :err
if not exist dist\AegisPlanner\AegisPlanner.exe ( echo [X] AegisPlanner.exe was not produced. & goto :err )
if defined AEGIS_SIGN_CMD (
    echo      signing AegisPlanner.exe...
    call !AEGIS_SIGN_CMD! "dist\AegisPlanner\AegisPlanner.exe" || ( echo [X] Signing failed. & goto :err )
)

echo.
echo [4/5] Looking for Inno Setup...
set ISCC=
where ISCC >nul 2>nul && set "ISCC=ISCC"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo      Inno Setup is missing - installing it with winget...
    winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    echo.
    echo [!] Could not install Inno Setup automatically. Install it from https://jrsoftware.org/isdl.php
    echo     and run this file again. Meanwhile the portable app is ready:
    echo     dist\AegisPlanner\AegisPlanner.exe
    start "" explorer "dist\AegisPlanner"
    goto :done
)

echo.
echo [5/5] Building the installer...
set ISCC_SIGN=
if defined AEGIS_SIGN_CMD set ISCC_SIGN=/DSignTool=1 "/Saegissign=!AEGIS_SIGN_CMD! $f"
"%ISCC%" /Q /DAppVersion=%VER% !ISCC_SIGN! packaging\installer.iss || goto :err
set OUT=installer_output\AegisPlanner-Setup-%VER%.exe
if not exist "%OUT%" ( echo [X] Installer was not produced. & goto :err )

echo.
echo ==========================================================================
echo   DONE.  Your installer:
echo   %CD%\%OUT%
echo ==========================================================================
start "" explorer /select,"%CD%\%OUT%"

:done
echo.
pause
exit /b 0

:err
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
