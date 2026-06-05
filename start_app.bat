@echo off
title Dark Messenger Server Controller
setlocal enabledelayedexpansion

:: Устанавливаем кодировку UTF-8
chcp 65001 >nul 2>&1

:: Цвета для ANSI
set "RESET=[0m"
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "CYAN=[96m"
set "WHITE=[97m"
set "BOLD=[1m"
set "DIM=[2m"

:: Путь к проекту (ИЗМЕНИТЕ НА ВАШ)
set "PROJECT_DIR=E:\BlockcoinWitres"
set "NGINX_DIR=C:\nginx"

:: Файлы
set "PID_FILE=%PROJECT_DIR%\app.pid"
set "LOG_FILE=%PROJECT_DIR%\messenger.log"
set "AUTORESTART_FLAG=%TEMP%\darkmessenger_autorestart.flag"

:: Проверка существования проекта
if not exist "%PROJECT_DIR%" (
    echo %RED%ERROR: Project directory not found: %PROJECT_DIR%%RESET%
    echo %YELLOW%Please edit the PROJECT_DIR variable in this script%RESET%
    pause
    exit /b 1
)

:: ==============================================
:: АВТО-ВОССТАНОВЛЕНИЕ (при краше сервера)
:: ==============================================
if "%1"=="--autorestart" (
    del "%AUTORESTART_FLAG%" 2>nul
    goto START_SILENT
)

if exist "%AUTORESTART_FLAG%" (
    cls
    echo.
    echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
    echo %CYAN%║%RESET%              %BOLD%%YELLOW%⟳ AUTO-RECOVERY MODE ⟳%RESET%                         %CYAN%║%RESET%
    echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
    echo.
    echo %YELLOW%⚠ Server crashed! Restarting...%RESET%
    timeout /t 3 /nobreak >nul
    set WAITRESS_MODE=stable
    goto START_SILENT
)

:MENU
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%     %BOLD%%WHITE%█▀▄▀█ █▀▀ █▀▄ █▀▀ █▀█ █   █   █▀▀ █▀█%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%     %BOLD%%WHITE%█ ▀ █ █▄▄ █▄▀ ██▄ █▀▄ █▄▄ █▄▄ █▄▄ █▀▄%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%╠══════════════════════════════════════════════════════════════╣%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%     %GREEN%▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%     %GREEN%▓%RESET%  %BOLD%Server Control Panel v2.0%RESET%                 %GREEN%▓%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%     %GREEN%▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%GREEN%1%WHITE%] Start Server (Stable)%RESET%                 %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%CYAN%2%WHITE%] Start Server (Max Performance)%RESET%           %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%YELLOW%3%WHITE%] Start Server (Development)%RESET%              %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%BLUE%4%WHITE%] Stop Server%RESET%                           %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%CYAN%5%WHITE%] Server Status%RESET%                         %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%YELLOW%6%WHITE%] Show Logs%RESET%                             %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%GREEN%7%WHITE%] Monitor Mode (Auto-Restart)%RESET%                 %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%RED%0%WHITE%] Exit%RESET%                                 %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.
set /p choice="%BOLD%%WHITE%> Choose option: %RESET%"

if "%choice%"=="1" goto START_STABLE
if "%choice%"=="2" goto START_MAX
if "%choice%"=="3" goto START_DEV
if "%choice%"=="4" goto STOP
if "%choice%"=="5" goto STATUS
if "%choice%"=="6" goto LOGS
if "%choice%"=="7" goto MONITOR_MODE
if "%choice%"=="0" goto EXIT
goto MENU

:START_STABLE
set WAITRESS_MODE=stable
goto START

:START_MAX
set WAITRESS_MODE=max
goto START

:START_DEV
set WAITRESS_MODE=dev
goto START

:START
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %GREEN%▀▄   ▄▀   ▀▄   ▄▀   ▀▄   ▄▀%RESET%                  %CYAN%║%RESET%
echo %CYAN%║%RESET%               %BOLD%%GREEN%STARTING DARK MESSENGER%RESET%                    %CYAN%║%RESET%
echo %CYAN%║%RESET%              %GREEN%▄▀   ▀▄   ▄▀   ▀▄   ▄▀   ▀▄%RESET%                  %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

:START_SILENT
cd /d "%PROJECT_DIR%"

:: Запуск Nginx
echo %BOLD%%BLUE%[1/4]%RESET% %WHITE%> Checking Nginx...%RESET%
if exist "%NGINX_DIR%\nginx.exe" (
    echo %GREEN%  ✓ Nginx found at %NGINX_DIR%%RESET%
    cd /d "%NGINX_DIR%"

    :: Проверяем, не запущен ли nginx
    tasklist /fi "imagename eq nginx.exe" 2>nul | find /i "nginx.exe" >nul
    if errorlevel 1 (
        start /b nginx.exe >nul 2>&1
        echo %GREEN%  ✓ Nginx started%RESET%
    ) else (
        echo %YELLOW%  ⚠ Nginx already running%RESET%
    )
) else (
    echo %YELLOW%  ⚠ Nginx not found, continuing without it%RESET%
)
echo.

:: Активация venv
echo %BOLD%%BLUE%[2/4]%RESET% %WHITE%> Activating environment...%RESET%
if exist "%PROJECT_DIR%\venv\Scripts\activate.bat" (
    call "%PROJECT_DIR%\venv\Scripts\activate.bat"
    echo %GREEN%  ✓ Virtual environment activated%RESET%
) else (
    echo %DIM%  ℹ No virtual environment found%RESET%
)
echo.

:: Очистка старого PID файла
if exist "%PID_FILE%" (
    echo %YELLOW%  ⚠ Found stale PID file, cleaning...%RESET%
    del "%PID_FILE%" >nul 2>&1
)

:: Запуск сервера
echo %BOLD%%BLUE%[3/4]%RESET% %WHITE%> Starting Waitress server...%RESET%
echo.
echo %YELLOW%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %YELLOW%║%RESET%                                                              %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %BOLD%%GREEN%✨ Server is now RUNNING ✨%RESET%                        %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %DIM%Mode: %WHITE%!WAITRESS_MODE!%RESET%                                           %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %DIM%Project: %WHITE%%PROJECT_DIR%%RESET%                              %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %DIM%URL: %WHITE%http://127.0.0.1:8000%RESET%                                %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %BOLD%%RED%⚠ PRESS CTRL+C TO STOP THE SERVER ⚠%RESET%                  %YELLOW%║%RESET%
echo %YELLOW%║%RESET%                                                              %YELLOW%║%RESET%
echo %YELLOW%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

cd /d "%PROJECT_DIR%"

:: Запуск run_win.py напрямую (так Ctrl+C будет работать правильно)
python run.py

:: Сюда попадаем после остановки (Ctrl+C или ошибка)
set "EXIT_CODE=%errorlevel%"

:: Остановка Nginx после завершения Python
echo.
echo %BOLD%%RED%[4/4]%RESET% %WHITE%> Stopping Nginx...%RESET%
if exist "%NGINX_DIR%\nginx.exe" (
    cd /d "%NGINX_DIR%"
    nginx.exe -s stop >nul 2>&1
    if !errorlevel! equ 0 (
        echo %GREEN%  ✓ Nginx stopped gracefully%RESET%
    ) else (
        taskkill /f /im nginx.exe >nul 2>&1
        echo %GREEN%  ✓ Nginx force stopped%RESET%
    )
)
echo.

:: Если сервер упал с ошибкой (не по Ctrl+C) - создаем флаг для авто-восстановления
if %EXIT_CODE% neq 0 (
    if "%1" neq "--autorestart" (
        echo %TIME% - Server crashed with error code %EXIT_CODE% >> "%LOG_FILE%"
        echo %YELLOW%⚠ Server crashed! Creating auto-recovery flag...%RESET%
        echo autorestart > "%AUTORESTART_FLAG%" 2>nul
    )
)

echo.
echo %RED%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %RED%║%RESET%              %BOLD%%RED%✖ SERVER STOPPED ✖%RESET%                       %RED%║%RESET%
echo %RED%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

:: Если есть флаг авто-восстановления, перезапускаем
if exist "%AUTORESTART_FLAG%" (
    echo %YELLOW%⟳ Auto-recovery active, restarting in 5 seconds...%RESET%
    timeout /t 5 /nobreak >nul
    del "%AUTORESTART_FLAG%" 2>nul
    goto START_STABLE
)

echo %WHITE%Press any key to return to menu...%RESET%
pause >nul
goto MENU

:MONITOR_MODE
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %BOLD%%GREEN%♻ MONITOR MODE ♻%RESET%                                 %CYAN%║%RESET%
echo %CYAN%╠══════════════════════════════════════════════════════════════╣%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%     %DIM%Server will auto-restart if it crashes%RESET%                       %CYAN%║%RESET%
echo %CYAN%║%RESET%     %DIM%Close this window to stop the server%RESET%                       %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.
echo %GREEN%Starting server in monitor mode...%RESET%
echo.

:MONITOR_LOOP
cd /d "%PROJECT_DIR%"

:: Активация venv
if exist "%PROJECT_DIR%\venv\Scripts\activate.bat" (
    call "%PROJECT_DIR%\venv\Scripts\activate.bat" >nul 2>&1
)

:: Запуск с флагом monitor
set WAITRESS_MODE=stable
python run.py

:: Если сервер упал - перезапускаем
if errorlevel 1 (
    echo %TIME% - Server crashed! Restarting in 5 seconds... >> "%LOG_FILE%"
    echo %YELLOW%⚠ Server crashed! Restarting in 5 seconds...%RESET%
    timeout /t 5 /nobreak >nul
    goto MONITOR_LOOP
)

:: Нормальное завершение
exit /b 0

:STOP
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %BOLD%%RED%■ STOPPING SERVER ■%RESET%                       %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

:: Удаляем флаг авто-восстановления
del "%AUTORESTART_FLAG%" 2>nul

:: Остановка Nginx
echo %BOLD%%RED%[1/2]%RESET% %WHITE%> Stopping Nginx...%RESET%
if exist "%NGINX_DIR%\nginx.exe" (
    cd /d "%NGINX_DIR%"
    nginx.exe -s stop >nul 2>&1
    if !errorlevel! equ 0 (
        echo %GREEN%  ✓ Nginx stopped gracefully%RESET%
    ) else (
        taskkill /f /im nginx.exe >nul 2>&1
        if !errorlevel! equ 0 (
            echo %GREEN%  ✓ Nginx force stopped%RESET%
        ) else (
            echo %DIM%  ℹ Nginx not running%RESET%
        )
    )
)
echo.

:: Остановка Python процессов
echo %BOLD%%RED%[2/2]%RESET% %WHITE%> Stopping Python server...%RESET%
taskkill /f /im python.exe >nul 2>&1
if errorlevel 1 (
    echo %DIM%  ℹ No Python processes found%RESET%
) else (
    echo %GREEN%  ✓ All Python processes stopped%RESET%
)

:: Очистка порта 8000
echo.
echo %BOLD%%RED%[3/3]%RESET% %WHITE%> Cleaning port 8000...%RESET%
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
    echo %GREEN%  ✓ Killed process on port 8000: %%a%RESET%
)

echo.
echo %GREEN%✅ Server stopped successfully%RESET%
echo.
echo %WHITE%Press any key to return to menu...%RESET%
pause >nul
goto MENU

:STATUS
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %BOLD%%BLUE%ℹ SERVER STATUS ℹ%RESET%                         %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

:: Проверка Nginx
echo %BOLD%%WHITE%> Nginx:%RESET%
tasklist /fi "imagename eq nginx.exe" 2>nul | find /i "nginx.exe" >nul
if errorlevel 1 (
    echo   %RED%❌ NOT RUNNING%RESET%
) else (
    for /f "tokens=2" %%i in ('tasklist /fi "imagename eq nginx.exe" /fo csv 2^>nul ^| findstr /i "nginx"') do (
        echo   %GREEN%✅ RUNNING (PID: %%~i)%RESET%
    )
)

:: Проверка порта 8000
echo.
echo %BOLD%%WHITE%> Waitress (Port 8000):%RESET%
netstat -ano | findstr ":8000.*LISTENING" >nul
if errorlevel 1 (
    echo   %RED%❌ NOT RUNNING%RESET%
) else (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
        echo   %GREEN%✅ RUNNING (PID: %%a)%RESET%
    )
)

:: Проверка через HTTP
echo.
echo %BOLD%%WHITE%> Health Check:%RESET%
curl -s -o nul -w "%%{http_code}" http://127.0.0.1:8000/health 2>nul | find "200" >nul
if errorlevel 1 (
    echo   %RED%❌ NOT RESPONDING%RESET%
) else (
    echo   %GREEN%✅ HEALTHY%RESET%
)

echo.
echo %WHITE%Press any key to return to menu...%RESET%
pause >nul
goto MENU

:LOGS
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %BOLD%%YELLOW%📋 LAST 20 LOG LINES 📋%RESET%                      %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

if exist "%LOG_FILE%" (
    echo %DIM%╔══════════════════════════════════════════════════════════════╗%RESET%
    powershell -Command "Get-Content '%LOG_FILE%' -Tail 20"
    echo %DIM%╚══════════════════════════════════════════════════════════════╝%RESET%
) else (
    echo %RED%  ✗ Log file not found: %LOG_FILE%%RESET%
)

echo.
echo %WHITE%Press any key to return to menu...%RESET%
pause >nul
goto MENU

:EXIT
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%           %BOLD%%WHITE%👋 Goodbye from Dark Messenger! 👋%RESET%               %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.
timeout /t 2 /nobreak >nul
exit /b 0