@echo off
title ClipDrop allcheck
cd /d "%~dp0"
echo.
echo  Running ClipDrop allcheck...
python allcheck.py
echo.
pause
