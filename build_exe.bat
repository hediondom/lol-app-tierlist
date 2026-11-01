@echo off
title Compilador de LoL Companion
cd /d "%~dp0"

echo =======================================================
echo       Compilando LoL Companion a Ejecutable (.exe)
echo =======================================================
echo.

python -m PyInstaller --noconfirm --onedir --windowed --name "LoLCompanion" ^
    --add-data "gui;gui" ^
    --add-data "champions_cache.json;." ^
    --add-data "champions_folder_cache.json;." ^
    app_gui.py

if %ERRORLEVEL% EQU 0 (
    if exist "config.json" (
        copy /y "config.json" "dist\LoLCompanion\config.json" >nul
    )
    echo.
    echo =======================================================
    echo       [OK] Compilacion completada exitosamente!
    echo       El ejecutable se encuentra en:
    echo       dist\LoLCompanion\LoLCompanion.exe
    echo =======================================================
) else (
    echo.
    echo [!] Hubo un error durante la compilacion. Revisa los mensajes anteriores.
)

pause
