@echo off
title Dark Messenger Restarter
setlocal enabledelayedexpansion

echo ========================================
echo   Restarting Dark Messenger
echo ========================================

:: 1. Останавливаем Nginx (если запущен)
echo [1/4] Stopping Nginx...
taskkill /f /im nginx.exe >nul 2>&1
if %errorlevel%==0 (echo   ✓ Nginx stopped) else (echo   ℹ Nginx not running)

:: 2. Останавливаем Flask-приложение по PID из файла
echo [2/4] Stopping Flask app...
set "PID_FILE=%CD%\app.pid"
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    echo   Found PID: !PID!
    taskkill /f /pid !PID! >nul 2>&1
    if !errorlevel!==0 (
        echo   ✓ Flask stopped
    ) else (
        echo   ⚠ Flask process not found, trying to kill python.exe...
        taskkill /f /im python.exe >nul 2>&1
    )
    del "%PID_FILE%" >nul 2>&1
) else (
    echo   ⚠ PID file not found, killing all python processes...
    taskkill /f /im python.exe >nul 2>&1
)

:: Пауза для освобождения портов
echo   Waiting for ports to free...
timeout /t 2 /nobreak >nul

:: 3. Запускаем Nginx
echo [3/4] Starting Nginx...
if exist "C:\nginx\nginx.exe" (
    cd /d C:\nginx
    start nginx
    echo   ✓ Nginx started
) else (
    echo   ✗ ERROR: Nginx not found at C:\nginx\nginx.exe
    echo   Please check your Nginx installation
    pause
    exit /b 1
)

:: 4. Запускаем Flask-приложение
echo [4/4] Starting Flask app...
cd /d %~dp0

:: Активация виртуального окружения (если используете venv)
if exist "%~dp0venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo   ✓ Virtual environment activated
)

:: Запуск приложения
start /b python run.py
timeout /t 3 /nobreak >nul

:: Проверка создания PID-файла
if exist "%PID_FILE%" (
    set /p NEW_PID=<"%PID_FILE%"
    echo   ✓ Flask running with PID: !NEW_PID!
) else (
    echo   ⚠ WARNING: Could not verify PID.
    echo   Check if run.py exists and has PID writing code.
)

echo ========================================
echo   Restart completed
echo   Check: https://blockcoin.ru
echo ========================================
pause