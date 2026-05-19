@echo off
title Dark Messenger Restarter
echo ========================================
echo   Restarting Dark Messenger
echo ========================================

:: 1. Останавливаем Nginx
echo [1/4] Stopping Nginx...
taskkill /f /im nginx.exe >nul 2>&1
if %errorlevel%==0 (echo   Nginx stopped) else (echo   Nginx not running)

:: 2. Останавливаем Flask-приложение по PID из файла
echo [2/4] Stopping Flask app...
set "PID_FILE=%CD%\app.pid"
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    echo   Found PID: !PID!
    taskkill /f /pid !PID! >nul 2>&1
    if !errorlevel!==0 (echo   Flask stopped) else (echo   Flask process not found)
    del "%PID_FILE%" >nul 2>&1
) else (
    echo   PID file not found, attempting to kill all python processes...
    taskkill /f /im python.exe >nul 2>&1
    echo   Killed all python processes
)

:: Небольшая пауза, чтобы порты освободились
timeout /t 2 /nobreak >nul

:: 3. Запускаем Nginx
echo [3/4] Starting Nginx...
cd /d C:\nginx
start nginx
echo   Nginx started

:: 4. Запускаем Flask-приложение
echo [4/4] Starting Flask app...
cd /d %~dp0
start /b python run.py
timeout /t 3 /nobreak >nul

:: Проверяем, создался ли PID-файл
if exist "%PID_FILE%" (
    set /p NEW_PID=<"%PID_FILE%"
    echo   Flask running with PID: !NEW_PID!
) else (
    echo   WARNING: Could not verify PID. Check app.log for errors.
)

echo ========================================
echo   Restart completed
echo   Check: https://localhost
echo ========================================
pause