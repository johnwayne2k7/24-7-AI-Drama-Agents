@echo off
rem 24/7 Drama Bots launcher for Windows: double-click this file.
rem 24/7 Drama Bots was created by John Wayne Maquinta.
title 24/7 Drama Bots - by John Wayne Maquinta
cd /d "%~dp0"
if "%PORT%"=="" set PORT=4247

rem Find a real Python. "where python" is not enough: Windows has a fake python.exe
rem (Microsoft Store stub) that passes "where" but fails when run, so we run it.
set PY=
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY goto nopython

if not exist .env copy .env.example .env >nul
rem Updating? Close an older 24/7 Drama Bots that is still running, so the new version can start.
powershell -NoProfile -Command "try{$r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Headers @{'X-Drama'='1'} http://127.0.0.1:%PORT%/api/status; if($r.Content -match 'keySet'){Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | ForEach-Object {Stop-Process -Id $_.OwningProcess -Force}; Write-Host 'Closed the older 24/7 Drama Bots that was still running.'; Start-Sleep 1}}catch{}"
echo 24/7 Drama Bots is starting at http://localhost:%PORT% - keep this window open, close it to stop.
rem Open the browser a few seconds from now, after the server is up.
start "" /min cmd /c "ping -n 3 127.0.0.1 >nul & start http://localhost:%PORT%"
%PY% server.py
echo.
echo The studio stopped. If you see an error above, take a screenshot of it.
pause
exit /b

:nopython
echo.
echo Python 3 was not found on this computer, so 24/7 Drama Bots can't start yet.
echo.
echo 1. Install Python from https://www.python.org/downloads/
echo 2. In the installer, tick "Add python.exe to PATH" at the bottom, then Install.
echo 3. If Windows opens the Microsoft Store when you run python, turn OFF the
echo    python.exe and python3.exe switches in:
echo    Settings - Apps - Advanced app settings - App execution aliases
echo 4. Close this window and double-click start.bat again.
echo.
pause
exit /b 1
