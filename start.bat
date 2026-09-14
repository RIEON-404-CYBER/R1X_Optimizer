@echo off
title R1X Optimizer v3 - Boot
cd /d "%~dp0"

if exist "dist\R1X_Optimizer_v3.exe" (
  echo [R1X] v3 detected - launching desktop app...
  echo       (accept the Administrator prompt if shown)
  start "" "dist\R1X_Optimizer_v3.exe"
  exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python not found. Run build_exe.bat on a machine with Python
  echo     to create the .exe first.
  pause & exit /b 1
)

echo [R1X] EXE not built yet - running in Python mode...
echo       Tip: run  build_exe.bat  to make the real desktop EXE.
start "" python "gui.py"
timeout /t 4 >nul
exit /b 0