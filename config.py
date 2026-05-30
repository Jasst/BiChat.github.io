"""
config.py — Централизованная конфигурация приложения
"""
import os
import sys
import secrets
import logging
from pathlib import Path

try:
    from dotenv import load_dotenv
    import pathlib
    load_dotenv(dotenv_path=pathlib.Path(__file__).parent / '.env', override=False)
except ImportError:
    pass

CONFIG = {
    'POW_DIFFICULTY':       int(os.getenv('POW_DIFFICULTY', 6)),
    'POW_MAX_ITERATIONS':   int(os.getenv('POW_MAX_ITERATIONS', 100_000_000)),
    'CACHE_SIZE_KEYS':      128,
    'CACHE_SIZE_GROUPS':    32,
    'CACHE_SIZE_CONTACTS':  64,
    'CACHE_SIZE_PUBKEYS':   256,
    'DB_TIMEOUT':           30.0,
    'DB_POOL_SIZE':         int(os.getenv('DB_POOL_SIZE', 10)),
    'SESSION_LIFETIME':     int(os.getenv('PERMANENT_SESSION_LIFETIME', 31_536_000)),
    'LOG_MAX_BYTES':        10 * 1024 * 1024,
    'LOG_BACKUP_COUNT':     5,
    'LOG_LEVEL':            os.getenv('LOG_LEVEL', 'INFO').upper(),
    'MAX_UPLOAD_SIZE':      16 * 1024 * 1024,
    'RATE_LIMIT_PER_MINUTE':         int(os.getenv('RATE_LIMIT_PER_MINUTE', 60)),
    'RATE_LIMIT_MESSAGE_PER_MINUTE': int(os.getenv('RATE_LIMIT_MESSAGE_PER_MINUTE', 30)),
    'RATE_LIMIT_API_PER_MINUTE':     int(os.getenv('RATE_LIMIT_API_PER_MINUTE', 120)),
    'LONG_POLLING_TIMEOUT':  int(os.getenv('LONG_POLLING_TIMEOUT', 25)),
    'LONG_POLLING_MAX_WAIT': int(os.getenv('LONG_POLLING_MAX_WAIT', 30)),
}

DB_POOL_SIZE = CONFIG['DB_POOL_SIZE']
DB_TIMEOUT   = CONFIG['DB_TIMEOUT']

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)

# ---------- PostgreSQL ----------
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:pass@localhost/bichat')
# Для обратной совместимости (можно удалить позже)
DATABASE_PATH = None

UPLOAD_FOLDER   = os.getenv('UPLOAD_FOLDER', str(BASE_DIR / 'uploads'))
STATIC_FOLDER   = str(BASE_DIR / 'static')
TEMPLATE_FOLDER = str(BASE_DIR / 'templates')

if sys.platform == 'win32':
    if DATABASE_PATH and DATABASE_PATH.startswith('/var/www/'):
        DATABASE_PATH = None
    if UPLOAD_FOLDER.startswith('/var/www/'):
        UPLOAD_FOLDER = str(BASE_DIR / 'uploads')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

COIN          = 1000000
COIN_NAME     = "BlockCoin"
TRANSFER_FEE  = int(os.getenv('TRANSFER_FEE', 50000))
MESSAGE_FEE = int(os.getenv('MESSAGE_FEE', 100))
MIN_BALANCE   = 0

AIRDROP_AMOUNT  = int(os.getenv('AIRDROP_AMOUNT', 1000))

MIN_STAKE_AMOUNT  = int(os.getenv('MIN_STAKE_AMOUNT', 10 * COIN))
STAKE_LOCK_BLOCKS = int(os.getenv('STAKE_LOCK_BLOCKS', 100))
BLOCK_REWARD = int(os.getenv('BLOCK_REWARD', 0.1*COIN))
# config.py – добавить в конец
STAKING_FEE_FROM_BLOCK_REWARD = float(os.getenv('STAKING_FEE_FROM_BLOCK_REWARD', 0.1))  # 10% от награды за блок

ENABLE_MINING  = os.getenv('ENABLE_MINING', '1') == '1'
ENABLE_STAKING = os.getenv('ENABLE_STAKING', '1') == '1'

STAKING_FEE_POOL_ADDRESS = 'staking_fee_pool'

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    SECRET_KEY = secrets.token_hex(32)
    logging.warning("SECRET_KEY NOT FOUND in env! Sessions will reset on restart!")

MAX_CONTENT_LENGTH = CONFIG['MAX_UPLOAD_SIZE']
MAX_SUPPLY = 21_000_000

ARCHIVE_OLD_MESSAGES_DAYS = int(os.getenv('ARCHIVE_OLD_MESSAGES_DAYS', 90))
ARCHIVE_ENABLED = os.getenv('ARCHIVE_ENABLED', '1') == '1'
FTS_ENABLED = os.getenv('FTS_ENABLED', '1') == '1'

MAX_MESSAGE_PAYLOAD_SIZE = int(os.getenv('MAX_MESSAGE_PAYLOAD_SIZE', 65536))

ONLINE_TIMEOUT_SECONDS = int(os.getenv('ONLINE_TIMEOUT_SECONDS', 60))
ARCHIVE_BATCH_SIZE = int(os.getenv('ARCHIVE_BATCH_SIZE', 1000))
MINING_CHALLENGE_TTL = int(os.getenv('MINING_CHALLENGE_TTL', 60))