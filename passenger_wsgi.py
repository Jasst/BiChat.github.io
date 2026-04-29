# passenger_wsgi.py
# Entry point для Reg.ru + Passenger

import sys
import os
import logging

# === Настройка логирования ===
logging.basicConfig(
    filename='/var/www/u3498810/data/www/blockchat.ru/passenger_error.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# === Путь к Python в вашем venv ===
INTERP = "/var/www/u3498810/data/www/blockchat.ru/venv/bin/python"

if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# === Добавляем путь к приложению ===
app_dir = os.path.dirname(__file__)
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

# =============================================================================
# 🔐 ЗАГРУЗКА .env — ДОБАВЛЕНО (этого не хватало!)
# =============================================================================
ENV_FILE = '/var/www/u3498810/data/www/blockchat.ru/.env'

if os.path.exists(ENV_FILE):
    logger.info(f"Loading env from {ENV_FILE}")
    with open(ENV_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            # Пропускаем комментарии и пустые строки
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip()
                # Убираем кавычки если есть
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                os.environ[key] = value
                logger.debug(f"Set env: {key}=***")
else:
    logger.warning(f"⚠️ .env file not found at {ENV_FILE}")

# =============================================================================

# === Переменные окружения для Flask ===
os.environ.setdefault('FLASK_ENV', 'production')
os.environ['SCRIPT_NAME'] = ''
os.environ['PATH_INFO'] = ''

# === Импорт приложения (ТЕПЕРЬ с загруженными переменными) ===
try:
    from app import app as application

    logger.info("✅ App imported successfully")

    # === Настройки для продакшена ===
    application.config['DEBUG'] = False
    application.config['TESTING'] = False

except Exception as e:
    logger.error(f"❌ Failed to import app: {e}", exc_info=True)
    raise