@echo off
cd /d "%~dp0"
echo Building AirGPT EXE (one-folder portable, light — no Cortex embed)...
pip install pyinstaller -q
pyinstaller --noconfirm --onedir --name AirGPT ^
  --add-data "index.html;." ^
  --add-data "admin.html;." ^
  --add-data "p2p-drop.html;." ^
  --add-data "viewer.html;." ^
  --hidden-import win32clipboard ^
  --hidden-import PIL ^
  --hidden-import qrcode ^
  --hidden-import pynput ^
  --hidden-import zeroconf ^
  --hidden-import wifi_access ^
  --hidden-import cortex_client ^
  --hidden-import access_policy ^
  --hidden-import admin_dashboard ^
  --hidden-import license ^
  --hidden-import auth ^
  --hidden-import ai_engine ^
  clipdrop.py
echo.
echo Output: dist\AirGPT\AirGPT.exe
echo Copy env.local.example to dist\AirGPT\env.local and add your keys.
echo Code signing: use signtool with your Authenticode cert (SmartScreen).
echo First run: Personal is free; activate Business key for org safety.
pause
