"""
app.py — Децентрализованный мессенджер с безопасным шифрованием
Версия: 3.4 (оптимизации: WAL, кэш-версионирование, производительность)
"""
import hashlib
import os
import hmac
import base64
import logging
import logging.handlers
import sqlite3
import time
import json
import uuid
import threading
import secrets
from functools import lru_cache, wraps
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import timedelta

from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory, g
from flask.sessions import SecureCookieSessionInterface
from mnemonic import Mnemonic
from marshmallow import Schema, fields, ValidationError, post_load
from werkzeug.utils import secure_filename

from crypto_manager import (
    encrypt_hybrid, decrypt_hybrid, get_public_key_b64, load_public_key_from_b64,
    compute_shared_key_b64, generate_symmetric_key, encrypt_message_aead, decrypt_message_aead,
    generate_address, generate_address_from_pubkey, verify_address_matches_pubkey,
    clear_key_cache, get_cache_info
)


# 🔧 Загрузка переменных из .env (для локальной разработки)
try:
    from dotenv import load_dotenv
    import pathlib
    # Ищем .env рядом с app.py, независимо от рабочей директории
    _env_path = pathlib.Path(__file__).parent / '.env'
    load_dotenv(dotenv_path=_env_path, override=False)
except ImportError:
    pass

# === Конфигурация ===
CONFIG = {
    'POW_DIFFICULTY': int(os.getenv('POW_DIFFICULTY', 2)),
    'POW_MAX_ITERATIONS': int(os.getenv('POW_MAX_ITERATIONS', 2_000_000)),
    'CACHE_SIZE_KEYS': 128,
    'CACHE_SIZE_GROUPS': 32,
    'CACHE_SIZE_CONTACTS': 64,
    'CACHE_SIZE_PUBKEYS': 256,
    'DB_TIMEOUT': 30.0,
    'SESSION_LIFETIME': int(os.getenv('PERMANENT_SESSION_LIFETIME', 31536000)),
    'LOG_MAX_BYTES': 10 * 1024 * 1024,
    'LOG_BACKUP_COUNT': 5,
    'MAX_UPLOAD_SIZE': 16 * 1024 * 1024,
}

# 🔧 Пути из .env или дефолты
DATABASE_PATH = os.getenv('DATABASE_PATH', 'blockchain.db')
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')

# 🔧 Адаптация путей под ОС
import sys
if sys.platform == 'win32':
    if DATABASE_PATH.startswith('/var/www/'):
        DATABASE_PATH = 'blockchain.db'
    if UPLOAD_FOLDER.startswith('/var/www/'):
        UPLOAD_FOLDER = 'uploads'

# 🔧 Создаём директории
os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)) or '.', exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
STATIC_FOLDER = 'static'
TEMPLATE_FOLDER = 'templates'

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    SECRET_KEY = secrets.token_hex(32)
    logging.warning("❌ SECRET_KEY NOT FOUND in env! Sessions will reset on restart!")
else:
    if os.getenv('FLASK_ENV') != 'production':
        logging.warning("✅ SECRET_KEY loaded from .env")

MAX_CONTENT_LENGTH = CONFIG['MAX_UPLOAD_SIZE']

# =============================================================================
# === Глобальные переменные для версионирования кэша ===
# =============================================================================
_pubkey_cache_version = 0
_pubkey_version_lock = threading.Lock()
_contact_cache_version = 0
_contact_version_lock = threading.Lock()
_groups_cache_version = 0
_groups_version_lock = threading.Lock()

# =============================================================================
# === Логирование ===
# =============================================================================
def setup_logging():
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'messenger.log')
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=CONFIG['LOG_MAX_BYTES'],
        backupCount=CONFIG['LOG_BACKUP_COUNT'],
        encoding='utf-8',
        delay=True
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    is_prod = os.getenv('FLASK_ENV') == 'production'
    log_level = logging.WARNING if is_prod else logging.INFO
    handlers = [file_handler] if is_prod else [file_handler, console_handler]
    logging.basicConfig(level=log_level, handlers=handlers, force=True)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlite3').setLevel(logging.ERROR)
    logging.getLogger('cryptography').setLevel(logging.WARNING)
    logging.getLogger(__name__).warning(f"=== App started, log path: {log_path} ===")

setup_logging()
logger = logging.getLogger(__name__)


# =============================================================================
# === Оптимизация SQLite: WAL + PRAGMA ===
# =============================================================================
def init_sqlite_optimizations(db_path: str) -> None:
    """
    Применяет PRAGMA-настройки для повышения производительности.
    Вызывается один раз при старте приложения.
    """
    try:
        conn = sqlite3.connect(db_path, timeout=CONFIG['DB_TIMEOUT'])
        cursor = conn.cursor()
        cursor.executescript("""
            PRAGMA journal_mode = WAL;
            PRAGMA synchronous = NORMAL;
            PRAGMA cache_size = -64000;
            PRAGMA temp_store = MEMORY;
            PRAGMA busy_timeout = 30000;
            PRAGMA foreign_keys = OFF;
        """)
        cursor.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        logger.info(f"✅ SQLite journal_mode: {mode.upper()}")
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to apply SQLite optimizations: {e}")


def warmup_database(db_path: str) -> None:
    """Прогрев БД: создаёт WAL-файлы и проверяет подключение."""
    try:
        with get_db_cursor(db_path) as cursor:
            cursor.execute("SELECT 1")
        logger.debug("✅ Database warmed up")
    except Exception as e:
        logger.warning(f"⚠️ Database warmup skipped: {e}")


# =============================================================================
# === Утилиты БД с PRAGMA на каждое соединение ===
# =============================================================================
@contextmanager
def get_db_cursor(db_path: str):
    conn = None
    try:
        conn = sqlite3.connect(
            db_path,
            timeout=CONFIG['DB_TIMEOUT'],
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        # Применяем настройки для ЭТОГО соединения
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        cursor.execute("PRAGMA cache_size = -64000")
        yield cursor
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn:
            conn.close()


# =============================================================================
# === Функции управления версиями кэша ===
# =============================================================================
# =============================================================================
# === Функции управления версиями кэша ===
# =============================================================================
def bump_pubkey_cache_version() -> None:
    global _pubkey_cache_version
    with _pubkey_version_lock:
        _pubkey_cache_version += 1
        logger.debug(f"🔄 Pubkey cache version bumped to {_pubkey_cache_version}")

def get_pubkey_cache_version() -> int:
    with _pubkey_version_lock:
        return _pubkey_cache_version

# ✅ ДОБАВЬТЕ ЭТИ ДВЕ ФУНКЦИИ:
def bump_contact_cache_version() -> None:
    global _contact_cache_version
    with _contact_version_lock:
        _contact_cache_version += 1

def get_contact_cache_version() -> int:  # ← БЫЛА ПРОПУЩЕНА!
    with _contact_version_lock:
        return _contact_cache_version

def bump_groups_cache_version() -> None:
    global _groups_cache_version
    with _groups_version_lock:
        _groups_cache_version += 1

def get_groups_cache_version() -> int:  # ← БЫЛА ПРОПУЩЕНА!
    with _groups_version_lock:
        return _groups_cache_version


# =============================================================================
# === Создание таблиц ===
# =============================================================================
def _create_contacts_table(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_address TEXT NOT NULL, contact_address TEXT NOT NULL,
        contact_name TEXT NOT NULL, contact_pubkey TEXT, created_at REAL,
        UNIQUE(user_address, contact_address)
    )''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)')

def _create_group_table(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, creator TEXT NOT NULL,
        members TEXT NOT NULL, created_at REAL
    )''')

def _create_pubkey_cache_table(cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pubkey_cache (
            address TEXT PRIMARY KEY, 
            public_key_b64 TEXT NOT NULL,
            updated_at REAL, 
            source TEXT DEFAULT 'blockchain',
            verified INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_updated ON pubkey_cache(updated_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_verified ON pubkey_cache(verified)')


# =============================================================================
# === Blockchain ===
# =============================================================================
class Blockchain:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._init_lock = threading.Lock()
        self.initialize_blockchain()
        logger.info("Blockchain initialized")

    def initialize_blockchain(self) -> None:
        with self._init_lock:
            with get_db_cursor(self.db_path) as cursor:
                self._create_tables(cursor)
                self._create_indexes(cursor)
                if not self._get_chain_raw(cursor):
                    self._new_block_raw(cursor, previous_hash='1', proof=100)
                    logger.info("Genesis block created")

    def _create_tables(self, cursor):
        cursor.execute('''CREATE TABLE IF NOT EXISTS blockchain (
            block_index INTEGER PRIMARY KEY, timestamp REAL,
            transactions TEXT, proof INTEGER, previous_hash TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL,
            recipient TEXT NOT NULL, content TEXT, image TEXT,
            timestamp REAL, sender_pubkey TEXT, metadata TEXT
        )''')
        _create_contacts_table(cursor)
        _create_group_table(cursor)
        _create_pubkey_cache_table(cursor)

    def _create_indexes(self, cursor):
        for sql in [
            'CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)',
        ]: cursor.execute(sql)

    def _new_block_raw(self, cursor, proof: int, previous_hash: Optional[str] = None) -> None:
        last = self._last_block_raw(cursor)
        block_index = last.get('index', 0) + 1
        block = {
            'index': block_index, 'timestamp': time.time(),
            'transactions': [], 'proof': proof,
            'previous_hash': previous_hash or self._hash_block(last),
        }
        cursor.execute(
            'INSERT INTO blockchain (block_index, timestamp, transactions, proof, previous_hash) VALUES (?, ?, ?, ?, ?)',
            (block['index'], block['timestamp'], json.dumps(block['transactions']),
             block['proof'], block['previous_hash'])
        )

    def _hash_block(self, block: Dict[str, Any]) -> str:
        if not block: return '0' * 64
        return hashlib.sha256(json.dumps(block, sort_keys=True).encode()).hexdigest()

    def _last_block_raw(self, cursor) -> Dict[str, Any]:
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            return {'index': row[0], 'timestamp': row[1], 'transactions': json.loads(row[2]),
                    'proof': row[3], 'previous_hash': row[4]}
        return {}

    def _get_chain_raw(self, cursor) -> List[Dict[str, Any]]:
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        return [{'index': r[0], 'timestamp': r[1], 'transactions': json.loads(r[2]),
                 'proof': r[3], 'previous_hash': r[4]} for r in cursor.fetchall()]

    def new_transaction(self, cursor, sender: str, recipient: str, content: str,
                        image: Optional[str] = None, sender_pubkey: Optional[str] = None,
                        metadata: Optional[Dict] = None) -> int:
        cursor.execute(
            'INSERT INTO transactions (sender, recipient, content, image, timestamp, sender_pubkey, metadata) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (sender, recipient, content, image, time.time(),
             sender_pubkey, json.dumps(metadata) if metadata else None)
        )
        return cursor.lastrowid

    def proof_of_work(self, last_proof: int) -> int:
        proof = 0
        target = "0" * CONFIG['POW_DIFFICULTY']
        while proof < CONFIG['POW_MAX_ITERATIONS']:
            if hashlib.sha256(f'{last_proof}{proof}'.encode()).hexdigest()[:CONFIG['POW_DIFFICULTY']] == target:
                return proof
            proof += 1
        raise RuntimeError(f"PoW failed after {CONFIG['POW_MAX_ITERATIONS']} iterations")


# =============================================================================
# === Фоновый майнинг ===
# =============================================================================
_pow_lock = threading.Lock()

def _mine_block_async(db_path: str, last_proof: int) -> None:
    """PoW в отдельном потоке — пользователь не ждёт."""
    if not _pow_lock.acquire(blocking=False):
        logger.debug("PoW already running, skipping")
        return
    try:
        proof = blockchain.proof_of_work(last_proof)
        with get_db_cursor(db_path) as cursor:
            blockchain._new_block_raw(cursor, proof)
        logger.debug(f"Block mined in background, proof={proof}")
    except Exception as e:
        logger.error(f"Async PoW failed: {e}")
    finally:
        _pow_lock.release()


_p2p_buffer: Dict[str, List[Dict]] = {}
_p2p_buffer_lock = threading.Lock()


# =============================================================================
# === Flask app ===
# =============================================================================
app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='__Secure-session',
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=CONFIG['SESSION_LIFETIME']),
)
app.session_interface = SecureCookieSessionInterface()

mnemonic_gen = Mnemonic('english')

# 🔧 Применяем оптимизации БД ПЕРЕД инициализацией блокчейна
init_sqlite_optimizations(DATABASE_PATH)
blockchain = Blockchain(DATABASE_PATH)
warmup_database(DATABASE_PATH)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# =============================================================================
# === Схемы валидации ===
# =============================================================================
class WalletSchema(Schema):
    mnemonic_phrase = fields.Str(required=True, load_only=True, validate=lambda x: len(x.strip()) >= 24)
    @post_load
    def strip(self, data, **kwargs):
        data['mnemonic_phrase'] = data['mnemonic_phrase'].strip()
        return data

class MessageSchema(Schema):
    recipient = fields.Str(required=True, validate=lambda x: len(x) == 64 or x.startswith('group:'))
    content = fields.Str(required=True, allow_none=False)
    image = fields.Str(allow_none=True)
    message_type = fields.Str(load_default='direct', validate=lambda x: x in ('direct', 'group'))
    group_id = fields.Str(allow_none=True)

class GroupSchema(Schema):
    name = fields.Str(required=True, validate=lambda x: 1 <= len(x.strip()) <= 100)
    members = fields.List(fields.Str(), required=True, validate=lambda x: 1 <= len(x) <= 50)

class ContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name = fields.Str(required=True, validate=lambda x: 1 <= len(x) <= 50)

class EditContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name = fields.Str(required=True, validate=lambda x: 1 <= len(x.strip()) <= 50)
    @post_load
    def strip_fields(self, data, **kwargs):
        data['name'] = data['name'].strip()
        data['address'] = data['address'].strip().lower()
        return data

class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True, validate=lambda x: x > 0)


# =============================================================================
# === Кэш публичных ключей (с версионированием) ===
# =============================================================================
@lru_cache(maxsize=CONFIG['CACHE_SIZE_PUBKEYS'])
def get_cached_public_key(address: str, cache_version: int = 0) -> Optional[Tuple[str, bool]]:
    """
    Возвращает (pubkey_b64, is_verified).
    Параметр cache_version позволяет инвалидировать кэш без очистки.
    """
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute(
            'SELECT public_key_b64, verified FROM pubkey_cache WHERE address = ?',
            (address,)
        )
        row = cursor.fetchone()
        return (row[0], bool(row[1])) if row else (None, False)


def cache_public_key(address: str, pubkey_b64: str, source: str = 'message',
                     verified: Optional[bool] = None) -> bool:
    """
    Кэширование публичного ключа БЕЗ очистки всего кэша.
    """
    try:
        if verified is None:
            verified = verify_address_matches_pubkey(address, pubkey_b64)
            if not verified:
                logger.warning(f"⚠️ Unverified pubkey cached for {address[:16]}...")
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute(
                'INSERT OR REPLACE INTO pubkey_cache (address, public_key_b64, updated_at, source, verified) '
                'VALUES (?, ?, ?, ?, ?)',
                (address, pubkey_b64, time.time(), source, 1 if verified else 0)
            )
        # ✅ Инвалидируем через версию, а не cache_clear()
        bump_pubkey_cache_version()
        return True
    except Exception as e:
        logger.error(f"Cache pubkey error: {e}")
        return False


def fetch_public_key_from_chain(address: str) -> Optional[Tuple[str, bool]]:
    """Получение публичного ключа из блокчейна с верификацией."""
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute(
            'SELECT sender_pubkey, metadata FROM transactions '
            'WHERE sender = ? AND sender_pubkey IS NOT NULL '
            'ORDER BY timestamp DESC LIMIT 1', (address,)
        )
        row = cursor.fetchone()
        if row and row[0]:
            pubkey = row[0]
            verified = verify_address_matches_pubkey(address, pubkey)
            return pubkey, verified
        if row and row[1]:
            try:
                meta = json.loads(row[1]) if isinstance(row[1], str) else row[1]
                if meta.get('pubkey'):
                    pubkey = meta['pubkey']
                    verified = verify_address_matches_pubkey(address, pubkey)
                    return pubkey, verified
            except Exception: pass
    return None, False


# =============================================================================
# === Контакты ===
# =============================================================================
def add_contact(user_address: str, contact_address: str, contact_name: str) -> bool:
    if not contact_name or not contact_name.strip():
        contact_name = contact_address[:10] + "..."
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute(
                'INSERT OR REPLACE INTO contacts (user_address, contact_address, contact_name, created_at) '
                'VALUES (?, ?, ?, ?)',
                (user_address, contact_address, contact_name.strip(), time.time())
            )
        # ✅ Не очищаем кэш, используем версионирование
        bump_contact_cache_version()
        return True
    except Exception as e:
        logger.error(f"Add contact DB error: {e}")
        return False


def get_contacts(user_address: str) -> List[Dict[str, Any]]:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute(
            'SELECT contact_address, contact_name, contact_pubkey, created_at '
            'FROM contacts WHERE user_address = ? ORDER BY contact_name COLLATE NOCASE',
            (user_address,)
        )
        return [{'address': row[0], 'name': row[1], 'pubkey': row[2], 'created_at': row[3]}
                for row in cursor.fetchall()]


def update_contact_name(user_address: str, contact_address: str, new_name: str) -> bool:
    """Обновляет имя контакта в БД с валидацией."""
    if not new_name or not new_name.strip():
        return False
    clean_name = ''.join(c for c in new_name.strip() if ord(c) >= 32 and ord(c) != 127)
    if not clean_name or len(clean_name) > 50:
        return False
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute(
                'UPDATE contacts SET contact_name = ? WHERE user_address = ? AND contact_address = ?',
                (clean_name, user_address, contact_address.lower())
            )
            updated = cursor.rowcount
        if updated:
            # ✅ Версионирование вместо cache_clear()
            bump_contact_cache_version()
            logger.info(f"Contact name updated: {contact_address[:16]}... -> '{clean_name}'")
        return bool(updated)
    except Exception as e:
        logger.error(f"Update contact name DB error: {e}")
        return False


# =============================================================================
# === Расшифровка сообщений ===
# =============================================================================
def decrypt_message_safe(key: bytes, encrypted_data: Optional[str],
                         fallback: str = "[Decryption Failed]") -> Optional[str]:
    if not encrypted_data: return None
    return decrypt_message_aead(key, encrypted_data, fallback=fallback)


def process_message_decryption(msg: Dict, user_address: str, mnemonic: str) -> Dict:
    result = msg.copy()
    try:
        # === ГРУППОВЫЕ СООБЩЕНИЯ ===
        if msg['recipient'].startswith('group:'):
            group_id = msg['recipient'].split(':', 1)[1]
            groups = get_user_groups_cached(user_address, cache_version=get_groups_cache_version())
            user_group = next((g for g in groups if g['id'] == group_id), None)
            if not user_group or user_address not in user_group['members']:
                result.update({'content': "[No access to group]", 'image': None})
                return result
            try:
                encrypted_data = json.loads(msg['content']) if isinstance(msg['content'], str) else msg['content']
            except json.JSONDecodeError:
                result.update({'content': "[Invalid JSON in group message]", 'image': None})
                return result
            if user_address not in encrypted_data:
                result.update({'content': "[Message not available for you]", 'image': None})
                return result
            user_data = encrypted_data[user_address]
            msg_sender = msg['sender']
            aad = msg_sender.encode('utf-8')
            sender_pubkey = msg.get('sender_pubkey')
            if not sender_pubkey:
                sender_pubkey, _ = get_cached_public_key(msg_sender, cache_version=get_pubkey_cache_version())
                if not sender_pubkey:
                    sender_pubkey, _ = fetch_public_key_from_chain(msg_sender)
            if not sender_pubkey:
                result.update({'content': "[Waiting for sender key exchange...]", 'image': None})
                result['encryption_type'] = 'group-ecdh-pending'
                return result
            try:
                key = compute_shared_key_b64(mnemonic, sender_pubkey, msg_sender)
            except Exception as e:
                logger.error(f"❌ Group ECDH key derivation failed: {e}")
                result.update({'content': "[Decryption Failed]", 'image': None})
                return result
            result['content'] = decrypt_message_aead(key, user_data.get('content'), associated_data=aad)
            result['image'] = decrypt_message_aead(key, user_data.get('image'), associated_data=aad) if user_data.get('image') else None
            result['encryption_type'] = 'group-ecdh-v4'
            result['group_id'] = group_id
            return result

        # === ПРЯМЫЕ СООБЩЕНИЯ ===
        payload = None
        raw_content = msg['content']
        if isinstance(raw_content, str):
            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, dict) and parsed.get('version') in ('hybrid-v1', 'hybrid-v2', 'key_exchange'):
                    payload = parsed
            except json.JSONDecodeError:
                pass
        elif isinstance(raw_content, dict):
            if raw_content.get('version') in ('hybrid-v1', 'hybrid-v2', 'key_exchange'):
                payload = raw_content

        if payload and payload.get('version') == 'key_exchange':
            result['content'] = "[Key exchange request — waiting for response]"
            result['image'] = None
            result['encryption_type'] = 'key_exchange'
            result['peer_pubkey'] = payload.get('my_pubkey')
            return result

        if payload and payload.get('version') in ('hybrid-v1', 'hybrid-v2'):
            if not payload.get('enc_session_key'):
                logger.warning(f"⚠️ Hybrid payload missing enc_session_key! msg_id={msg.get('id')}, sender={msg.get('sender', '')[:16]}...")
                payload = None
            else:
                if msg['sender'] == user_address:
                    peer_address = msg['recipient']
                    peer_pubkey, peer_verified = get_cached_public_key(peer_address, cache_version=get_pubkey_cache_version())
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = fetch_public_key_from_chain(peer_address)
                else:
                    peer_address = msg['sender']
                    peer_pubkey = msg.get('sender_pubkey')
                    peer_verified = False
                    if peer_pubkey:
                        peer_verified = verify_address_matches_pubkey(peer_address, peer_pubkey)
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = get_cached_public_key(peer_address, cache_version=get_pubkey_cache_version())
                        if not peer_pubkey:
                            peer_pubkey, peer_verified = fetch_public_key_from_chain(peer_address)
                if not peer_pubkey:
                    result['content'] = "[Waiting for key exchange...]"
                    result['image'] = None
                    result['encryption_type'] = payload.get('version')
                    return result
                cache_public_key(peer_address, peer_pubkey, verified=peer_verified)
                try:
                    decrypted = decrypt_hybrid(mnemonic, peer_pubkey, peer_address, payload)
                    result['content'] = decrypted.get('content') or "[Decryption Failed]"
                    result['image'] = decrypted.get('image')
                    result['encryption_type'] = payload.get('version')
                    result['key_verified'] = peer_verified
                except Exception as e:
                    logger.error(f"❌ decrypt_hybrid failed: {e}")
                    result['content'] = "[Decryption Error]"
                    result['image'] = None
                return result

        # === LEGACY FALLBACK ===
        peer_addr = msg['sender'] if msg['sender'] != user_address else msg['recipient']
        peer_pubkey, _ = get_cached_public_key(peer_addr, cache_version=get_pubkey_cache_version())
        if peer_pubkey:
            try:
                shared_key = compute_shared_key_b64(mnemonic, peer_pubkey, peer_addr)
                content = decrypt_message_aead(shared_key, msg['content'])
                if content and content != "[Decryption Failed]":
                    result['content'] = content
                    result['image'] = decrypt_message_aead(shared_key, msg['image']) if msg.get('image') else None
                    result['encryption_type'] = 'legacy-ecdh'
                    return result
            except Exception:
                pass
        try:
            key = generate_symmetric_key(msg['sender'], msg['recipient'], mnemonic)
            result['content'] = decrypt_message_safe(key, msg['content'])
            result['image'] = decrypt_message_safe(key, msg['image'])
            result['encryption_type'] = 'legacy-symmetric'
            return result
        except Exception:
            pass
        result['content'] = "[Decryption Failed]"
        result['image'] = None
        result['encryption_type'] = 'unknown'
        return result
    except Exception as e:
        logger.error(f"❌ process_message_decryption CRITICAL: {type(e).__name__}: {e}", exc_info=app.debug)
        result.update({'content': '[System Error]', 'image': None, 'error': str(e)[:100]})
        return result


# =============================================================================
# === Кэшированные функции с версионированием ===
# =============================================================================
@lru_cache(maxsize=CONFIG['CACHE_SIZE_CONTACTS'])
def get_contact_name_cached(user_address: str, contact_address: str, cache_version: int = 0) -> Optional[str]:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute(
            'SELECT contact_name FROM contacts WHERE user_address = ? AND contact_address = ?',
            (user_address, contact_address)
        )
        row = cursor.fetchone()
        return row[0] if row else None


@lru_cache(maxsize=CONFIG['CACHE_SIZE_GROUPS'])
def get_user_groups_cached(address: str, cache_version: int = 0) -> tuple:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('SELECT id, name, creator, members, created_at FROM groups')
        groups = []
        for row in cursor.fetchall():
            members = json.loads(row[3])
            if address in members:
                groups.append({
                    'id': row[0], 'name': row[1], 'creator': row[2],
                    'members': members, 'created_at': row[4]
                })
        return tuple(groups)


def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    """Возвращает список диалогов с простым превью."""
    conversations: Dict[str, Dict] = {}
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('''
                SELECT 
                    CASE WHEN sender = :addr THEN recipient ELSE sender END AS partner,
                    content, image, timestamp, sender
                FROM transactions
                WHERE sender = :addr OR recipient = :addr
                ORDER BY timestamp DESC LIMIT 500
            ''', {'addr': user_address})
            seen_partners = set()
            for row in cursor.fetchall():
                partner, raw_content, raw_image, ts, msg_sender = row
                if partner == user_address or partner in seen_partners:
                    continue
                seen_partners.add(partner)
                if msg_sender == user_address:
                    preview = "Вы"
                else:
                    if raw_image:
                        preview = "📷 Фото"
                    elif raw_content:
                        try:
                            data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                            v = data.get('version') if isinstance(data, dict) else None
                            preview = "🔑 Обмен ключами" if v == 'key_exchange' else "💬 Новое сообщение"
                        except:
                            preview = "💬 Новое сообщение"
                    else:
                        preview = "💬 Новое сообщение"
                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups = get_user_groups_cached(user_address, cache_version=get_groups_cache_version())
                    group = next((g for g in groups if g['id'] == group_id), None)
                    name = group['name'] if group else f'Группа {group_id[:8]}...'
                    conversations[partner] = {'address': partner, 'name': name, 'is_group': True, 'last_preview': preview, 'last_ts': ts}
                else:
                    name = get_contact_name_cached(user_address, partner, cache_version=get_contact_cache_version()) or partner[:10] + "..."
                    conversations[partner] = {'address': partner, 'name': name, 'is_group': False, 'last_preview': preview, 'last_ts': ts}
    except Exception as e:
        logger.error(f"Get conversations error: {e}")
    return sorted(conversations.values(), key=lambda x: x.get('last_ts', 0), reverse=True)


# =============================================================================
# === Маршруты ===
# =============================================================================
@app.before_request
def log_request():
    if 'address' in session:
        session.modified = True
    if app.debug:
        logger.debug(f"{request.method} {request.path}")
    if request.endpoint and request.endpoint not in ('index', 'login', 'create_wallet', 'static', 'serve_upload', 'test_socket'):
        if 'address' not in session:
            return jsonify({'error': 'Unauthorized'}), 401


@app.route('/')
def index():
    if 'address' in session: return redirect(url_for('chat'))
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    try:
        phrase = mnemonic_gen.generate(256)
        address = generate_address(phrase)
        session['address'] = address
        session['mnemonic'] = phrase
        session.permanent = True
        my_pubkey = get_public_key_b64(phrase)
        cache_public_key(address, my_pubkey, source='self', verified=True)
        logger.info(f"Wallet created: {address[:16]}...")
        return jsonify({
            'mnemonic_phrase': phrase, 'address': address, 'public_key': my_pubkey,
            'warning': 'Save your mnemonic phrase securely. It will not be shown again.'
        }), 201
    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        return jsonify({'error': 'Wallet creation failed'}), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            data = WalletSchema().load(request.get_json())
            phrase = data['mnemonic_phrase'].strip()
            try:
                if not mnemonic_gen.check(phrase):
                    return jsonify({'error': 'Invalid mnemonic phrase'}), 400
            except Exception:
                pass
            address = generate_address(phrase)
            session['address'] = address
            session['mnemonic'] = phrase
            session.permanent = True
            my_pubkey = get_public_key_b64(phrase)
            cache_public_key(address, my_pubkey, source='self', verified=True)
            logger.info(f"Login: {address[:16]}...")
            return jsonify({'address': address, 'public_key': my_pubkey}), 200
        except ValidationError as err:
            return jsonify({'error': err.messages}), 400
        except Exception as e:
            logger.error(f"Login error: {e}")
            return jsonify({'error': 'Login failed'}), 500
    return render_template('login.html')


@app.route('/logout')
def logout():
    clear_key_cache()
    # ✅ Очистка кэша при логауте — это ок, сессия завершается
    get_contact_name_cached.cache_clear()
    get_user_groups_cached.cache_clear()
    get_cached_public_key.cache_clear()
    session.clear()
    return redirect(url_for('index'))


@app.route('/chat')
def chat():
    if 'address' not in session: return redirect(url_for('index'))
    return render_template('chat.html', address=session['address'])


@app.route('/contacts')
def contacts():
    if 'address' not in session: return redirect(url_for('index'))
    return render_template('contacts.html', address=session['address'])


@app.route('/groups')
def groups_page():
    if 'address' not in session: return redirect(url_for('index'))
    return render_template('groups.html', address=session['address'])


@app.route('/profile')
def profile():
    if 'address' not in session: return redirect(url_for('index'))
    return render_template('profile.html', address=session.get('address'), cache_stats=get_cache_info() if app.debug else None)


@app.route('/get_public_key/<string:address>')
def get_public_key_route(address: str):
    pubkey, verified = get_cached_public_key(address, cache_version=get_pubkey_cache_version())
    if not pubkey:
        pubkey, verified = fetch_public_key_from_chain(address)
    if pubkey:
        return jsonify({'address': address, 'public_key': pubkey, 'verified': verified}), 200
    return jsonify({'error': 'Public key not found'}), 404


# =============================================================================
# === Отправка сообщений ===
# =============================================================================
@app.route('/send_message', methods=['POST'])
def send_message():
    if 'address' not in session:
        logger.warning(f"⚠️ Unauthorized send_message attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = MessageSchema().load(request.get_json())
        sender = session['address']
        recipient = data['recipient']
        content = data['content']
        image = data.get('image')
        msg_type = data.get('message_type', 'direct')
        group_id = data.get('group_id')
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            logger.warning(f"⚠️ No mnemonic in session for {sender[:16]}...")
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        expected_address = generate_address(mnemonic)
        if not hmac.compare_digest(expected_address, sender):
            logger.critical(f"🚫 Mnemonic/address mismatch!")
            return jsonify({'error': 'Authentication failed'}), 403
        my_pubkey = get_public_key_b64(mnemonic)

        # === ГРУППОВЫЕ СООБЩЕНИЯ ===
        if msg_type == 'group' and group_id:
            groups = get_user_groups_cached(sender, cache_version=get_groups_cache_version())
            group = next((g for g in groups if g['id'] == group_id), None)
            if not group or sender not in group['members']:
                return jsonify({'error': 'Group not found or no access'}), 404
            encrypted_map: Dict[str, Any] = {}
            for member in group['members']:
                try:
                    member_pubkey, _ = get_cached_public_key(member, cache_version=get_pubkey_cache_version())
                    if not member_pubkey:
                        member_pubkey, _ = fetch_public_key_from_chain(member)
                    if not member_pubkey:
                        logger.warning(f"⚠️ No pubkey for member {member[:10]}..., skipping")
                        continue
                    key = compute_shared_key_b64(mnemonic, member_pubkey, member)
                    aad = sender.encode('utf-8')
                    encrypted_map[member] = {
                        'content': encrypt_message_aead(key, content, associated_data=aad),
                        'image': encrypt_message_aead(key, image, associated_data=aad) if image else None,
                        'sender': sender
                    }
                except Exception as e:
                    logger.warning(f"⚠️ Encrypt for {member[:10]}... failed: {type(e).__name__}")
                    continue
            if not encrypted_map:
                return jsonify({'error': 'Encryption failed for all members — pubkeys missing?'}), 500
            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(cursor, sender, f"group:{group_id}", json.dumps(encrypted_map), None, sender_pubkey=my_pubkey, metadata={'encryption': 'group-ecdh-v4', 'group_id': group_id, 'sender_verified': True, 'member_count': len(encrypted_map)})
                last_proof = blockchain._last_block_raw(cursor)['proof']
                threading.Thread(target=_mine_block_async, args=(blockchain.db_path, last_proof), daemon=True).start()
            try:
                with _p2p_buffer_lock:
                    for member in group['members']:
                        _p2p_buffer.setdefault(member, []).append({'sender': sender, 'recipient': f"group:{group_id}", 'content': json.dumps(encrypted_map), 'image': None, 'ts': time.time(), 'tx_id': tx_id, 'id': f"group_{tx_id}_{member[:8]}", 'is_group': True})
                        if len(_p2p_buffer[member]) > 100:
                            _p2p_buffer[member] = _p2p_buffer[member][-100:]
            except Exception as e:
                logger.debug(f"ℹ️ P2P buffer update skipped: {e}")
            return jsonify({'message': 'Sent', 'tx_id': tx_id, 'recipient': f"group:{group_id}", 'type': 'group', 'encryption': 'group-ecdh-v4', 'members_encrypted': len(encrypted_map)}), 201

        # === ПРЯМЫЕ СООБЩЕНИЯ ===
        if sender == recipient:
            return jsonify({'error': 'Cannot message yourself'}), 400
        recipient_pubkey, recipient_verified = get_cached_public_key(recipient, cache_version=get_pubkey_cache_version())
        if not recipient_pubkey:
            recipient_pubkey, recipient_verified = fetch_public_key_from_chain(recipient)
        if recipient_pubkey:
            payload = encrypt_hybrid(mnemonic, recipient_pubkey, recipient, content, image_data=image)
            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(cursor, sender, recipient, json.dumps(payload), None, sender_pubkey=my_pubkey, metadata={'encryption': 'hybrid-v2', 'key_verified': recipient_verified})
                last_proof = blockchain._last_block_raw(cursor)['proof']
                threading.Thread(target=_mine_block_async, args=(blockchain.db_path, last_proof), daemon=True).start()
            try:
                with _p2p_buffer_lock:
                    _p2p_buffer.setdefault(recipient, []).append({'sender': sender, 'recipient': recipient, 'content': json.dumps(payload), 'sender_pubkey': my_pubkey, 'image': None, 'ts': time.time(), 'tx_id': tx_id, 'id': tx_id, 'is_group': False})
                    if len(_p2p_buffer[recipient]) > 100:
                        _p2p_buffer[recipient] = _p2p_buffer[recipient][-100:]
            except Exception as e:
                logger.debug(f"ℹ️ P2P buffer update skipped: {e}")
            return jsonify({'message': 'Sent', 'tx_id': tx_id, 'recipient': recipient, 'type': 'direct', 'encryption': 'hybrid-v2', 'key_verified': recipient_verified}), 201
        else:
            key_exchange_payload = {'my_pubkey': my_pubkey, 'message': 'key_exchange_request', 'version': 'key_exchange', 'sender_address': sender, 'timestamp': time.time()}
            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(cursor, sender, recipient, json.dumps(key_exchange_payload), None, sender_pubkey=my_pubkey, metadata={'encryption': 'key_exchange', 'note': 'Content will be sent after key exchange'})
                last_proof = blockchain._last_block_raw(cursor)['proof']
                threading.Thread(target=_mine_block_async, args=(blockchain.db_path, last_proof), daemon=True).start()
            cache_public_key(sender, my_pubkey, source='outgoing', verified=True)
            logger.info(f"🔑 Key exchange sent: {sender[:16]}... -> {recipient[:16]}...")
            return jsonify({'message': 'Key exchange sent. Please ask recipient to fetch your public key.', 'tx_id': tx_id, 'recipient': recipient, 'key_exchange': True, 'my_pubkey': my_pubkey}), 201
    except ValidationError as err:
        logger.warning(f"⚠️ Validation error in send_message: {err.messages}")
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"❌ send_message error: {type(e).__name__}", exc_info=os.getenv('FLASK_ENV') != 'production')
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# === Получение сообщений ===
# =============================================================================
@app.route('/get_conversation', methods=['GET'])
def get_conversation():
    if 'address' not in session:
        logger.warning(f"⚠️ Unauthorized get_conversation attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        user_addr = session['address']
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            logger.warning(f"⚠️ No mnemonic in session for {user_addr[:16]}...")
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        expected_address = generate_address(mnemonic)
        if not hmac.compare_digest(expected_address, user_addr):
            logger.critical(f"🚫 Mnemonic/address mismatch in get_conversation!")
            return jsonify({'error': 'Authentication failed'}), 403
        chat_with = request.args.get('with')
        if not chat_with:
            return jsonify({'error': 'Missing "with" parameter'}), 400
        last_message_id = request.args.get('last_message_id', type=int)
        limit = min(int(request.args.get('limit', 50)), 100)
        with get_db_cursor(blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                group_id = chat_with.split(':', 1)[1]
                groups = get_user_groups_cached(user_addr, cache_version=get_groups_cache_version())
                user_group = next((g for g in groups if g['id'] == group_id), None)
                if not user_group or user_addr not in user_group['members']:
                    return jsonify({'error': 'No access to this group'}), 403
                query = 'SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata FROM transactions WHERE recipient = ?'
                params = [chat_with]
            else:
                query = 'SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata FROM transactions WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)'
                params = [user_addr, chat_with, chat_with, user_addr]
            if last_message_id:
                query += ' AND id > ?'
                params.append(last_message_id)
            query += ' ORDER BY timestamp ASC LIMIT ?'
            params.append(limit)
            cursor.execute(query, params)
            messages = [{'id': r[0], 'sender': r[1], 'recipient': r[2], 'content': r[3], 'image': r[4], 'timestamp': r[5], 'sender_pubkey': r[6], 'metadata': r[7]} for r in cursor.fetchall()]
        peer_addresses = set(msg['sender'] for msg in messages) | set(msg['recipient'] for msg in messages)
        peer_addresses.discard(user_addr)
        if peer_addresses:
            placeholders = ','.join('?' * len(peer_addresses))
            with get_db_cursor(blockchain.db_path) as cursor:
                cursor.execute(f'SELECT address, public_key_b64, verified FROM pubkey_cache WHERE address IN ({placeholders})', list(peer_addresses))
                for row in cursor.fetchall():
                    cache_public_key(row[0], row[1], verified=bool(row[2]))
        decrypted = []
        for msg in messages:
            dec = process_message_decryption(msg, user_addr, mnemonic)
            dec['sender_name'] = get_contact_name_cached(user_addr, msg['sender'], cache_version=get_contact_cache_version()) or msg['sender']
            dec['recipient_name'] = get_contact_name_cached(user_addr, msg['recipient'], cache_version=get_contact_cache_version()) or msg['recipient']
            dec['is_mine'] = (msg['sender'] == user_addr)
            if msg.get('metadata'):
                try:
                    meta = json.loads(msg['metadata']) if isinstance(msg['metadata'], str) else msg['metadata']
                    if not dec.get('encryption_type'):
                        dec['encryption_type'] = meta.get('encryption', 'unknown')
                    if dec.get('key_verified') is None:
                        dec['key_verified'] = meta.get('key_verified', False)
                except Exception:
                    pass
            decrypted.append(dec)
        return jsonify({'messages': decrypted, 'has_more': len(messages) == limit, 'chat_with': chat_with, 'last_message_id': messages[-1]['id'] if messages else None}), 200
    except Exception as e:
        logger.error(f"❌ get_conversation error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': f'Failed to load messages: {type(e).__name__}'}), 500


@app.route('/get_conversations', methods=['GET'])
def get_conversations_route():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        return jsonify({'conversations': get_conversations_list(session['address'])}), 200
    except Exception as e:
        logger.error(f"Get conversations error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/mark_conversation_read', methods=['POST'])
def mark_conversation_read():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json() or {}
        chat_with = data.get('chat_with', '').strip()
        if not chat_with:
            return jsonify({'error': 'Missing chat_with'}), 400
        logger.debug(f"👁️ Read mark: {session['address'][:16]}... -> {chat_with[:20]}... at {time.time():.0f}")
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Failed'}), 500


# =============================================================================
# === Контакты: маршруты ===
# =============================================================================
@app.route('/add_contact', methods=['POST'])
def add_contact_route():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = ContactSchema().load(request.get_json())
        if add_contact(session['address'], data['address'], data['name']):
            return jsonify({'message': 'Contact added'}), 201
        return jsonify({'error': 'Failed to add contact'}), 500
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Add contact error: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/add_contact_from_chat', methods=['POST'])
def add_contact_from_chat():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        raw_data = request.get_json() or {}
        contact_address = raw_data.get('contact_address', '').strip()
        contact_name = raw_data.get('contact_name', '').strip()
        if not contact_address or len(contact_address) != 64:
            return jsonify({'error': 'Invalid address format (must be 64 hex chars)'}), 400
        if not contact_name: contact_name = contact_address[:10] + '...'
        if add_contact(session['address'], contact_address, contact_name):
            logger.info(f"Contact {contact_address[:16]}... added from chat")
            return jsonify({'message': 'Contact added'}), 201
        return jsonify({'error': 'Failed to save to database'}), 500
    except Exception as e:
        logger.error(f"add_contact_from_chat error: {e}", exc_info=True)
        return jsonify({'error': f'Server error'}), 500


@app.route('/get_contacts', methods=['GET'])
def get_contacts_route():
    if 'address' not in session:
        logger.warning(f"⚠️ Unauthorized access to /get_contacts")
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        user_addr = session['address']
        if not user_addr:
            logger.error("❌ user_addr is empty in session")
            return jsonify({'error': 'Invalid session'}), 401
        logger.debug(f"📋 Loading contacts for {user_addr[:16]}...")
        user_contacts = get_contacts(user_addr)
        logger.debug(f"✅ Found {len(user_contacts)} contacts")
        for contact in user_contacts:
            if not contact.get('pubkey'):
                try:
                    pubkey, verified = get_cached_public_key(contact['address'], cache_version=get_pubkey_cache_version())
                    contact['pubkey'] = pubkey
                    contact['pubkey_verified'] = verified
                except Exception as e:
                    logger.debug(f"⚠️ Could not fetch pubkey for {contact['address'][:16]}...: {type(e).__name__}")
                    contact['pubkey'] = None
                    contact['pubkey_verified'] = False
        return jsonify({'contacts': user_contacts}), 200
    except sqlite3.OperationalError as e:
        logger.error(f"❌ SQLite error in get_contacts: {e}")
        return jsonify({'error': f'Database error: {str(e)}'}), 500
    except Exception as e:
        logger.error(f"❌ Get contacts error: {type(e).__name__}: {e}", exc_info=True)
        return jsonify({'error': f'Failed: {type(e).__name__}'}), 500


@app.route('/delete_contact', methods=['POST'])
def delete_contact_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json() or {}
        contact_address = data.get('address', '').strip()
        if not contact_address or len(contact_address) != 64:
            return jsonify({'error': 'Invalid address format'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('DELETE FROM contacts WHERE user_address = ? AND contact_address = ?', (user_addr, contact_address))
            deleted = cursor.rowcount
        # ✅ Версионирование вместо cache_clear()
        bump_contact_cache_version()
        if deleted:
            logger.info(f"Contact {contact_address[:16]}... deleted by {user_addr[:16]}...")
            return jsonify({'message': 'Contact deleted'}), 200
        else:
            return jsonify({'error': 'Contact not found'}), 404
    except Exception as e:
        logger.error(f"Delete contact error: {e}")
        return jsonify({'error': 'Failed to delete contact'}), 500


@app.route('/edit_contact', methods=['POST'])
def edit_contact_route():
    if 'address' not in session:
        logger.warning(f"⚠️ Unauthorized edit_contact attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = EditContactSchema().load(request.get_json(silent=True) or {})
        user_addr = session['address']
        contact_address = data['address']
        new_name = data['name']
        if hmac.compare_digest(user_addr, contact_address):
            return jsonify({'error': 'Cannot edit yourself as a contact'}), 400
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT contact_name FROM contacts WHERE user_address = ? AND contact_address = ?', (user_addr, contact_address))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Contact not found'}), 404
            old_name = row[0]
        if old_name == new_name:
            return jsonify({'message': 'No changes', 'unchanged': True}), 200
        if update_contact_name(user_addr, contact_address, new_name):
            return jsonify({'message': 'Contact name updated', 'old_name': old_name, 'new_name': new_name}), 200
        else:
            return jsonify({'error': 'Failed to update contact name'}), 500
    except ValidationError as err:
        logger.warning(f"⚠️ Validation error in edit_contact: {err.messages}")
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"❌ edit_contact error: {type(e).__name__}: {e}", exc_info=app.debug)
        return jsonify({'error': 'Internal server error'}), 500


# =============================================================================
# === Группы ===
# =============================================================================
@app.route('/get_groups', methods=['GET'])
def get_groups():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        groups = get_user_groups_cached(session['address'], cache_version=get_groups_cache_version())
        return jsonify({'groups': groups}), 200
    except Exception as e:
        logger.error(f"Get groups error: {e}")
        return jsonify({'error': 'Failed to load groups'}), 500


@app.route('/create_group', methods=['POST'])
def create_group():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = GroupSchema().load(request.get_json())
        creator = session['address']
        name = data['name'].strip()
        members: List[str] = data['members']
        members_set = {m.strip() for m in members if m.strip()}
        members_set.add(creator)
        members_clean = sorted(members_set)
        invalid = [m for m in members_clean if len(m) != 64]
        if invalid: return jsonify({'error': f'Invalid member addresses: {invalid[:3]}'}), 400
        group_id = uuid.uuid4().hex
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('INSERT INTO groups (id, name, creator, members, created_at) VALUES (?, ?, ?, ?, ?)', (group_id, name, creator, json.dumps(members_clean), time.time()))
        # ✅ Версионирование вместо cache_clear()
        bump_groups_cache_version()
        logger.info(f"Group '{name}' created by {creator[:16]}... with {len(members_clean)} members")
        return jsonify({'message': 'Group created', 'group_id': group_id, 'name': name, 'members': members_clean, 'member_count': len(members_clean)}), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Create group error: {e}")
        return jsonify({'error': 'Failed to create group'}), 500


@app.route('/api/export_mnemonic', methods=['POST'])
def export_mnemonic():
    if 'address' not in session:
        logger.warning(f"Unauthorized mnemonic export attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        confirmation = data.get('confirmation', '').strip().upper()
        valid_confirmations = ('I CONFIRM', 'ПОДТВЕРЖДАЮ', 'CONFIRM', 'YES')
        if confirmation not in valid_confirmations:
            logger.warning(f"Invalid confirmation attempt for {session.get('address', 'unknown')[:16]}...")
            return jsonify({'error': 'Please type "I CONFIRM" or "YES" to continue'}), 400
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            logger.warning(f"Mnemonic export failed: session expired for {session.get('address', 'unknown')[:16]}...")
            return jsonify({'error': 'Session expired. Please login again.'}), 401
        response = jsonify({'mnemonic': mnemonic, 'warning': 'Auto-clears in 30 seconds. Do not share.', 'auto_clear_seconds': 30})
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        logger.info(f"Mnemonic exported for {session.get('address', 'unknown')[:16]}... from {request.remote_addr}")
        return response, 200
    except Exception as e:
        logger.error(f"Mnemonic export error for {session.get('address', 'unknown')[:16]}...: {type(e).__name__}")
        return jsonify({'error': 'Export failed'}), 500


@app.route('/delete_group', methods=['POST'])
def delete_group():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID format'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT id, name, creator, members FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            creator = row[2]
            group_name = row[1]
            if creator != user_addr:
                logger.warning(f"Unauthorized delete attempt: {user_addr[:16]}... tried to delete group {group_id} (creator: {creator[:16]}...)")
                return jsonify({'error': 'Only the group creator can delete this group'}), 403
            cursor.execute('DELETE FROM groups WHERE id = ?', (group_id,))
            deleted = cursor.rowcount
        # ✅ Версионирование вместо cache_clear()
        bump_groups_cache_version()
        logger.info(f"Group '{group_name}' (ID: {group_id}) deleted by creator {user_addr[:16]}...")
        return jsonify({'message': 'Group deleted', 'group_id': group_id, 'group_name': group_name}), 200
    except Exception as e:
        logger.error(f"Delete group error: {type(e).__name__}", exc_info=app.debug)
        return jsonify({'error': 'Failed to delete group'}), 500


@app.route('/rename_group', methods=['POST'])
def rename_group():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        new_name = data.get('name', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID'}), 400
        if not new_name or len(new_name) > 100:
            return jsonify({'error': 'Name must be 1–100 characters'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT creator FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            if row[0] != user_addr:
                return jsonify({'error': 'Only the creator can rename this group'}), 403
            cursor.execute('UPDATE groups SET name = ? WHERE id = ?', (new_name, group_id))
        # ✅ Версионирование вместо cache_clear()
        bump_groups_cache_version()
        logger.info(f"Group {group_id} renamed to '{new_name}' by {user_addr[:16]}...")
        return jsonify({'message': 'Group renamed', 'name': new_name}), 200
    except Exception as e:
        logger.error(f"Rename group error: {type(e).__name__}")
        return jsonify({'error': 'Failed to rename group'}), 500


@app.route('/add_group_member', methods=['POST'])
def add_group_member():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        new_member = data.get('address', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID'}), 400
        if not new_member or len(new_member) != 64:
            return jsonify({'error': 'Invalid address (must be 64 hex chars)'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT creator, members FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            if row[0] != user_addr:
                return jsonify({'error': 'Only the creator can add members'}), 403
            members = json.loads(row[1])
            if new_member in members:
                return jsonify({'error': 'Address already in group'}), 400
            if len(members) >= 50:
                return jsonify({'error': 'Group member limit (50) reached'}), 400
            members.append(new_member)
            members.sort()
            cursor.execute('UPDATE groups SET members = ? WHERE id = ?', (json.dumps(members), group_id))
        # ✅ Версионирование вместо cache_clear()
        bump_groups_cache_version()
        logger.info(f"Member {new_member[:16]}... added to group {group_id} by {user_addr[:16]}...")
        return jsonify({'message': 'Member added', 'members': members}), 200
    except Exception as e:
        logger.error(f"Add group member error: {type(e).__name__}")
        return jsonify({'error': 'Failed to add member'}), 500


@app.route('/remove_group_member', methods=['POST'])
def remove_group_member():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()
        target = data.get('address', '').strip()
        if not group_id or len(group_id) != 32:
            return jsonify({'error': 'Invalid group ID'}), 400
        if not target or len(target) != 64:
            return jsonify({'error': 'Invalid address'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT creator, members FROM groups WHERE id = ?', (group_id,))
            row = cursor.fetchone()
            if not row:
                return jsonify({'error': 'Group not found'}), 404
            creator = row[0]
            members = json.loads(row[1])
            if creator != user_addr:
                return jsonify({'error': 'Only the creator can remove members'}), 403
            if target == creator:
                return jsonify({'error': 'Creator cannot be removed'}), 400
            if target not in members:
                return jsonify({'error': 'Address not in group'}), 404
            if len(members) <= 2:
                return jsonify({'error': 'Group must have at least 2 members'}), 400
            members.remove(target)
            cursor.execute('UPDATE groups SET members = ? WHERE id = ?', (json.dumps(members), group_id))
        # ✅ Версионирование вместо cache_clear()
        bump_groups_cache_version()
        logger.info(f"Member {target[:16]}... removed from group {group_id} by {user_addr[:16]}...")
        return jsonify({'message': 'Member removed', 'members': members}), 200
    except Exception as e:
        logger.error(f"Remove group member error: {type(e).__name__}")
        return jsonify({'error': 'Failed to remove member'}), 500


# =============================================================================
# === Утилиты и загрузка файлов ===
# =============================================================================
IMAGE_MAGIC_BYTES = {
    b'\xFF\xD8\xFF': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF....WEBP': 'image/webp',
}

def validate_image_file(file_content: bytes) -> Optional[str]:
    for magic, mime_type in IMAGE_MAGIC_BYTES.items():
        if file_content.startswith(magic):
            return mime_type
    return None


@app.route('/clear_conversation', methods=['POST'])
def clear_conversation():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json() or {}
        chat_with = data.get('chat_with', '').strip()
        if not chat_with:
            return jsonify({'error': 'Missing chat_with parameter'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                cursor.execute('DELETE FROM transactions WHERE sender = ? AND recipient = ?', (user_addr, chat_with))
            else:
                cursor.execute('DELETE FROM transactions WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)', (user_addr, chat_with, chat_with, user_addr))
            deleted = cursor.rowcount
        logger.info(f"Cleared {deleted} messages for {user_addr[:16]}... in {chat_with[:20]}...")
        return jsonify({'message': f'Cleared {deleted} messages'}), 200
    except Exception as e:
        logger.error(f"Clear conversation error: {e}")
        return jsonify({'error': 'Failed to clear'}), 500


@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        if 'file' not in request.files: return jsonify({'error': 'No file provided'}), 400
        file = request.files['file']
        if not file.filename: return jsonify({'error': 'Empty filename'}), 400
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > CONFIG['MAX_UPLOAD_SIZE']:
            return jsonify({'error': 'File too large'}), 413
        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(filepath)
        with open(filepath, 'rb') as f:
            header = f.read(12)
        detected_mime = validate_image_file(header)
        declared_mime = file.content_type
        if declared_mime and declared_mime.startswith('image/'):
            if detected_mime and detected_mime != declared_mime:
                logger.warning(f"MIME mismatch: declared={declared_mime}, detected={detected_mime}")
            if detected_mime:
                with open(filepath, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                os.remove(filepath)
                return jsonify({'file_url': f"{detected_mime};base64,{b64}"}), 200
        return jsonify({'file_url': f"/uploads/{unique_name}"}), 200
    except Exception as e:
        logger.error(f"Upload error: {e}")
        if 'filepath' in locals() and os.path.exists(filepath):
            os.remove(filepath)
        return jsonify({'error': 'Upload failed'}), 500


@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/delete_message', methods=['POST'])
def delete_message():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = DeleteMessageSchema().load(request.get_json())
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT sender FROM transactions WHERE id = ?', (data['message_id'],))
            row = cursor.fetchone()
            if not row: return jsonify({'error': 'Message not found'}), 404
            if row[0] != user_addr: return jsonify({'error': 'Permission denied'}), 403
            cursor.execute('DELETE FROM transactions WHERE id = ?', (data['message_id'],))
        logger.info(f"Message #{data['message_id']} deleted by {user_addr[:16]}...")
        return jsonify({'message': 'Deleted'}), 200
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Delete message error: {e}")
        return jsonify({'error': 'Failed'}), 500


# =============================================================================
# === GunDB конфигурация ===
# =============================================================================
@app.route('/gun-config')
def gun_config():
    peers = [
        'https://gun.robins.one/gun',
        'https://relic.eastus.cloudapp.azure.com/gun',
        'https://gun-manhattan.herokuapp.com/gun',
        'https://gundb-relay-eb4x.onrender.com/gun',
        'https://gun-relay-7q2w.onrender.com/gun',
    ]
    return jsonify({'peers': peers, 'room_prefix': 'dm_v1:', 'version': '1.0', 'fallback': 'localStorage'})


try:
    from gun import Gun
    @app.route('/gun', methods=['GET', 'POST', 'OPTIONS'])
    def gun_relay():
        if request.method == 'OPTIONS':
            return '', 204
        return jsonify({'ok': True})
except ImportError:
    pass


@app.route('/decrypt_message', methods=['POST'])
def decrypt_message_api():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json()
        encrypted_payload = data.get('encrypted_payload')
        peer_address = data.get('peer_address')
        if not encrypted_payload or not peer_address:
            return jsonify({'error': 'Missing fields'}), 400
        user_addr = session['address']
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            return jsonify({'error': 'Session expired'}), 401
        peer_pubkey, _ = get_cached_public_key(peer_address, cache_version=get_pubkey_cache_version())
        if not peer_pubkey:
            peer_pubkey, _ = fetch_public_key_from_chain(peer_address)
        if not peer_pubkey:
            return jsonify({'content': '[Waiting for key exchange...]'}), 200
        decrypted = decrypt_hybrid(mnemonic, peer_pubkey, peer_address, encrypted_payload)
        return jsonify({'content': decrypted.get('content'), 'image': decrypted.get('image')}), 200
    except Exception as e:
        logger.error(f"P2P decrypt error: {e}")
        return jsonify({'content': '[Decryption failed]'}), 200


@app.route('/p2p-poll')
def p2p_poll():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    chat_id = request.args.get('chat', '')
    since = float(request.args.get('since', 0))
    user_addr = session['address']
    if not chat_id:
        return jsonify([]), 400
    with _p2p_buffer_lock:
        messages = _p2p_buffer.get(chat_id, [])
        new_messages = [m for m in messages if m['ts'] > since and m['recipient'] in (user_addr, chat_id)]
        cutoff = time.time() - 300
        for addr in list(_p2p_buffer.keys()):
            _p2p_buffer[addr] = [m for m in _p2p_buffer[addr] if m['ts'] > cutoff]
            if not _p2p_buffer[addr]:
                del _p2p_buffer[addr]
    return jsonify(new_messages), 200


# =============================================================================
# === Обработчики ошибок ===
# =============================================================================
@app.errorhandler(404)
def not_found(e): return jsonify({'error': 'Not found'}), 404
@app.errorhandler(500)
def server_error(e): return jsonify({'error': 'Internal server error'}), 500
@app.errorhandler(413)
def file_too_large(e): return jsonify({'error': 'File too large (max 16MB)'}), 413


# =============================================================================
# === Запуск приложения ===
# =============================================================================
if __name__ == '__main__':
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        logger.critical("❌ SECRET_KEY too short or missing! Set it in .env")
    is_production = os.getenv('FLASK_ENV') == 'production'
    if is_production:
        logger.warning("🚀 Starting in PRODUCTION mode")
        app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
    else:
        logger.info("🔧 Starting in DEVELOPMENT mode")
        app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)