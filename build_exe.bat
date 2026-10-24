@echo off
rem Rebuild the desktop app. Your progress lives in %LOCALAPPDATA%\AION2 Pet Tracker and is not touched.
cd /d "%~dp0"
tasklist /FI "IMAGENAME eq AION2 Pet Tracker.exe" | find /I "AION2 Pet Tracker.exe" >nul && (
  echo Close AION2 Pet Tracker first, then run this again.
  pause
  exit /b 1
)
.venv\Scripts\pyinstaller packaging\tracker.spec --noconfirm --distpath dist --workpath build
echo.
echo Done: dist\AION2 Pet Tracker\AION2 Pet Tracker.exe  (the desktop shortcut points here)
pause
