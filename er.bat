@echo off
echo ========================================
echo   Fixing Quart dependencies
echo ========================================

cd /d C:\Users\PC\Documents\GitHub\BiChat.github.io

echo Activating venv...
call .venv\Scripts\activate.bat

echo Upgrading pip...
python -m pip install --upgrade pip

echo Uninstalling old versions...
pip uninstall flask quart -y 2>nul

echo Installing compatible versions...
pip install flask==2.3.3
pip install quart==0.19.4
pip install quart-cors==0.6.0
pip install hypercorn==0.14.3
pip install asyncpg redis cryptography python-dotenv werkzeug jinja2

echo.
echo ========================================
echo   Done! Now try running:
echo   python app_async.py
echo ========================================
pause