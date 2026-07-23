@echo off
cd /d "%~dp0"
title ClipDrop v5
echo.
echo  ClipDrop - screenshot + clipboard sync
echo  iPad: use TUNNEL URL shown in browser (works on company WiFi)
echo.
pip install -q -r requirements.txt 2>nul
python clipdrop.py
pause
