@echo off
title Dark Messenger Restarter
setlocal enabledelayedexpansion

echo ========================================
echo   Restarting Dark Messenger
echo ========================================

set WSL_PATH=/mnt/e/BlockcoinGunicorn

:: 1. Убиваем старые процессы Gunicorn (чтобы не было конфликта портов)
echo [1/3] Stopping old app...
wsl bash -c "pkill -f gunicorn 2>/dev/null"
timeout /t 2 /nobreak >nul

:: 2. Nginx
echo [2/3] Restarting Nginx...
taskkill /f /im nginx.exe >nul 2>&1
cd /d C:\nginx
start /b nginx
timeout /t 1 /nobreak >nul
echo   OK

:: 3. Запускаем Gunicorn в отдельном окне (хитрость)
echo [3/3] Starting Gunicorn in new window...
call E:\BlockcoinGunicorn\start_gunicorn.bat

echo.
echo ========================================
echo   Gunicorn запущен в новом окне.
echo   Не закрывайте то окно, иначе сайт упадёт.
echo   https://blockcoin.ru
echo ========================================
pause