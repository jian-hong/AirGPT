@echo off
title AirGPT — Phone Hotspot Help
cd /d "%~dp0"
echo.
echo  === Phone Hotspot Mode (no cable, no router blocking) ===
echo.
echo  1. On phone: Settings -^> Hotspot -^> turn ON
echo  2. On PC: connect WiFi to your phone hotspot
echo  3. Double-click restart.bat on this PC
echo  4. Scan the WiFi QR in the app (new IP)
echo.
echo  Opening WiFi settings...
start ms-settings:network-wifi
echo.
pause
