@echo off
setlocal enabledelayedexpansion
title ClipDrop Restart
cd /d "%~dp0"
echo.
echo  Stopping ClipDrop...

rem "-p TCP" and the trailing space in ":8765 " keep this to real listeners on this
rem port. The old filter was `findstr :8765` over all protocols, which also matched
rem ports like :87650-shaped columns and foreign addresses.
for /f "tokens=5" %%a in ('netstat -ano -p TCP ^| findstr LISTENING ^| findstr ":8765 "') do (
  echo    killing PID %%a
  taskkill /F /PID %%a >nul 2>&1
)
taskkill /F /IM cloudflared.exe >nul 2>&1

rem Wait for the port to actually be free rather than guessing with a fixed sleep.
rem A kill that had not landed yet meant the new process failed to bind and exited,
rem which is exactly how a restart ended at "Stopping ClipDrop..." with nothing running.
set FREE=0
for /l %%i in (1,1,20) do (
  if "!FREE!"=="0" (
    netstat -ano -p TCP | findstr LISTENING | findstr ":8765 " >nul 2>&1
    if errorlevel 1 (set FREE=1) else (timeout /t 1 /nobreak >nul)
  )
)
if "!FREE!"=="0" (
  echo.
  echo  STILL IN USE - something is holding 8765:
  netstat -ano -p TCP | findstr LISTENING | findstr ":8765 "
  echo  Close that process, then run restart.bat again.
  echo.
  pause
  exit /b 1
)
echo  Port 8765 is free.

echo  Opening LAN firewall (click YES on UAC if prompted)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0allow_firewall.ps1\"\" -Quiet'" >nul 2>&1

echo  Starting ClipDrop v5...
pip install -q -r requirements.txt 2>nul
rem `cmd /k` so the window survives the process. With a bare `start ... python`, the
rem console dies the instant python exits, which destroyed the startup error - an
rem ImportError or "Port 8765 in use" flashed up and vanished, leaving a restart that
rem looked like it simply stopped and never came back.
start "ClipDrop" cmd /k python clipdrop.py

rem Confirm it is serving before claiming success. This used to print the URLs
rem whether or not the process had survived startup.
set UP=0
for /l %%i in (1,1,30) do (
  if "!UP!"=="0" (
    timeout /t 1 /nobreak >nul
    netstat -ano -p TCP | findstr LISTENING | findstr ":8765 " >nul 2>&1
    if not errorlevel 1 set UP=1
  )
)
if "!UP!"=="0" (
  echo.
  echo  ClipDrop did NOT come up. The "ClipDrop" window is still open - read the
  echo  error there. Usually an import error or a missing requirement.
  echo.
  pause
  exit /b 1
)
echo  ClipDrop is listening on 8765.

python allcheck.py
python wifi_debug.py
python security_test.py
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do set LAN_IP=%%a
set LAN_IP=!LAN_IP: =!
start http://127.0.0.1:8765
echo.
echo  PC:   http://127.0.0.1:8765
if defined LAN_IP echo  LAN:  http://!LAN_IP!:8765  ^(scan LAN QR on phone^)
echo  Run enable-lan.bat if phone cannot connect on WiFi.
echo.
pause
