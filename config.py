"""
config.py — Централизованная конфигурация приложения
"""
import os
import sys
import secrets
import logging

try:
    from dotenv import load_dotenv
    import pathlib
    load_dotenv(dotenv_path=pathlib.Path(__file__).parent / '.env', override=False)
except ImportError:
    pass

# === Основные настройки ===
CONFIG = {
    'POW_DIFFICULTY':       int(os.getenv('POW_DIFFICULTY', 2)),
    'POW_MAX_ITERATIONS':   int(os.getenv('POW_MAX_ITERATIONS', 2_000_000)),
    'CACHE_SIZE_KEYS':      128,
    'CACHE_SIZE_GROUPS':    32,
    'CACHE_SIZE_CONTACTS':  64,
    'CACHE_SIZE_PUBKEYS':   256,
    'DB_TIMEOUT':           30.0,
    'SESSION_LIFETIME':     int(os.getenv('PERMANENT_SESSION_LIFETIME', 31_536_000)),
    'LOG_MAX_BYTES':        10 * 1024 * 1024,
    'LOG_BACKUP_COUNT':     5,
    'MAX_UPLOAD_SIZE':      16 * 1024 * 1024,
}

# === Пути ===
DATABASE_PATH = os.getenv('DATABASE_PATH', 'blockchain.db')
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')
STATIC_FOLDER  = 'static'
TEMPLATE_FOLDER = 'templates'

if sys.platform == 'win32':
    if DATABASE_PATH.startswith('/var/www/'):
        DATABASE_PATH = 'blockchain.db'
    if UPLOAD_FOLDER.startswith('/var/www/'):
        UPLOAD_FOLDER = 'uploads'

os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)) or '.', exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# === Кошелёк / монеты ===
COIN          = 1_000_000   # 1 монета = 1 000 000 сатоши
COIN_NAME     = "BlockCoin"
TRANSFER_FEE  = 10_000      # 0.01 BlockCoin
MIN_BALANCE   = 0

# === Аирдроп ===
AIRDROP_AMOUNT = 100_000    # 0.1 BlockCoin

# === Стейкинг ===
MIN_STAKE_AMOUNT  = 10 * COIN
STAKE_LOCK_BLOCKS = 100

# === Майнинг и эмиссия ===
BLOCK_REWARD      = 0.1 * COIN
POOL_FEE_PERCENT  = 10

# === Лотерея ===
LOTTERY_INTERVAL  = 3600

# === НЕЛИНЕЙНЫЙ ВЕС ДЛЯ СТЕЙКИНГА ===
STAKE_WEIGHT_POWER = 0.5          # 1.0 = линейный (сумма * возраст), 0.5 = квадратный корень
MAX_WEIGHT_PER_ADDRESS = None     # например, 10_000_000_000 или None для отключения капа

# === Лотерея ===
LOTTERY_INTERVAL  = 1800
LOTTERY_INITIAL_REWARD = 100 * COIN   # сколько BlockCoin разыгрывается изначально
LOTTERY_HALVING_INTERVAL = 1000      # через сколько розыгрышей награда уменьшается вдвое

# === Секретный ключ ===
SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    SECRET_KEY = secrets.token_hex(32)
    logging.warning("❌ SECRET_KEY NOT FOUND in env! Sessions will reset on restart!")
else:
    if os.getenv('FLASK_ENV') != 'production':
        logging.warning("✅ SECRET_KEY loaded from .env")

MAX_CONTENT_LENGTH = CONFIG['MAX_UPLOAD_SIZE']