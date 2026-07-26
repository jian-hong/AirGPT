@echo off
cd /d "%~dp0"
title AirGPT (supervised)
echo.
echo  AirGPT - supervised start
echo  Restarts on crash; logs in data\server.err.log and data\crash.log
echo.
pip install -q -r requirements.txt 2>nul
python supervisor.py
pause
