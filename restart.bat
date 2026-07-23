@echo off
title ClipDrop Restart
cd /d "%~dp0"
echo.
echo  Stopping ClipDrop...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
)
taskkill /F /IM cloudflared.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo  Opening LAN firewall (click YES on UAC if prompted)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0allow_firewall.ps1\"\" -Quiet'" >nul 2>&1
timeout /t 4 /nobreak >nul
echo  Starting ClipDrop v5...
pip install -q -r requirements.txt 2>nul
start "ClipDrop" python clipdrop.py
timeout /t 5 /nobreak >nul
python allcheck.py
python wifi_debug.py
python security_test.py
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do set LAN_IP=%%a
set LAN_IP=%LAN_IP: =%
start http://127.0.0.1:8765
echo.
echo  PC:   http://127.0.0.1:8765
if defined LAN_IP echo  LAN:  http://%LAN_IP%:8765  ^(scan LAN QR on phone^)
echo  Run enable-lan.bat if phone cannot connect on WiFi.
echo.
pause
