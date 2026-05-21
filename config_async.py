"""config_async.py — Конфигурация для высоконагруженного асинхронного сервера"""

import os
import secrets
import logging
from pathlib import Path

# =============================================================================
# ЗАГРУЗКА .env
# =============================================================================
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / '.env')
except ImportError:
    pass

# =============================================================================
# БАЗА ДАННЫХ (PostgreSQL + asyncpg)
# =============================================================================
POSTGRES_HOST = os.getenv('POSTGRES_HOST', 'localhost')
POSTGRES_PORT = int(os.getenv('POSTGRES_PORT', 5432))
POSTGRES_DB = os.getenv('POSTGRES_DB', 'messenger')
POSTGRES_USER = os.getenv('POSTGRES_USER', 'messenger')
POSTGRES_PASSWORD = os.getenv('POSTGRES_PASSWORD', 'secure_password_here')

# Строка подключения
DATABASE_DSN = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Пул соединений
DB_POOL_MIN_SIZE = int(os.getenv('DB_POOL_MIN_SIZE', 10))
DB_POOL_MAX_SIZE = int(os.getenv('DB_POOL_MAX_SIZE', 50))
DB_POOL_MAX_QUERIES = int(os.getenv('DB_POOL_MAX_QUERIES', 50000))
DB_POOL_MAX_INACTIVE = int(os.getenv('DB_POOL_MAX_INACTIVE', 300))
DB_COMMAND_TIMEOUT = int(os.getenv('DB_COMMAND_TIMEOUT', 60))

# =============================================================================
# REDIS
# =============================================================================
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_DB = int(os.getenv('REDIS_DB', 0))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None)

# Формируем URL для Redis
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
if REDIS_PASSWORD:
    REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# Максимальное количество соединений Redis
REDIS_MAX_CONNECTIONS = int(os.getenv('REDIS_MAX_CONNECTIONS', 50))

# Настройки кэша (TTL в секундах)
CACHE_TTL = {
    'balance': int(os.getenv('CACHE_TTL_BALANCE', 30)),      # баланс
    'contacts': int(os.getenv('CACHE_TTL_CONTACTS', 60)),    # контакты
    'groups': int(os.getenv('CACHE_TTL_GROUPS', 30)),        # группы
    'pubkey': int(os.getenv('CACHE_TTL_PUBKEY', 3600)),      # публичные ключи
    'nonce': int(os.getenv('CACHE_TTL_NONCE', 300)),         # nonce для входа
}

# =============================================================================
# БЛОКЧЕЙН И КОИНЫ
# =============================================================================
COIN = 1_000_000                      # 1 монета = 1 000 000 сатоши
COIN_NAME = os.getenv('COIN_NAME', "BlockCoin")
TRANSFER_FEE = int(os.getenv('TRANSFER_FEE', 50_000))        # комиссия за перевод
MESSAGE_FEE = int(os.getenv('MESSAGE_FEE', 100))             # плата за сообщение
AIRDROP_AMOUNT = int(os.getenv('AIRDROP_AMOUNT', 10_00))     # аирдроп при регистрации
BLOCK_REWARD = int(os.getenv('BLOCK_REWARD', 100_000))       # награда за блок

# =============================================================================
# СТЕЙКИНГ
# =============================================================================
MIN_STAKE_AMOUNT = int(os.getenv('MIN_STAKE_AMOUNT', 10 * COIN))   # минимальный стейк
STAKE_LOCK_BLOCKS = int(os.getenv('STAKE_LOCK_BLOCKS', 100))       # блоков блокировки
STAKING_FEE_POOL_ADDRESS = os.getenv('STAKING_FEE_POOL_ADDRESS', 'staking_fee_pool')
REWARD_PRECISION = 10**12  # точность для расчётов стейкинга

# =============================================================================
# МАЙНИНГ (Proof-of-Work)
# =============================================================================
POW_DIFFICULTY = int(os.getenv('POW_DIFFICULTY', 4))                # сложность (число нулей)
POW_MAX_ITERATIONS = int(os.getenv('POW_MAX_ITERATIONS', 1_000_000)) # макс попыток
ENABLE_MINING = os.getenv('ENABLE_MINING', '1') == '1'              # включить майнинг
ENABLE_STAKING = os.getenv('ENABLE_STAKING', '1') == '1'            # включить стейкинг

# =============================================================================
# ЭМИССИЯ
# =============================================================================
MAX_SUPPLY = int(os.getenv('MAX_SUPPLY', 21_000_000 * COIN)) if os.getenv('MAX_SUPPLY') else None

# =============================================================================
# СЕРВЕР (Hypercorn / Quart)
# =============================================================================
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    SECRET_KEY = secrets.token_hex(32)
    logging.warning("⚠️ SECRET_KEY not set! Generated random key. Sessions will reset on restart!")
else:
    logging.info("✅ SECRET_KEY loaded")

# Настройки сессии
SESSION_TTL = int(os.getenv('SESSION_TTL', 86400))           # 24 часа
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '1') == '1'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Long polling
LONG_POLLING_TIMEOUT = int(os.getenv('LONG_POLLING_TIMEOUT', 25))      # таймаут ожидания
LONG_POLLING_MAX_WAIT = int(os.getenv('LONG_POLLING_MAX_WAIT', 30))    # максимум ожидания
MAX_MESSAGES_PER_POLL = int(os.getenv('MAX_MESSAGES_PER_POLL', 50))    # сообщений за раз

# =============================================================================
# RATE LIMITING (Redis-based)
# =============================================================================
RATE_LIMIT_REQUESTS = int(os.getenv('RATE_LIMIT_REQUESTS', 60))        # запросов в минуту
RATE_LIMIT_MESSAGES = int(os.getenv('RATE_LIMIT_MESSAGES', 30))        # сообщений в минуту
RATE_LIMIT_API = int(os.getenv('RATE_LIMIT_API', 120))                 # API запросов в минуту
RATE_LIMIT_LOGIN = int(os.getenv('RATE_LIMIT_LOGIN', 10))              # попыток входа в минуту
RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', 60))            # окно в секундах

# =============================================================================
# ЛОГИРОВАНИЕ
# =============================================================================
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_MAX_BYTES = int(os.getenv('LOG_MAX_BYTES', 10 * 1024 * 1024))      # 10 MB
LOG_BACKUP_COUNT = int(os.getenv('LOG_BACKUP_COUNT', 5))
LOG_FORMAT = os.getenv('LOG_FORMAT', '%(asctime)s %(levelname)s [%(name)s] %(message)s')

# =============================================================================
# ЗАГРУЗКА ФАЙЛОВ
# =============================================================================
MAX_UPLOAD_SIZE = int(os.getenv('MAX_UPLOAD_SIZE', 16 * 1024 * 1024))   # 16 MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov'}

# =============================================================================
# ПУТИ К ПАПКАМ
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
UPLOAD_FOLDER = Path(os.getenv('UPLOAD_FOLDER', BASE_DIR / 'uploads'))
STATIC_FOLDER = BASE_DIR / 'static'
TEMPLATE_FOLDER = BASE_DIR / 'templates'

# Создаём необходимые папки
DATA_DIR.mkdir(exist_ok=True)
UPLOAD_FOLDER.mkdir(exist_ok=True)
STATIC_FOLDER.mkdir(exist_ok=True)
TEMPLATE_FOLDER.mkdir(exist_ok=True)

# =============================================================================
# ОСТАЛЬНЫЕ НАСТРОЙКИ
# =============================================================================
ONLINE_TIMEOUT = int(os.getenv('ONLINE_TIMEOUT', 60))                  # секунд оффлайн
MAX_GROUP_MEMBERS = int(os.getenv('MAX_GROUP_MEMBERS', 50))            # макс участников в группе
MAX_CONTACT_NAME_LENGTH = int(os.getenv('MAX_CONTACT_NAME_LENGTH', 50))
MAX_GROUP_NAME_LENGTH = int(os.getenv('MAX_GROUP_NAME_LENGTH', 100))

# =============================================================================
# ПРОВЕРКА ОБЯЗАТЕЛЬНЫХ ПАРАМЕТРОВ
# =============================================================================
if not POSTGRES_PASSWORD or POSTGRES_PASSWORD == 'secure_password_here':
    logging.warning("⚠️ Using default PostgreSQL password! Change it in .env file!")

if REDIS_PASSWORD is None:
    logging.warning("⚠️ Redis password not set! Consider setting REDIS_PASSWORD for security!")

# =============================================================================
# ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ (с импортами из старого config.py)
# =============================================================================
CONFIG = {
    'POW_DIFFICULTY': POW_DIFFICULTY,
    'POW_MAX_ITERATIONS': POW_MAX_ITERATIONS,
    'DB_TIMEOUT': 30,
    'DB_POOL_SIZE': DB_POOL_MAX_SIZE,
    'SESSION_LIFETIME': SESSION_TTL,
    'LOG_MAX_BYTES': LOG_MAX_BYTES,
    'LOG_BACKUP_COUNT': LOG_BACKUP_COUNT,
    'MAX_UPLOAD_SIZE': MAX_UPLOAD_SIZE,
    'RATE_LIMIT_PER_MINUTE': RATE_LIMIT_REQUESTS,
    'RATE_LIMIT_MESSAGE_PER_MINUTE': RATE_LIMIT_MESSAGES,
    'RATE_LIMIT_API_PER_MINUTE': RATE_LIMIT_API,
    'LONG_POLLING_TIMEOUT': LONG_POLLING_TIMEOUT,
    'LONG_POLLING_MAX_WAIT': LONG_POLLING_MAX_WAIT,
    'CACHE_SIZE_KEYS': 1000,
    'CACHE_SIZE_GROUPS': 500,
    'CACHE_SIZE_CONTACTS': 1000,
    'CACHE_SIZE_PUBKEYS': 2000,
}

DATABASE_PATH = str(DATA_DIR / 'blockchain.db')  # для обратной совместимости
MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE

# =============================================================================
# ИНФОРМАЦИЯ О ПЛАТФОРМЕ
# =============================================================================
import platform
IS_WINDOWS = platform.system() == 'Windows'
IS_WSL = 'microsoft' in platform.uname().release.lower() if hasattr(platform, 'uname') else False
IS_PRODUCTION = os.getenv('FLASK_ENV') == 'production' or os.getenv('QUART_ENV') == 'production'

# =============================================================================
# ВЫВОД ИНФОРМАЦИИ ПРИ ЗАГРУЗКЕ
# =============================================================================
if __name__ != '__main__':  # не выводим при импорте в тестах
    logging.info(f"📁 Config loaded from: {BASE_DIR}")
    logging.info(f"🐘 PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    logging.info(f"⚡ Redis: {REDIS_HOST}:{REDIS_PORT}")
    logging.info(f"⛏️ Mining: {'ON' if ENABLE_MINING else 'OFF'}, Difficulty: {POW_DIFFICULTY}")
    logging.info(f"💰 Staking: {'ON' if ENABLE_STAKING else 'OFF'}")