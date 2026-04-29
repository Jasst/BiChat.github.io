import sys
import os
import logging

# === Путь к venv Python (ОБЯЗАТЕЛЬНО — Passenger иначе берёт системный Python) ===
INTERP = "/var/www/u3498810/data/www/blockchat.ru/venv/bin/python"
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# === Добавляем папку приложения в sys.path ===
APP_DIR = "/var/www/u3498810/data/www/blockchat.ru"
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# === Логирование Passenger (до импорта app) ===
logging.basicConfig(
    filename=os.path.join(APP_DIR, 'passenger_error.log'),
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# 🔐 ЗАГРУЗКА .env — вручную, без зависимостей
# Делаем ЭТО до импорта app.py, чтобы все os.getenv() внутри получили значения
# =============================================================================
ENV_FILE = os.path.join(APP_DIR, '.env')

if os.path.exists(ENV_FILE):
    logger.info(f"Loading .env from {ENV_FILE}")
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip()
            # Убираем кавычки
            if len(value) >= 2:
                if (value[0] == '"' and value[-1] == '"') or \
                   (value[0] == "'" and value[-1] == "'"):
                    value = value[1:-1]
            # Не перезаписываем уже установленные системные переменные
            if key and key not in os.environ:
                os.environ[key] = value
    logger.info(".env loaded successfully")
else:
    logger.warning(f"⚠️ .env not found at {ENV_FILE}")

# === Принудительно выставляем продакшен-режим ===
os.environ.setdefault('FLASK_ENV', 'production')
os.environ.setdefault('FLASK_DEBUG', '0')

# =============================================================================
# === Импорт Flask-приложения (ПОСЛЕ загрузки .env!) ===
# =============================================================================
try:
    from app import app as application
    application.config['DEBUG'] = False
    application.config['TESTING'] = False
    logger.info("✅ Application imported successfully")
except Exception as e:
    logger.error(f"❌ Failed to import app: {e}", exc_info=True)
    raise