# passenger_wsgi.py
# Entry point для Reg.ru + Passenger

import sys
import os

# === Путь к Python в вашем venv (ПРОВЕРЬТЕ!) ===
INTERP = "/var/www/u3498810/data/www/blockchat.ru/venv/bin/python"

if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# === Добавляем путь к приложению ===
app_dir = os.path.dirname(__file__)
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# === Переменные окружения для Flask ===
os.environ['FLASK_ENV'] = 'production'
os.environ['SCRIPT_NAME'] = ''
os.environ['PATH_INFO'] = ''

# === Импорт приложения ===
from app import app as application

# === Настройки для продакшена ===
application.config['DEBUG'] = False
application.config['TESTING'] = False