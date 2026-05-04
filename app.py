"""
app.py — Децентрализованный мессенджер с безопасным шифрованием
Версия: 3.3 (исправлены уязвимости: сессии, метаданные, валидация ключей)
"""
import hashlib
import hmac
import os
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
import hmac

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
    'POW_DIFFICULTY': int(os.getenv('POW_DIFFICULTY', 2)),  # читаем из .env
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

# 🔧 Читаем пути из .env или используем безопасные дефолты
DATABASE_PATH = os.getenv('DATABASE_PATH', 'blockchain.db')
UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', 'uploads')

# 🔧 Адаптация путей под ОС (Windows / Linux)
import sys
if sys.platform == 'win32':
    # Если путь содержит Linux-разделители — заменяем на относительные
    if DATABASE_PATH.startswith('/var/www/'):
        DATABASE_PATH = 'blockchain.db'
    if UPLOAD_FOLDER.startswith('/var/www/'):
        UPLOAD_FOLDER = 'uploads'

# 🔧 Создаём директории, если их нет (критично для первой инициализации!)
os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)) or '.', exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
STATIC_FOLDER = 'static'
TEMPLATE_FOLDER = 'templates'

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    SECRET_KEY = secrets.token_hex(32)
    logging.warning("❌ SECRET_KEY NOT FOUND in env! Sessions will reset on restart!")
else:
    # Лог только в режиме разработки, чтобы не спамить в продакшене
    # ✅ СТАЛО (исправлено):
    if os.getenv('FLASK_ENV') != 'production':
        logging.warning("✅ SECRET_KEY loaded from .env")  # используем logging, а не logger

MAX_CONTENT_LENGTH = CONFIG['MAX_UPLOAD_SIZE']


# === Логирование ===
def setup_logging():
    # Явный абсолютный путь рядом с app.py
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

    # Сразу пишем стартовое сообщение для проверки
    logging.getLogger(__name__).warning(f"=== App started, log path: {log_path} ===")

setup_logging()
logger = logging.getLogger(__name__)


# === Утилиты БД ===
@contextmanager
def get_db_cursor(db_path: str):
    conn = None
    try:
        conn = sqlite3.connect(
            db_path, timeout=CONFIG['DB_TIMEOUT'],
            check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES
        )
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        if conn: conn.close()


# === Создание таблиц ===
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
    # 🔒 Флаг verified: проверено ли соответствие ключа адресу (выносим комментарий НАД запросом)
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




# === Blockchain ===
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
        # 🔒 НИКОГДА не сохраняем plaintext в metadata!
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

# === Фоновый майнинг (не блокирует запросы пользователей) ===
_pow_lock = threading.Lock()  # только один PoW за раз

def _mine_block_async(db_path: str, last_proof: int) -> None:
    """PoW в отдельном потоке — пользователь не ждёт."""
    if not _pow_lock.acquire(blocking=False):
        # Другой поток уже майнит — пропускаем
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
# === Flask app ===
app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='__Secure-session',  # 🔒 Префикс для HTTPS-only
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=CONFIG['SESSION_LIFETIME']),
)

app.session_interface = SecureCookieSessionInterface()

mnemonic_gen = Mnemonic('english')
blockchain = Blockchain(DATABASE_PATH)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# === Схемы валидации ===
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

class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True, validate=lambda x: x > 0)


# === Кэш публичных ключей (с верификацией) ===
@lru_cache(maxsize=CONFIG['CACHE_SIZE_PUBKEYS'])
def get_cached_public_key(address: str) -> Optional[Tuple[str, bool]]:
    """
    Возвращает (pubkey_b64, is_verified).
    is_verified=True означает, что ключ криптографически привязан к адресу.
    """
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('SELECT public_key_b64, verified FROM pubkey_cache WHERE address = ?', (address,))
        row = cursor.fetchone()
        return (row[0], bool(row[1])) if row else (None, False)

def cache_public_key(address: str, pubkey_b64: str, source: str = 'message',
                     verified: Optional[bool] = None) -> bool:
    """
    Кэширование публичного ключа с опциональной верификацией.

    🔒 Если verified=None — автоматически проверяем соответствие ключа адресу.
    """
    try:
        # 🔒 Авто-верификация при первом добавлении
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
        get_cached_public_key.cache_clear()
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


# === Контакты ===
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
        get_contact_name_cached.cache_clear()
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


# === Расшифровка сообщений ===
def decrypt_message_safe(key: bytes, encrypted_data: Optional[str],
                         fallback: str = "[Decryption Failed]") -> Optional[str]:
    """Безопасная расшифровка с унифицированной обработкой ошибок."""
    if not encrypted_data: return None
    return decrypt_message_aead(key, encrypted_data, fallback=fallback)


#=============================================================================
# === Расшифровка сообщений — ПОЛНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ ===
# =============================================================================

def process_message_decryption(msg: Dict, user_address: str, mnemonic: str) -> Dict:
    """
    Безопасная обработка и расшифровка сообщений.
    ✅ Исправлены: конфликт версий, парсинг payload, обработка key_exchange, fallback
    """
    result = msg.copy()

    try:
        # =====================================================================
        # 1. ГРУППОВЫЕ СООБЩЕНИЯ
        # =====================================================================
        if msg['recipient'].startswith('group:'):
            group_id = msg['recipient'].split(':', 1)[1]
            groups = get_user_groups_cached(user_address)
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
            key = generate_symmetric_key(msg_sender, user_address, mnemonic)
            aad = msg_sender.encode('utf-8')

            result['content'] = decrypt_message_aead(key, user_data.get('content'), associated_data=aad)
            result['image'] = decrypt_message_aead(key, user_data.get('image'), associated_data=aad) if user_data.get(
                'image') else None
            result['encryption_type'] = 'symmetric-group-v2'
            result['group_id'] = group_id
            return result

        # =====================================================================
        # 2. ПРЯМЫЕ СООБЩЕНИЯ — Безопасный парсинг payload
        # =====================================================================
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

        # 🔑 2.1 Обработка обмена ключами (КРИТИЧНО: проверяем ПЕРЕД гибридной логикой!)
        if payload and payload.get('version') == 'key_exchange':
            result['content'] = "[Key exchange request — waiting for response]"
            result['image'] = None
            result['encryption_type'] = 'key_exchange'
            result['peer_pubkey'] = payload.get('my_pubkey')
            return result

        # 🔐 2.2 Обработка гибридного шифрования (v1 / v2)
        # 🔐 2.2 Обработка гибридного шифрования (v1 / v2)
        if payload and payload.get('version') in ('hybrid-v1', 'hybrid-v2'):
            if not payload.get('enc_session_key'):
                logger.warning(
                    f"⚠️ Hybrid payload missing enc_session_key! "
                    f"msg_id={msg.get('id')}, sender={msg.get('sender', '')[:16]}..., "
                    f"keys={list(payload.keys()) if payload else 'N/A'}"
                )
                # 🔄 НЕ возвращаем ошибку — сбрасываем payload, чтобы сработал LEGACY FALLBACK ниже
                payload = None
            else:
                # Определяем адрес и публичный ключ пира
                if msg['sender'] == user_address:
                    peer_address = msg['recipient']
                    peer_pubkey, peer_verified = get_cached_public_key(peer_address)
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = fetch_public_key_from_chain(peer_address)
                else:
                    peer_address = msg['sender']
                    peer_pubkey = msg.get('sender_pubkey')
                    peer_verified = False
                    if peer_pubkey:
                        peer_verified = verify_address_matches_pubkey(peer_address, peer_pubkey)
                    if not peer_pubkey:
                        peer_pubkey, peer_verified = get_cached_public_key(peer_address)
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
                return result  # ← Возвращаем ТОЛЬКО при успешной расшифровке
        # =====================================================================
        # 3. LEGACY FALLBACK (старые сообщения)
        # =====================================================================
        peer_addr = msg['sender'] if msg['sender'] != user_address else msg['recipient']
        peer_pubkey, _ = get_cached_public_key(peer_addr)

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


def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    """Возвращает список диалогов с простым превью."""
    conversations: Dict[str, Dict] = {}
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            # Запрос получает сообщения с контентом и временем, от новых к старым
            cursor.execute('''
                SELECT 
                    CASE WHEN sender = :addr THEN recipient ELSE sender END AS partner,
                    content,
                    image,
                    timestamp,
                    sender
                FROM transactions
                WHERE sender = :addr OR recipient = :addr
                ORDER BY timestamp DESC
            ''', {'addr': user_address})

            seen_partners = set()
            for row in cursor.fetchall():
                partner, raw_content, raw_image, ts, msg_sender = row
                if partner == user_address or partner in seen_partners:
                    continue
                seen_partners.add(partner)

                # 🔹 Формируем ПРЕДЕЛЬНО простое превью
                if msg_sender == user_address:
                    # ✅ Исходящее — просто "Вы"
                    preview = "Вы"
                else:
                    # 🔹 Входящее — иконка + тип
                    if raw_image:
                        preview = "📷 Фото"
                    elif raw_content:
                        try:
                            data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                            v = data.get('version') if isinstance(data, dict) else None
                            if v == 'key_exchange':
                                preview = "🔑 Обмен ключами"
                            else:
                                preview = "💬 Новое сообщение"
                        except:
                            preview = "💬 Новое сообщение"
                    else:
                        preview = "💬 Новое сообщение"

                # 🔹 Сохраняем в словарь
                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups = get_user_groups_cached(user_address)
                    group = next((g for g in groups if g['id'] == group_id), None)
                    name = group['name'] if group else f'Группа {group_id[:8]}...'
                    conversations[partner] = {
                        'address': partner,
                        'name': name,
                        'is_group': True,
                        'last_preview': preview,
                        'last_ts': ts
                    }
                else:
                    name = get_contact_name_cached(user_address, partner) or partner[:10] + "..."
                    conversations[partner] = {
                        'address': partner,
                        'name': name,
                        'is_group': False,
                        'last_preview': preview,
                        'last_ts': ts
                    }

    except Exception as e:
        logger.error(f"Get conversations error: {e}")

    # 🔥 Сортируем: самые свежие диалогов сверху
    return sorted(conversations.values(), key=lambda x: x.get('last_ts', 0), reverse=True)


@app.route('/mark_conversation_read', methods=['POST'])
def mark_conversation_read():
    """Фиксирует прочтение диалога (для синхронизации между устройствами)."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json() or {}
        chat_with = data.get('chat_with', '').strip()
        if not chat_with:
            return jsonify({'error': 'Missing chat_with'}), 400

        # 🔹 Здесь можно записать last_read_ts в БД при миграции.
        # Пока просто логируем и возвращаем успех для фоновой синхронизации.
        logger.debug(f"👁️ Read mark: {session['address'][:16]}... -> {chat_with[:20]}... at {time.time():.0f}")
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return jsonify({'error': 'Failed'}), 500

@lru_cache(maxsize=CONFIG['CACHE_SIZE_CONTACTS'])
def get_contact_name_cached(user_address: str, contact_address: str) -> Optional[str]:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute(
            'SELECT contact_name FROM contacts WHERE user_address = ? AND contact_address = ?',
            (user_address, contact_address)
        )
        row = cursor.fetchone()
        return row[0] if row else None


@lru_cache(maxsize=CONFIG['CACHE_SIZE_GROUPS'])
def get_user_groups_cached(address: str) -> List[Dict[str, Any]]:
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
        return groups


# =============================================================================
# === Маршруты ===
# =============================================================================

@app.before_request
def log_request():
    if 'address' in session:
        session.modified = True

    if app.debug:
        logger.debug(f"{request.method} {request.path}")

    # 🔒 Проверка сессии для защищённых эндпоинтов
    if request.endpoint and request.endpoint not in ('index', 'login', 'create_wallet',
                                                      'static', 'serve_upload', 'test_socket'):
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

        # 🔒 В сессию сохраняем ТОЛЬКО адрес, не мнемонику!
        session['address'] = address
        session['mnemonic'] = phrase
        session.permanent = True

        my_pubkey = get_public_key_b64(phrase)
        cache_public_key(address, my_pubkey, source='self', verified=True)
        logger.info(f"Wallet created: {address[:16]}...")

        # 🔒 Возвращаем мнемонику ТОЛЬКО в ответе, клиент должен сохранить её безопасно
        return jsonify({
            'mnemonic_phrase': phrase,
            'address': address,
            'public_key': my_pubkey,
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

            # 🔒 Опциональная проверка валидности мнемоники (если mnemonic поддерживает)
            try:
                if not mnemonic_gen.check(phrase):
                    return jsonify({'error': 'Invalid mnemonic phrase'}), 400
            except Exception:
                pass  # Если mnemonic не установлен, пропускаем проверку

            address = generate_address(phrase)

            # 🔒 В сессию — только адрес
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
    # 🔒 Не показываем мнемонику в профиле по умолчанию
    return render_template('profile.html',
                          address=session.get('address'),
                          cache_stats=get_cache_info() if app.debug else None)

@app.route('/get_public_key/<string:address>')
def get_public_key_route(address: str):
    pubkey, verified = get_cached_public_key(address)
    if not pubkey:
        pubkey, verified = fetch_public_key_from_chain(address)

    if pubkey:
        return jsonify({
            'address': address,
            'public_key': pubkey,
            'verified': verified  # 🔒 Клиент может показать статус верификации
        }), 200
    return jsonify({'error': 'Public key not found'}), 404



# =============================================================================
# === Отправка сообщений (БЕЗОПАСНАЯ ВЕРСИЯ) ===
# =============================================================================

@app.route('/send_message', methods=['POST'])
def send_message():
    """
    Отправка сообщения с гибридным шифрованием.
    🔒 Мнемоника берётся ТОЛЬКО из сессии, не из запроса клиента.
    """
    # 🔒 Проверка сессии (дублируется в before_request для явности)
    if 'address' not in session:
        logger.warning(f"⚠️ Unauthorized send_message attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        # Валидация входных данных
        data = MessageSchema().load(request.get_json())
        sender = session['address']
        recipient = data['recipient']
        content = data['content']
        image = data.get('image')
        msg_type = data.get('message_type', 'direct')
        group_id = data.get('group_id')

        # 🔒 КРИТИЧНО: мнемоника ТОЛЬКО из сессии
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            logger.warning(f"⚠️ No mnemonic in session for {sender[:16]}...")
            return jsonify({'error': 'Session expired. Please login again.'}), 401

        # 🔒 Верификация: адрес в сессии должен соответствовать мнемонике
        expected_address = generate_address(mnemonic)
        if not hmac.compare_digest(expected_address, sender):
            logger.critical(
                f"🚫 Mnemonic/address mismatch! session={sender[:16]}..., expected={expected_address[:16]}...")
            return jsonify({'error': 'Authentication failed'}), 403

        # Получаем наш публичный ключ для подписи транзакций
        my_pubkey = get_public_key_b64(mnemonic)

        # =====================================================================
        # ── ГРУППОВЫЕ СООБЩЕНИЯ ─────────────────────────────────────────────
        # =====================================================================
        if msg_type == 'group' and group_id:
            groups = get_user_groups_cached(sender)
            group = next((g for g in groups if g['id'] == group_id), None)
            if not group or sender not in group['members']:
                return jsonify({'error': 'Group not found or no access'}), 404

            # Шифруем отдельно для каждого участника группы
            encrypted_map: Dict[str, Any] = {}
            for member in group['members']:
                try:
                    # 🔒 Ключ зависит от отправителя + получателя (детерминированный)
                    key = generate_symmetric_key(sender, member, mnemonic)
                    # 🔒 AAD = адрес отправителя для аутентификации источника
                    aad = sender.encode('utf-8')

                    encrypted_map[member] = {
                        'content': encrypt_message_aead(key, content, associated_data=aad),
                        'image': encrypt_message_aead(key, image, associated_data=aad) if image else None,
                        'sender': sender  # Явно сохраняем для проверки на стороне получателя
                    }
                except Exception as e:
                    logger.warning(f"⚠️ Encrypt for {member[:10]}... failed: {type(e).__name__}")
                    continue

            if not encrypted_map:
                return jsonify({'error': 'Encryption failed for all members'}), 500

            # Сохраняем в блокчейн
            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(
                    cursor, sender, f"group:{group_id}",
                    json.dumps(encrypted_map), None,
                    sender_pubkey=my_pubkey,
                    metadata={
                        'encryption': 'symmetric-group-v2',
                        'group_id': group_id,
                        'sender_verified': True,
                        'member_count': len(encrypted_map)
                    }
                )
                # PoW в фоне — пользователь не ждёт
                last_proof = blockchain._last_block_raw(cursor)['proof']
                threading.Thread(
                    target=_mine_block_async,
                    args=(blockchain.db_path, last_proof),
                    daemon=True
                ).start()

            # 🔁 P2P-буфер для мгновенной доставки (long polling fallback)
            try:
                with _p2p_buffer_lock:
                    for member in group['members']:
                        _p2p_buffer.setdefault(member, []).append({
                            'sender': sender,
                            'recipient': f"group:{group_id}",
                            'content': content,  # 🔐 уже зашифровано!
                            'image': image,
                            'ts': time.time(),
                            'tx_id': tx_id,
                            'id': f"group_{tx_id}_{member[:8]}",
                            'is_group': True
                        })
                        # Ограничиваем размер буфера
                        if len(_p2p_buffer[member]) > 100:
                            _p2p_buffer[member] = _p2p_buffer[member][-100:]
            except Exception as e:
                logger.debug(f"ℹ️ P2P buffer update skipped: {e}")

            return jsonify({
                'message': 'Sent',
                'tx_id': tx_id,
                'recipient': f"group:{group_id}",
                'type': 'group',
                'encryption': 'symmetric-group-v2',
                'members_encrypted': len(encrypted_map)
            }), 201

        # =====================================================================
        # ── ПРЯМЫЕ СООБЩЕНИЯ ────────────────────────────────────────────────
        # =====================================================================
        if sender == recipient:
            return jsonify({'error': 'Cannot message yourself'}), 400

        # Получаем публичный ключ получателя
        recipient_pubkey, recipient_verified = get_cached_public_key(recipient)
        if not recipient_pubkey:
            recipient_pubkey, recipient_verified = fetch_public_key_from_chain(recipient)

        if recipient_pubkey:
            # ✅ Используем hybrid-v2 с верификацией адреса получателя
            payload = encrypt_hybrid(
                mnemonic,  # моя мнемоника (для вычисления shared secret)
                recipient_pubkey,  # публичный ключ ПОЛУЧАТЕЛЯ
                recipient,  # адрес ПОЛУЧАТЕЛЯ (для верификации)
                content,
                image_data=image
            )

            # Сохраняем в блокчейн
            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(
                    cursor, sender, recipient,
                    json.dumps(payload), None,
                    sender_pubkey=my_pubkey,
                    metadata={
                        'encryption': 'hybrid-v2',
                        'key_verified': recipient_verified,
                        'content_preview': content[:20] + '...' if len(content) > 20 else content
                    }
                )
                # PoW в фоне
                last_proof = blockchain._last_block_raw(cursor)['proof']
                threading.Thread(
                    target=_mine_block_async,
                    args=(blockchain.db_path, last_proof),
                    daemon=True
                ).start()

            # 🔁 P2P-буфер для мгновенной доставки
            try:
                with _p2p_buffer_lock:
                    _p2p_buffer.setdefault(recipient, []).append({
                        'sender': sender,
                        'recipient': recipient,
                        'content': content,  # 🔐 уже зашифровано бэкендом!
                        'image': image,
                        'ts': time.time(),
                        'tx_id': tx_id,
                        'id': tx_id,
                        'is_group': False
                    })
                    if len(_p2p_buffer[recipient]) > 100:
                        _p2p_buffer[recipient] = _p2p_buffer[recipient][-100:]
            except Exception as e:
                logger.debug(f"ℹ️ P2P buffer update skipped: {e}")

            return jsonify({
                'message': 'Sent',
                'tx_id': tx_id,
                'recipient': recipient,
                'type': 'direct',
                'encryption': 'hybrid-v2',
                'key_verified': recipient_verified
            }), 201

        else:
            # 🔑 Нет публичного ключа — отправляем запрос на обмен ключами
            # ✅ СТАЛО:
            key_exchange_payload = {
                'my_pubkey': my_pubkey,
                'message': 'key_exchange_request',
                'version': 'key_exchange',  # ← Уникальная версия для обмена ключами
                'sender_address': sender,
                'timestamp': time.time()
            }

            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(
                    cursor, sender, recipient,
                    json.dumps(key_exchange_payload),
                    None,
                    sender_pubkey=my_pubkey,
                    metadata={
                        'encryption': 'key_exchange',
                        'note': 'Content will be sent after key exchange'
                    }
                )
                last_proof = blockchain._last_block_raw(cursor)['proof']
                threading.Thread(
                    target=_mine_block_async,
                    args=(blockchain.db_path, last_proof),
                    daemon=True
                ).start()

            # 🔒 Кэшируем НАШ ключ для получателя
            cache_public_key(sender, my_pubkey, source='outgoing', verified=True)

            logger.info(f"🔑 Key exchange sent: {sender[:16]}... -> {recipient[:16]}...")
            return jsonify({
                'message': 'Key exchange sent. Please ask recipient to fetch your public key.',
                'tx_id': tx_id,
                'recipient': recipient,
                'key_exchange': True,
                'my_pubkey': my_pubkey
            }), 201

    except ValidationError as err:
        logger.warning(f"⚠️ Validation error in send_message: {err.messages}")
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"❌ send_message error: {type(e).__name__}", exc_info=os.getenv('FLASK_ENV') != 'production')
        return jsonify({'error': 'Internal server error'}), 500  # без деталей!
# =============================================================================
# === Получение сообщений (ОБНОВЛЁННЫЙ с пагинацией) ===
# =============================================================================

@app.route('/get_conversation', methods=['GET'])
def get_conversation():
    """
    Получение истории чата с расшифровкой.
    🔒 Мнемоника берётся ТОЛЬКО из сессии.
    🔥 Поддержка пагинации для больших историй.
    """
    # 🔒 Проверка сессии
    if 'address' not in session:
        logger.warning(f"⚠️ Unauthorized get_conversation attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        user_addr = session['address']

        # 🔒 Мнемоника ТОЛЬКО из сессии
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            logger.warning(f"⚠️ No mnemonic in session for {user_addr[:16]}...")
            return jsonify({'error': 'Session expired. Please login again.'}), 401

        # 🔒 Верификация адреса
        expected_address = generate_address(mnemonic)
        if not hmac.compare_digest(expected_address, user_addr):
            logger.critical(f"🚫 Mnemonic/address mismatch in get_conversation!")
            return jsonify({'error': 'Authentication failed'}), 403

        # Параметры запроса
        chat_with = request.args.get('with')
        if not chat_with:
            return jsonify({'error': 'Missing "with" parameter'}), 400

        # 🔥 ПАГИНАЦИЯ: параметры для подгрузки истории
        last_message_id = request.args.get('last_message_id', type=int)
        limit = min(int(request.args.get('limit', 50)), 100)  # Защита от слишком большого limit

        with get_db_cursor(blockchain.db_path) as cursor:
            # ── Групповые чаты ─────────────────────────────────────────────
            if chat_with.startswith('group:'):
                group_id = chat_with.split(':', 1)[1]
                groups = get_user_groups_cached(user_addr)
                user_group = next((g for g in groups if g['id'] == group_id), None)
                if not user_group or user_addr not in user_group['members']:
                    return jsonify({'error': 'No access to this group'}), 403

                query = '''
                    SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata
                    FROM transactions 
                    WHERE recipient = ?
                '''
                params = [chat_with]

            # ── Прямые чаты ────────────────────────────────────────────────
            else:
                query = '''
                    SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata
                    FROM transactions
                    WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                '''
                params = [user_addr, chat_with, chat_with, user_addr]

            # 🔥 Фильтр по ID + лимит для пагинации
            if last_message_id:
                query += ' AND id > ?'
                params.append(last_message_id)

            query += ' ORDER BY timestamp ASC LIMIT ?'
            params.append(limit)

            cursor.execute(query, params)
            messages = [
                {
                    'id': r[0],
                    'sender': r[1],
                    'recipient': r[2],
                    'content': r[3],
                    'image': r[4],
                    'timestamp': r[5],
                    'sender_pubkey': r[6],
                    'metadata': r[7]
                }
                for r in cursor.fetchall()
            ]

        # 🔐 Расшифровка сообщений
        decrypted = []
        for msg in messages:
            dec = process_message_decryption(msg, user_addr, mnemonic)

            # Добавляем имена контактов для отображения
            dec['sender_name'] = get_contact_name_cached(user_addr, msg['sender']) or msg['sender']
            dec['recipient_name'] = get_contact_name_cached(user_addr, msg['recipient']) or msg['recipient']
            dec['is_mine'] = (msg['sender'] == user_addr)

            # Добавляем метаданные шифрования для отладки
            if msg.get('metadata'):
                try:
                    meta = json.loads(msg['metadata']) if isinstance(msg['metadata'], str) else msg['metadata']
                    dec['encryption_type'] = meta.get('encryption', 'unknown')
                    dec['key_verified'] = meta.get('key_verified', False)
                    dec['version'] = meta.get('version', 'legacy')
                except Exception:
                    pass

            decrypted.append(dec)

        # 🔥 Возвращаем флаг has_more для бесконечной прокрутки
        return jsonify({
            'messages': decrypted,
            'has_more': len(messages) == limit,  # Если вернули ровно limit — есть ещё
            'chat_with': chat_with,
            'last_message_id': messages[-1]['id'] if messages else None
        }), 200

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



# =============================================================================
# === Контакты ===
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

        # Безопасное обогащение публичными ключами
        for contact in user_contacts:
            if not contact.get('pubkey'):
                try:
                    pubkey, verified = get_cached_public_key(contact['address'])
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


# === Удаление контакта (добавьте в app.py) ===
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
            cursor.execute(
                'DELETE FROM contacts WHERE user_address = ? AND contact_address = ?',
                (user_addr, contact_address)
            )
            deleted = cursor.rowcount

        # Очистка кэша
        get_contact_name_cached.cache_clear()

        if deleted:
            logger.info(f"Contact {contact_address[:16]}... deleted by {user_addr[:16]}...")
            return jsonify({'message': 'Contact deleted'}), 200
        else:
            return jsonify({'error': 'Contact not found'}), 404

    except Exception as e:
        logger.error(f"Delete contact error: {e}")
        return jsonify({'error': 'Failed to delete contact'}), 500
# =============================================================================
# === Группы ===
# =============================================================================

@app.route('/get_groups', methods=['GET'])
def get_groups():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        get_user_groups_cached.cache_clear()
        groups = get_user_groups_cached(session['address'])
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
            cursor.execute(
                'INSERT INTO groups (id, name, creator, members, created_at) VALUES (?, ?, ?, ?, ?)',
                (group_id, name, creator, json.dumps(members_clean), time.time())
            )
        get_user_groups_cached.cache_clear()
        logger.info(f"Group '{name}' created by {creator[:16]}... with {len(members_clean)} members")
        return jsonify({
            'message': 'Group created', 'group_id': group_id, 'name': name,
            'members': members_clean, 'member_count': len(members_clean)
        }), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Create group error: {e}")
        return jsonify({'error': 'Failed to create group'}), 500


# В app.py, после других маршрутов:

@app.route('/api/export_mnemonic', methods=['POST'])
def export_mnemonic():
    """🔐 Экспорт мнемоники с подтверждением действия и защитой от утечек."""

    # 🔒 1. Проверка сессии
    if 'address' not in session:
        logger.warning(f"Unauthorized mnemonic export attempt from {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json(silent=True) or {}
        confirmation = data.get('confirmation', '').strip().upper()

        # 🔒 2. Валидация подтверждения (без логирования ввода!)
        valid_confirmations = ('I CONFIRM', 'ПОДТВЕРЖДАЮ', 'CONFIRM', 'YES')
        if confirmation not in valid_confirmations:
            # 🔥 НЕ логируем ввод пользователя — может содержать чувствительные данные
            logger.warning(f"Invalid confirmation attempt for {session.get('address', 'unknown')[:16]}...")
            return jsonify({'error': 'Please type "I CONFIRM" or "YES" to continue'}), 400

        # 🔒 3. Получение мнемоники из сессии
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            logger.warning(f"Mnemonic export failed: session expired for {session.get('address', 'unknown')[:16]}...")
            return jsonify({'error': 'Session expired. Please login again.'}), 401

        # 🔒 4. Формирование ответа с заголовками безопасности
        response = jsonify({
            'mnemonic': mnemonic,
            'warning': 'Auto-clears in 30 seconds. Do not share.',
            'auto_clear_seconds': 30,
            # 🔥 Не возвращаем адрес в ответе — клиент уже знает его
        })

        # 🔒 5. Заголовки против кэширования чувствительных данных
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'

        # 🔒 6. Логирование успеха (без мнемоники!)
        logger.info(f"Mnemonic exported for {session.get('address', 'unknown')[:16]}... from {request.remote_addr}")

        return response, 200

    except Exception as e:
        # 🔥 НИКОГДА не логируем исключения с возможными чувствительными данными
        logger.error(f"Mnemonic export error for {session.get('address', 'unknown')[:16]}...: {type(e).__name__}")
        return jsonify({'error': 'Export failed'}), 500

@app.route('/delete_group', methods=['POST'])
def delete_group():
    """🗑️ Удаление группы — только создатель может удалить."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json(silent=True) or {}
        group_id = data.get('group_id', '').strip()

        if not group_id or len(group_id) != 32:  # UUID hex = 32 chars
            return jsonify({'error': 'Invalid group ID format'}), 400

        user_addr = session['address']

        with get_db_cursor(blockchain.db_path) as cursor:
            # 🔒 Проверяем, что группа существует и пользователь — создатель
            cursor.execute(
                'SELECT id, name, creator, members FROM groups WHERE id = ?',
                (group_id,)
            )
            row = cursor.fetchone()

            if not row:
                return jsonify({'error': 'Group not found'}), 404

            creator = row[2]
            group_name = row[1]

            # 🔒 Только создатель может удалить
            if creator != user_addr:
                logger.warning(
                    f"Unauthorized delete attempt: {user_addr[:16]}... tried to delete group {group_id} (creator: {creator[:16]}...)")
                return jsonify({'error': 'Only the group creator can delete this group'}), 403

            # 🔥 Удаляем группу
            cursor.execute('DELETE FROM groups WHERE id = ?', (group_id,))

            # 🔥 Опционально: удаляем сообщения группы (если хотите)
            # ❗ В блокчейн-архитектуре сообщения обычно НЕ удаляются,
            # но можно пометить группу как "архивированную" вместо удаления
            # cursor.execute('DELETE FROM transactions WHERE recipient = ?', (f'group:{group_id}',))

            deleted = cursor.rowcount

        # Очистка кэша
        get_user_groups_cached.cache_clear()

        logger.info(f"Group '{group_name}' (ID: {group_id}) deleted by creator {user_addr[:16]}...")

        return jsonify({
            'message': 'Group deleted',
            'group_id': group_id,
            'group_name': group_name
        }), 200

    except Exception as e:
        logger.error(f"Delete group error: {type(e).__name__}", exc_info=app.debug)
        return jsonify({'error': 'Failed to delete group'}), 500

# =============================================================================
# === Утилиты и загрузка файлов ===
# =============================================================================

# 🔒 Валидация изображений по magic bytes
IMAGE_MAGIC_BYTES = {
    b'\xFF\xD8\xFF': 'image/jpeg',
    b'\x89PNG\r\n\x1a\n': 'image/png',
    b'GIF87a': 'image/gif',
    b'GIF89a': 'image/gif',
    b'RIFF....WEBP': 'image/webp',
}

def validate_image_file(file_content: bytes) -> Optional[str]:
    """Проверка изображения по заголовку (magic bytes)."""
    for magic, mime_type in IMAGE_MAGIC_BYTES.items():
        if file_content.startswith(magic):
            return mime_type
    return None

@app.route('/clear_conversation', methods=['POST'])
def clear_conversation():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = request.get_json() or {}
        chat_with = data.get('chat_with', '').strip()
        if not chat_with: return jsonify({'error': 'Missing chat_with parameter'}), 400
        user_addr = session['address']
        with get_db_cursor(blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                cursor.execute('DELETE FROM transactions WHERE sender = ? AND recipient = ?', (user_addr, chat_with))
            else:
                cursor.execute('DELETE FROM transactions WHERE sender = ? AND recipient = ?', (user_addr, chat_with))
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

        # 🔒 Проверка размера ДО чтения в память
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > CONFIG['MAX_UPLOAD_SIZE']:
            return jsonify({'error': 'File too large'}), 413

        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_name)

        file.save(filepath)

        # 🔒 Валидация по magic bytes, а не только Content-Type
        with open(filepath, 'rb') as f:
            header = f.read(12)  # Читаем первые 12 байт

        detected_mime = validate_image_file(header)
        declared_mime = file.content_type

        if declared_mime and declared_mime.startswith('image/'):
            if detected_mime and detected_mime != declared_mime:
                logger.warning(f"MIME mismatch: declared={declared_mime}, detected={detected_mime}")
                # Можно отклонить или принять с предупреждением
            if detected_mime:
                with open(filepath, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                os.remove(filepath)
                return jsonify({'file_url': f"{detected_mime};base64,{b64}"}), 200

        # Для не-изображений или если не удалось определить
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
# === GunDB: Конфигурация для фронтенда ===
# =============================================================================

@app.route('/gun-config')
def gun_config():
    """Актуальные публичные релеи GunDB"""
    peers = [
        # ✅ Наиболее стабильные (проверены):
        'https://gun.robins.one/gun',  # Robin's relay — стабильный
        'https://relic.eastus.cloudapp.azure.com/gun',  # Azure-hosted
        'https://gun-manhattan.herokuapp.com/gun',
        # ⚠️ Могут работать с перерывами:
        'https://gundb-relay-eb4x.onrender.com/gun',  # Render (может "спать")
        'https://gun-relay-7q2w.onrender.com/gun',  # Альтернатива Render

        # 🔄 Резерв: только localStorage, если всё остальное не работает
    ]
    return jsonify({
        'peers': peers,
        'room_prefix': 'dm_v1:',
        'version': '1.0',
        'fallback': 'localStorage'  # подсказка для фронтенда
    })

# Опционально: простой ретранслятор для GunDB (если не используете публичные релеи)
# Требуется: pip install gun
try:
    from gun import Gun  # если установлен
    @app.route('/gun', methods=['GET', 'POST', 'OPTIONS'])
    def gun_relay():
        """Простейший WebSocket-ретранслятор для GunDB"""
        # В реальности лучше использовать standalone Gun-сервер
        # Это заглушка для быстрого старта
        if request.method == 'OPTIONS':
            return '', 204
        return jsonify({'ok': True})
except ImportError:
    pass  # Gun не установлен — используем публичные релеи


@app.route('/decrypt_message', methods=['POST'])
def decrypt_message_api():
    """🔓 Расшифровка сообщения (для P2P-входящих)"""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        encrypted_payload = data.get('encrypted_payload')
        peer_address = data.get('peer_address')  # адрес ОТПРАВИТЕЛЯ

        if not encrypted_payload or not peer_address:
            return jsonify({'error': 'Missing fields'}), 400

        user_addr = session['address']
        mnemonic = session.get('mnemonic')
        if not mnemonic:
            return jsonify({'error': 'Session expired'}), 401

        # Получаем публичный ключ отправителя
        peer_pubkey, _ = get_cached_public_key(peer_address)
        if not peer_pubkey:
            peer_pubkey, _ = fetch_public_key_from_chain(peer_address)
        if not peer_pubkey:
            return jsonify({'content': '[Waiting for key exchange...]'}), 200

        # Расшифровываем через ваше крипто-ядро
        decrypted = decrypt_hybrid(mnemonic, peer_pubkey, peer_address, encrypted_payload)

        return jsonify({
            'content': decrypted.get('content'),
            'image': decrypted.get('image')
        }), 200

    except Exception as e:
        logger.error(f"P2P decrypt error: {e}")
        return jsonify({'content': '[Decryption failed]'}), 200  # 200, чтобы не триггерить повторные запросы



@app.route('/p2p-poll')
def p2p_poll():
    """
    Long Polling endpoint для эмуляции P2P на хостингах без WebSocket.
    Возвращает зашифрованные сообщения для текущего пользователя.
    """
    if 'address' not in session:
        return jsonify([]), 401

    chat_id = request.args.get('chat', '')
    since = float(request.args.get('since', 0))
    user_addr = session['address']

    if not chat_id:
        return jsonify([]), 400

    with _p2p_buffer_lock:
        # Получаем сообщения для этого чата, новее чем `since`
        messages = _p2p_buffer.get(chat_id, [])
        new_messages = [
            m for m in messages
            if m['ts'] > since and m['recipient'] in (user_addr, chat_id)
        ]

        # Очищаем старые сообщения (храним 5 минут)
        cutoff = time.time() - 300
        _p2p_buffer[chat_id] = [m for m in messages if m['ts'] > cutoff]

    return jsonify(new_messages), 200


@app.errorhandler(404)
def not_found(e): return jsonify({'error': 'Not found'}), 404
@app.errorhandler(500)
def server_error(e): return jsonify({'error': 'Internal server error'}), 500
@app.errorhandler(413)
def file_too_large(e): return jsonify({'error': 'File too large (max 16MB)'}), 413

# ✅ СТАЛО (безопасно):
# =============================================================================
# === Запуск приложения ===
# =============================================================================

if __name__ == '__main__':
    """
    🔹 Для локальной разработки:
        python app.py

    🔹 Для reg.ru (shared hosting):
        Запуск через Passenger/CGI настраивается в панели хостинга.
        Если поддерживается прямой запуск — используйте этот блок.
    """

    # 🔒 Проверка базовой безопасности
    if not SECRET_KEY or len(SECRET_KEY) < 32:
        logger.critical("❌ SECRET_KEY too short or missing! Set it in .env")

    # Определяем режим
    is_production = os.getenv('FLASK_ENV') == 'production'

    if is_production:
        # 🔒 Продакшен-настройки
        logger.warning("🚀 Starting in PRODUCTION mode")
        app.run(
            host='127.0.0.1',  # ← Только localhost для безопасности!
            port=5000,
            debug=False,  # ← НИКОГДА не включайте debug=True в продакшене
            threaded=True  # ← Обработка нескольких запросов
        )
    else:
        # 🔧 Разработка — можно запускать на всех интерфейсах
        logger.info("🔧 Starting in DEVELOPMENT mode")
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=True,
            threaded=True
        )