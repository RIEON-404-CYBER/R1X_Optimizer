@echo off
title R1X Optimizer - EXE Builder
cd /d "%~dp0"
echo ============================================
echo   R1X OPTIMIZER v3 - DESKTOP EXE BUILDER
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python not found. Install Python 3.10+ first.
  pause & exit /b 1
)

echo [1/4] Installing build deps...
python -m pip install --quiet --upgrade pyinstaller customtkinter pillow
if errorlevel 1 ( echo [X] pip install failed. & pause & exit /b 1 )

echo [2/4] Generating neon app icon...
python make_icon.py

echo [3/4] Building standalone desktop EXE (onefile + windowed)...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name "R1X_Optimizer_v3" ^
  --icon "r1x.ico" ^
  --hidden-import tkinter ^
  --hidden-import customtkinter ^
  --hidden-import PIL.ImageTk ^
  --hidden-import psutil ^
  gui.py
if errorlevel 1 ( echo [X] Build failed. & pause & exit /b 1 )

echo [4/4] Done!
echo.
echo Final EXE:  dist\R1X_Optimizer_v3.exe  (DESKTOP APP - no browser)
echo Run it as Administrator for the full arsenal.
pause