@echo off
title AirGPT — Enable LAN (Admin)
cd /d "%~dp0"
echo.
echo  Opening firewall + setting WiFi to Private...
echo  Click YES on the UAC prompt.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"\"%~dp0allow_firewall.ps1\"\" -Quiet'"
timeout /t 3 /nobreak >nul
echo.
echo  Restarting AirGPT...
call "%~dp0restart.bat"
