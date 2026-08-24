@echo off
REM Start AirGPT on the disposable DEMO / BUSINESS MOCK profile.
REM Real ./data is untouched. See video-assets/00-handoff/DEMO_MOCK.md
cd /d "%~dp0"
title AirGPT DEMO MOCK
echo.
echo  AirGPT — DEMO / BUSINESS MOCK profile
echo  Data dir: data-demo-mock  (real ./data untouched)
echo.

REM Stop anything on 8765
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8765 ^| findstr LISTENING') do (
  taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

python seed_demo_mock.py
if errorlevel 1 (
  echo Seed failed.
  pause
  exit /b 1
)

set AIRGPT_DEMO_MOCK=1
set AIRGPT_DATA_DIR=%~dp0data-demo-mock
set AIRGPT_DEMO_LAN_IP=10.10.20.42
set AIRGPT_DEMO_HOSTNAME=DEMO-LAPTOP

echo  Starting clipdrop.py with DEMO_MOCK...
start "AirGPT DEMO MOCK" cmd /k "set AIRGPT_DEMO_MOCK=1&& set AIRGPT_DATA_DIR=%~dp0data-demo-mock&& set AIRGPT_DEMO_LAN_IP=10.10.20.42&& set AIRGPT_DEMO_HOSTNAME=DEMO-LAPTOP&& python clipdrop.py"
timeout /t 4 /nobreak >nul
start http://127.0.0.1:8765
echo.
echo  PC: http://127.0.0.1:8765
echo  Confirm /api/info shows "demo_mock": true
python scripts\verify_demo_smoke.py --require-demo-mock
echo  To return to real data: close this server and run start.bat / restart.bat
echo.
pause
