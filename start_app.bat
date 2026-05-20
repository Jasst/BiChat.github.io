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

:: Путь к проекту
set "PROJECT_DIR=E:\BlockcoinWitres"
set "NGINX_DIR=C:\nginx"

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
echo %CYAN%║%RESET%     %GREEN%▓%RESET%  %BOLD%Server Control Panel%RESET%                     %GREEN%▓%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%     %GREEN%▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓%RESET%          %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%GREEN%1%WHITE%] Start Server%RESET%                          %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%RED%2%WHITE%] Stop Server%RESET%                           %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%CYAN%3%WHITE%] Restart Server%RESET%                         %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%YELLOW%4%WHITE%] Server Status%RESET%                         %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%BLUE%5%WHITE%] Show Logs%RESET%                             %CYAN%║%RESET%
echo %CYAN%║%RESET%     %YELLOW%▶%RESET% %WHITE%[%RED%0%WHITE%] Exit%RESET%                                 %CYAN%║%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.
set /p choice="%BOLD%%WHITE%> Choose option: %RESET%"

if "%choice%"=="1" goto START
if "%choice%"=="2" goto STOP
if "%choice%"=="3" goto RESTART
if "%choice%"=="4" goto STATUS
if "%choice%"=="5" goto LOGS
if "%choice%"=="0" goto EXIT
goto MENU

:START
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %GREEN%▀▄   ▄▀   ▀▄   ▄▀   ▀▄   ▄▀%RESET%                  %CYAN%║%RESET%
echo %CYAN%║%RESET%               %BOLD%%GREEN%STARTING DARK MESSENGER%RESET%                    %CYAN%║%RESET%
echo %CYAN%║%RESET%              %GREEN%▄▀   ▀▄   ▄▀   ▀▄   ▄▀   ▀▄%RESET%                  %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

cd /d "%PROJECT_DIR%"

:: Проверка Nginx
echo %BOLD%%BLUE%[1/3]%RESET% %WHITE%> Checking Nginx...%RESET%
if exist "%NGINX_DIR%\nginx.exe" (
    echo %GREEN%  ✓ Nginx found at %NGINX_DIR%%RESET%
    cd /d "%NGINX_DIR%"
    start /b nginx.exe >nul 2>&1
    echo %GREEN%  ✓ Nginx started%RESET%
) else (
    echo %RED%  ✗ Nginx not found at %NGINX_DIR%\nginx.exe%RESET%
    echo %YELLOW%  ⚠ Continuing without Nginx...%RESET%
)
echo.

:: Активация venv
echo %BOLD%%BLUE%[2/3]%RESET% %WHITE%> Activating environment...%RESET%
if exist "%PROJECT_DIR%\venv\Scripts\activate.bat" (
    call "%PROJECT_DIR%\venv\Scripts\activate.bat"
    echo %GREEN%  ✓ Virtual environment activated%RESET%
) else (
    echo %DIM%  ℹ No virtual environment found%RESET%
)
echo.

:: Запуск сервера
echo %BOLD%%BLUE%[3/3]%RESET% %WHITE%> Starting Waitress server...%RESET%
echo.
echo %YELLOW%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %YELLOW%║%RESET%                                                              %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %BOLD%%GREEN%✨ Server is now RUNNING ✨%RESET%                        %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %DIM%Project: %WHITE%%PROJECT_DIR%%RESET%                              %YELLOW%║%RESET%
echo %YELLOW%║%RESET%     %DIM%Press Ctrl+C to stop the server%RESET%                      %YELLOW%║%RESET%
echo %YELLOW%║%RESET%                                                              %YELLOW%║%RESET%
echo %YELLOW%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

cd /d "%PROJECT_DIR%"

:: Запуск run_win.py в этом же окне
python run_win.py

:: Сюда попадаем после остановки
echo.
echo %RED%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %RED%║%RESET%              %BOLD%%RED%✖ SERVER STOPPED ✖%RESET%                       %RED%║%RESET%
echo %RED%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.
echo %WHITE%Press any key to return to menu...%RESET%
pause >nul
goto MENU

:STOP
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %BOLD%%RED%■ STOPPING SERVER ■%RESET%                       %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

:: Остановка Nginx
echo %BOLD%%RED%[1/2]%RESET% %WHITE%> Stopping Nginx...%RESET%
taskkill /f /im nginx.exe >nul 2>&1
if %errorlevel%==0 (
    echo %GREEN%  ✓ Nginx stopped%RESET%
) else (
    echo %DIM%  ℹ Nginx not running%RESET%
)
echo.

:: Остановка Python
echo %BOLD%%RED%[2/2]%RESET% %WHITE%> Stopping Python server...%RESET%
taskkill /f /im python.exe /fi "WINDOWTITLE eq Dark Messenger*" >nul 2>&1
set "PID_FILE=%PROJECT_DIR%\app.pid"
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    taskkill /f /pid !PID! >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)
taskkill /f /im python.exe >nul 2>&1
echo %GREEN%  ✓ Python stopped%RESET%
echo.
echo %GREEN%✅ Server stopped successfully%RESET%
echo.
echo %WHITE%Press any key to return to menu...%RESET%
pause >nul
goto MENU

:RESTART
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%            %BOLD%%YELLOW%⟳ RESTARTING SERVER ⟳%RESET%                       %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

call :STOP_SILENT
timeout /t 2 /nobreak >nul
goto START

:STOP_SILENT
taskkill /f /im nginx.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
set "PID_FILE=%PROJECT_DIR%\app.pid"
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    taskkill /f /pid !PID! >nul 2>&1
    del "%PID_FILE%" >nul 2>&1
)
exit /b

:STATUS
cls
echo.
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%              %BOLD%%BLUE%ℹ SERVER STATUS ℹ%RESET%                         %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
echo.

:: Проверка Nginx
echo %BOLD%%WHITE%> Nginx:%RESET%
tasklist /fi "imagename eq nginx.exe" 2>nul | find "nginx.exe" >nul
if errorlevel 1 (
    echo   %RED%❌ NOT RUNNING%RESET%
) else (
    echo   %GREEN%✅ RUNNING%RESET%
)

:: Проверка порта 8000
echo.
echo %BOLD%%WHITE%> Waitress (Port 8000):%RESET%
netstat -ano | findstr ":8000.*LISTENING" >nul
if errorlevel 1 (
    echo   %RED%❌ NOT RUNNING%RESET%
) else (
    echo   %GREEN%✅ RUNNING%RESET%
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
echo %CYAN%╔══════════════════════════════════════════════════════════════╗%RESET%
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%║%RESET%  %DIM%Project Dir:%RESET% %WHITE%%PROJECT_DIR%%RESET% %CYAN%║%RESET%
if exist "%PROJECT_DIR%\app.pid" (
    set /p PID=<"%PROJECT_DIR%\app.pid"
    echo %CYAN%║%RESET%  %DIM%PID File:%RESET% %WHITE%!PID!%RESET%                                       %CYAN%║%RESET%
) else (
    echo %CYAN%║%RESET%  %DIM%PID File:%RESET% %RED%Not found%RESET%                                      %CYAN%║%RESET%
)
echo %CYAN%║%RESET%                                                              %CYAN%║%RESET%
echo %CYAN%╚══════════════════════════════════════════════════════════════╝%RESET%
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

if exist "%PROJECT_DIR%\messenger.log" (
    echo %DIM%╔══════════════════════════════════════════════════════════════╗%RESET%
    powershell -Command "Get-Content '%PROJECT_DIR%\messenger.log' -Tail 20"
    echo %DIM%╚══════════════════════════════════════════════════════════════╝%RESET%
) else (
    echo %RED%  ✗ Log file not found: %PROJECT_DIR%\messenger.log%RESET%
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
exit