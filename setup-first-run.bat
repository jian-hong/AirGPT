@echo off
title AirGPT — first run on this laptop
cd /d "%~dp0"
echo.
echo  AirGPT first-time setup
echo  Folder: %CD%
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Python not found.
  echo  Install Python 3.10+ from https://www.python.org/downloads/
  echo  Tick "Add python to PATH" then run this again.
  pause
  exit /b 1
)

if not exist env.local (
  echo  Creating env.local from template...
  copy /Y env.local.example env.local >nul
  echo  Edit env.local or use Settings to add API keys.
)

echo  Installing Python packages...
pip install -r requirements.txt
if errorlevel 1 (
  echo  pip install failed — check internet and Python PATH.
  pause
  exit /b 1
)

echo.
echo  Setup OK. Starting AirGPT...
call restart.bat
