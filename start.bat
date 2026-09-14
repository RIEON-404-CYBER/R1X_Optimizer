@echo off
title R1X Optimizer v3 - Boot
cd /d "%~dp0"

if exist "dist\R1X_Optimizer_v3.exe" (
  echo [R1X] Launching desktop app...
  start "" "dist\R1X_Optimizer_v3.exe"
  exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python not found. Run build_exe.bat on a machine with Python to make the .exe.
  pause & exit /b 1
)

echo [R1X] Launching desktop GUI (no browser)...
start "" python "gui.py"
timeout /t 4 >nul
exit /b 0