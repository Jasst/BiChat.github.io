"""
app.py — Децентрализованный мессенджер с гибридным шифрованием
Версия: 3.0 (ECDH + AES, полная P2P-безопасность)
"""
import hashlib
import os
import base64
import logging
import logging.handlers
import sqlite3
import time
import json
import uuid
import threading
from functools import lru_cache, wraps
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Callable

from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory
from mnemonic import Mnemonic
from marshmallow import Schema, fields, ValidationError, post_load
from werkzeug.utils import secure_filename

from crypto_manager import (
    # Гибридное шифрование
    encrypt_hybrid,
    decrypt_hybrid,
    get_public_key_b64,
    load_public_key_from_b64,
    compute_shared_key_b64,
    # Симметричное (для групп)
    generate_symmetric_key,
    encrypt_message,
    decrypt_message,
    # Утилиты
    generate_address,
    clear_key_cache,
    get_cache_info
)

# === Конфигурация ===
CONFIG = {
    'POW_DIFFICULTY': 3,
    'POW_MAX_ITERATIONS': 50000,
    'CACHE_SIZE_KEYS': 128,
    'CACHE_SIZE_GROUPS': 32,
    'CACHE_SIZE_CONTACTS': 64,
    'CACHE_SIZE_PUBKEYS': 256,
    'DB_TIMEOUT': 30.0,
    'SESSION_LIFETIME': 3600,
    'LOG_MAX_BYTES': 10 * 1024 * 1024,
    'LOG_BACKUP_COUNT': 5,
}

DATABASE_PATH = 'blockchain.db'
UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
TEMPLATE_FOLDER = 'templates'
SECRET_KEY = os.getenv('SECRET_KEY', 'CHANGE_THIS_IN_PRODUCTION_Jasstme666')
MAX_CONTENT_LENGTH = 16 * 1024 * 1024


# === Логирование ===
def setup_logging():
    file_handler = logging.handlers.RotatingFileHandler(
        'messenger.log', maxBytes=CONFIG['LOG_MAX_BYTES'],
        backupCount=CONFIG['LOG_BACKUP_COUNT'], encoding='utf-8', delay=True
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    log_level = logging.INFO if os.getenv('FLASK_ENV') != 'production' else logging.WARNING
    logging.basicConfig(level=log_level, handlers=[file_handler] +
                                                  ([console_handler] if os.getenv('FLASK_ENV') != 'production' else []))
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlite3').setLevel(logging.ERROR)
    logging.getLogger('cryptography').setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)


# === Утилиты БД ===
@contextmanager
def get_db_cursor(db_path: str):
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=CONFIG['DB_TIMEOUT'],
                               check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
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


# === Кэширование ===
def timed_cache(duration: int):
    def decorator(func: Callable) -> Callable:
        cache: Dict[str, tuple] = {}
        lock = threading.Lock()

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{args}:{kwargs}"
            now = time.time()
            with lock:
                if key in cache:
                    result, timestamp = cache[key]
                    if now - timestamp < duration:
                        return result
            result = func(*args, **kwargs)
            with lock:
                expired = [k for k, (_, t) in cache.items() if now - t >= duration]
                for k in expired: del cache[k]
                cache[key] = (result, now)
            return result

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator


# === Создание таблиц ===
def create_contacts_table(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_address TEXT NOT NULL,
        contact_address TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        contact_pubkey TEXT,
        created_at REAL,
        UNIQUE(user_address, contact_address)
    )''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)')


def create_group_table(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, creator TEXT NOT NULL,
        members TEXT NOT NULL, created_at REAL
    )''')


def create_pubkey_cache_table(cursor):
    """Таблица для кэширования публичных ключей."""
    cursor.execute('''CREATE TABLE IF NOT EXISTS pubkey_cache (
        address TEXT PRIMARY KEY,
        public_key_b64 TEXT NOT NULL,
        updated_at REAL,
        source TEXT DEFAULT 'blockchain'
    )''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_pubkey_updated ON pubkey_cache(updated_at)')


# === Blockchain класс ===
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL, recipient TEXT NOT NULL,
            content TEXT, image TEXT, timestamp REAL,
            sender_pubkey TEXT, metadata TEXT
        )''')
        create_contacts_table(cursor)
        create_group_table(cursor)
        create_pubkey_cache_table(cursor)

    def _create_indexes(self, cursor):
        for sql in [
            'CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)',
        ]:
            cursor.execute(sql)

    def _new_block_raw(self, cursor, proof: int, previous_hash: Optional[str] = None) -> None:
        last = self._last_block_raw(cursor)
        block_index = last.get('index', 0) + 1
        block = {
            'index': block_index, 'timestamp': time.time(),
            'transactions': [], 'proof': proof,
            'previous_hash': previous_hash or self._hash_block(last),
        }
        cursor.execute('''INSERT INTO blockchain 
            (block_index, timestamp, transactions, proof, previous_hash) VALUES (?, ?, ?, ?, ?)''',
                       (block['index'], block['timestamp'], json.dumps(block['transactions']),
                        block['proof'], block['previous_hash']))

    def _hash_block(self, block: Dict[str, Any]) -> str:
        if not block: return '0' * 64
        return hashlib.sha256(json.dumps(block, sort_keys=True).encode()).hexdigest()

    def _last_block_raw(self, cursor):
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
                        image: Optional[str], sender_pubkey: Optional[str] = None,
                        metadata: Optional[Dict] = None) -> int:
        cursor.execute('''INSERT INTO transactions 
            (sender, recipient, content, image, timestamp, sender_pubkey, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
                       (sender, recipient, content, image, time.time(),
                        sender_pubkey, json.dumps(metadata) if metadata else None))
        return cursor.lastrowid

    def get_messages(self, cursor, address: str) -> List[Dict[str, Any]]:
        cursor.execute('''SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata
            FROM transactions WHERE sender = ? OR recipient = ? OR recipient LIKE 'group:%'
            ORDER BY timestamp ASC''', (address, address))
        return [{'id': r[0], 'sender': r[1], 'recipient': r[2], 'content': r[3],
                 'image': r[4], 'timestamp': r[5], 'sender_pubkey': r[6], 'metadata': r[7]}
                for r in cursor.fetchall()]

    def proof_of_work(self, last_proof: int) -> int:
        proof = 0
        target = "0" * CONFIG['POW_DIFFICULTY']
        while proof < CONFIG['POW_MAX_ITERATIONS']:
            if hashlib.sha256(f'{last_proof}{proof}'.encode()).hexdigest()[:CONFIG['POW_DIFFICULTY']] == target:
                return proof
            proof += 1
        return proof


# === Flask app ===
app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.config.update(
    SECRET_KEY=SECRET_KEY, UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=CONFIG['SESSION_LIFETIME'],
)

mnemonic_gen = Mnemonic('english')
blockchain = Blockchain(DATABASE_PATH)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# === Схемы валидации (без изменений) ===
class WalletSchema(Schema):
    mnemonic_phrase = fields.Str(required=True, load_only=True)

    @post_load
    def strip(self, data, **kwargs):
        data['mnemonic_phrase'] = data['mnemonic_phrase'].strip()
        return data


class MessageSchema(Schema):
    recipient = fields.Str(required=True)
    content = fields.Str(required=True, allow_none=False)
    image = fields.Str(allow_none=True)
    message_type = fields.Str(load_default='direct', validate=lambda x: x in ('direct', 'group'))
    group_id = fields.Str(allow_none=True)


class GroupSchema(Schema):
    name = fields.Str(required=True, validate=lambda x: 1 <= len(x) <= 100)
    members = fields.List(fields.Str(), required=True, validate=lambda x: 1 <= len(x) <= 50)


class ContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)
    name = fields.Str(required=True, validate=lambda x: 1 <= len(x) <= 50)


class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True, validate=lambda x: x > 0)


# === Кэш публичных ключей ===
@timed_cache(duration=3600)
@lru_cache(maxsize=CONFIG['CACHE_SIZE_PUBKEYS'])
def get_cached_public_key(address: str) -> Optional[str]:
    """Получает публичный ключ из локального кэша/БД."""
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('SELECT public_key_b64 FROM pubkey_cache WHERE address = ?', (address,))
        row = cursor.fetchone()
        return row[0] if row else None


def cache_public_key(address: str, pubkey_b64: str, source: str = 'message') -> bool:
    """Сохраняет публичный ключ в кэш."""
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('''INSERT OR REPLACE INTO pubkey_cache 
                (address, public_key_b64, updated_at, source) VALUES (?, ?, ?, ?)''',
                           (address, pubkey_b64, time.time(), source))
        get_cached_public_key.cache_clear()
        return True
    except Exception as e:
        logger.error(f"Cache pubkey error: {e}")
        return False


def fetch_public_key_from_chain(address: str) -> Optional[str]:
    """Ищет публичный ключ в истории блокчейна (транзакции key_register)."""
    with get_db_cursor(blockchain.db_path) as cursor:
        # Ищем транзакцию, где sender=address и metadata содержит pubkey
        cursor.execute('''SELECT sender_pubkey, metadata FROM transactions 
            WHERE sender = ? AND sender_pubkey IS NOT NULL 
            ORDER BY timestamp DESC LIMIT 1''', (address,))
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]  # sender_pubkey хранится отдельно
        # Альтернатива: парсим metadata
        if row and row[1]:
            try:
                meta = json.loads(row[1])
                if meta.get('pubkey'):
                    return meta['pubkey']
            except:
                pass
    return None

# =============================================================================
# === ФУНКЦИЯ: Добавить контакт в БД ===
# =============================================================================
def add_contact(user_address: str, contact_address: str, contact_name: str) -> bool:
    """Добавляет контакт в локальную БД пользователя."""
    if not contact_name:
        contact_name = contact_address[:10] + "..."
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute(
                'INSERT OR REPLACE INTO contacts (user_address, contact_address, contact_name, created_at) VALUES (?, ?, ?, ?)',
                (user_address, contact_address, contact_name, time.time())
            )
        # Очищаем кэш, если он есть
        if 'get_contact_name_cached' in globals():
            get_contact_name_cached.cache_clear()
        return True
    except Exception as e:
        logger.error(f"Add contact DB error: {e}")
        return False


def get_contacts(user_address: str) -> List[Dict[str, Any]]:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('''SELECT contact_address, contact_name, contact_pubkey, created_at 
            FROM contacts WHERE user_address = ? ORDER BY contact_name COLLATE NOCASE''',
                       (user_address,))
        return [{'address': row[0], 'name': row[1], 'pubkey': row[2], 'created_at': row[3]}
                for row in cursor.fetchall()]


# === Расшифровка сообщений ===
def decrypt_message_safe(key: bytes, encrypted_data: Optional[str], fallback: str = "[Decryption Failed]") -> Optional[
    str]:
    if not encrypted_data: return None
    try:
        result = decrypt_message(key, encrypted_data)
        return result if result else fallback
    except Exception as e:
        logger.warning(f"Decryption failed: {e}")
        return fallback


def process_message_decryption(msg: Dict, user_address: str, mnemonic: str) -> Dict:
    """Универсальная расшифровка с поддержкой гибридного формата."""
    result = msg.copy()

    try:
        # Групповые чаты (симметричное шифрование, как раньше)
        if msg['recipient'].startswith('group:'):
            group_id = msg['recipient'].split(':', 1)[1]
            groups = get_user_groups_cached(user_address)
            user_group = next((g for g in groups if g['id'] == group_id), None)
            if not user_group or user_address not in user_group['members']:
                result.update({'content': "[No access]", 'image': None})
                return result

            try:
                encrypted_data = json.loads(msg['content']) if isinstance(msg['content'], str) else msg['content']
                if user_address not in encrypted_data:
                    result.update({'content': "[No data]", 'image': None})
                    return result
                user_data = encrypted_data[user_address]
                key = generate_symmetric_key(msg['sender'], user_address, mnemonic)
                result['content'] = decrypt_message_safe(key, user_data.get('content'))
                result['image'] = decrypt_message_safe(key, user_data.get('image'))
            except json.JSONDecodeError:
                result.update({'content': "[Invalid JSON]", 'image': None})

        # Прямые сообщения (гибридное шифрование)
        else:
            # Проверяем формат: старый (прямой AES) или новый (гибридный)
            try:
                payload = json.loads(msg['content']) if isinstance(msg['content'], str) else None
            except:
                payload = None

            if payload and isinstance(payload, dict) and payload.get('version') == 'hybrid-v1':
                # === НОВЫЙ ГИБРИДНЫЙ ФОРМАТ ===
                # 🔧 КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ:
                # Для расшифровки нужен публичный ключ СОБЕСЕДНИКА, не отправителя!

                if msg['sender'] == user_address:
                    # 👤 Я отправитель → нужен публичный ключ ПОЛУЧАТЕЛЯ
                    peer_pubkey = get_cached_public_key(msg['recipient'])
                    if not peer_pubkey:
                        peer_pubkey = fetch_public_key_from_chain(msg['recipient'])
                    peer_address = msg['recipient']
                else:
                    # 👤 Я получатель → нужен публичный ключ ОТПРАВИТЕЛЯ
                    peer_pubkey = msg.get('sender_pubkey')
                    if not peer_pubkey:
                        peer_pubkey = get_cached_public_key(msg['sender'])
                    if not peer_pubkey:
                        peer_pubkey = fetch_public_key_from_chain(msg['sender'])
                    peer_address = msg['sender']

                if not peer_pubkey:
                    result['content'] = "[Waiting for key exchange...]"
                    result['image'] = None
                    return result

                # Сохраняем ключ собеседника в кэш
                cache_public_key(peer_address, peer_pubkey)

                # Стало: ✅ Расшифровка и контента, и изображения
                decrypted = decrypt_hybrid(mnemonic, peer_pubkey, payload)
                result['content'] = decrypted.get('content') if decrypted.get('content') else "[Decryption Failed]"
                result['image'] = decrypted.get('image')  # Может быть None, если изображения не было

            else:
                # === СТАРЫЙ ФОРМАТ (обратная совместимость) ===
                peer_pubkey = get_cached_public_key(
                    msg['sender'] if msg['sender'] != user_address else msg['recipient'])
                if peer_pubkey:
                    shared_key = compute_shared_key_b64(mnemonic, peer_pubkey)
                    content = decrypt_message(shared_key, msg['content'])
                    if content:
                        result['content'] = content
                        result['image'] = decrypt_message(shared_key, msg['image']) if msg['image'] else None
                        return result

                # Фоллбэк на старую симметричную схему
                key = generate_symmetric_key(msg['sender'], msg['recipient'], mnemonic)
                result['content'] = decrypt_message_safe(key, msg['content'])
                result['image'] = decrypt_message_safe(key, msg['image'])

    except Exception as e:
        logger.error(f"Message processing error: {e}")
        result.update({'content': '[Error]', 'image': None})

    if app.debug and payload and payload.get('version') == 'hybrid-v1':
        logger.debug(f"""
        [HYBRID DEBUG]
        user_address: {user_address[:16]}...
        msg sender: {msg['sender'][:16]}...
        msg recipient: {msg['recipient'][:16]}...
        peer_pubkey used: {peer_pubkey[:40] if peer_pubkey else 'None'}...
        decrypted: {result['content'][:50] if result['content'] and len(result['content']) > 50 else result['content']}
        """)
    return result


# === Список диалогов ===
def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    conversations = {}
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('''SELECT DISTINCT CASE WHEN sender = ? THEN recipient ELSE sender END as partner
                FROM transactions WHERE sender = ? OR recipient = ?''',
                           (user_address, user_address, user_address))
            for row in cursor.fetchall():
                partner = row[0]
                if partner == user_address: continue
                if partner.startswith('group:'):
                    group_id = partner.split(':', 1)[1]
                    groups = get_user_groups_cached(user_address)
                    group = next((g for g in groups if g['id'] == group_id), None)
                    if group:
                        conversations[partner] = {'address': partner, 'name': group['name'], 'is_group': True}
                else:
                    name = get_contact_name_cached(user_address, partner) or partner[:10] + "..."
                    conversations[partner] = {'address': partner, 'name': name, 'is_group': False}
    except Exception as e:
        logger.error(f"Get conversations error: {e}")
    return list(conversations.values())


@timed_cache(duration=300)
@lru_cache(maxsize=CONFIG['CACHE_SIZE_CONTACTS'])
def get_contact_name_cached(user_address: str, contact_address: str) -> Optional[str]:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('SELECT contact_name FROM contacts WHERE user_address = ? AND contact_address = ?',
                       (user_address, contact_address))
        row = cursor.fetchone()
        return row[0] if row else None


@timed_cache(duration=300)
def get_user_groups_cached(address: str) -> List[Dict[str, Any]]:
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('SELECT id, name, creator, members, created_at FROM groups')
        groups = []
        for row in cursor.fetchall():
            members = json.loads(row[3])
            if address in members:
                groups.append({'id': row[0], 'name': row[1], 'creator': row[2],
                               'members': members, 'created_at': row[4]})
        return groups


# === Маршруты ===
@app.before_request
def log_request():
    if app.debug: logger.debug(f"{request.method} {request.path}")


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
        # Кэшируем свой публичный ключ
        my_pubkey = get_public_key_b64(phrase)
        cache_public_key(address, my_pubkey, source='self')
        logger.info(f"Wallet created: {address[:16]}...")
        return jsonify({'mnemonic_phrase': phrase, 'address': address, 'public_key': my_pubkey}), 201
    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        return jsonify({'error': 'Wallet creation failed'}), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            data = WalletSchema().load(request.get_json())
            phrase = data['mnemonic_phrase'].strip()
            if not mnemonic_gen.check(phrase):
                return jsonify({'error': 'Invalid mnemonic phrase'}), 400
            address = generate_address(phrase)
            session['address'] = address
            session['mnemonic'] = phrase
            session.permanent = True
            # Кэшируем свой публичный ключ
            my_pubkey = get_public_key_b64(phrase)
            cache_public_key(address, my_pubkey, source='self')
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


# В app.py, добавьте в маршрут /chat:
@app.route('/chat')
def chat():
    if 'address' not in session: return redirect(url_for('index'))
    # Поддержка ?start_with= для прямого перехода в чат
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
    my_pubkey = get_public_key_b64(session['mnemonic']) if session.get('mnemonic') else None
    return render_template('profile.html', address=session.get('address'),
                           mnemonic=session.get('mnemonic'), public_key=my_pubkey,
                           cache_stats=get_cache_info() if app.debug else None)


@app.route('/get_public_key/<address>')
def get_public_key_route(address: str):
    """API для получения публичного ключа по адресу."""
    pubkey = get_cached_public_key(address)
    if not pubkey:
        pubkey = fetch_public_key_from_chain(address)
    if pubkey:
        return jsonify({'address': address, 'public_key': pubkey}), 200
    return jsonify({'error': 'Public key not found'}), 404


@app.route('/send_message', methods=['POST'])
def send_message():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
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
            return jsonify({'error': 'Session expired'}), 401

        # Мой публичный ключ (для вложения в сообщение)
        my_pubkey = get_public_key_b64(mnemonic)

        if msg_type == 'group' and group_id:
            # Групповые чаты: симметричное шифрование (как раньше)
            groups = get_user_groups_cached(sender)
            group = next((g for g in groups if g['id'] == group_id), None)
            if not group:
                return jsonify({'error': 'Group not found'}), 404

            encrypted_map = {}
            for member in group['members']:
                if member == sender: continue
                try:
                    key = generate_symmetric_key(sender, member, mnemonic)
                    encrypted_map[member] = {
                        'content': encrypt_message(key, content),
                        'image': encrypt_message(key, image) if image else None
                    }
                except Exception as e:
                    logger.warning(f"Encrypt for {member[:10]}... failed: {e}")
                    continue

            if not encrypted_map:
                return jsonify({'error': 'Encryption failed'}), 500

            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(cursor, sender, f"group:{group_id}",
                                                   json.dumps(encrypted_map), None, sender_pubkey=my_pubkey)
                last_proof = blockchain._last_block_raw(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain._new_block_raw(cursor, proof)

        else:
            # Прямые сообщения: ГИБРИДНОЕ шифрование
            if sender == recipient:
                return jsonify({'error': 'Cannot message yourself'}), 400

            # Получаем публичный ключ получателя
            recipient_pubkey = get_cached_public_key(recipient)
            if not recipient_pubkey:
                recipient_pubkey = fetch_public_key_from_chain(recipient)

            if recipient_pubkey:
                # Стало: ✅ Один вызов для контента + изображения
                payload = encrypt_hybrid(mnemonic, recipient_pubkey, content, image_data=image)

                with get_db_cursor(blockchain.db_path) as cursor:
                    tx_id = blockchain.new_transaction(
                        cursor, sender, recipient,
                        json.dumps(payload), None,
                        sender_pubkey=my_pubkey,
                        metadata={'encryption': 'hybrid-v1'}
                    )
                    last_proof = blockchain._last_block_raw(cursor)['proof']
                    proof = blockchain.proof_of_work(last_proof)
                    blockchain._new_block_raw(cursor, proof)

            else:
                # === KEY EXCHANGE: отправляем свой публичный ключ ===
                # Создаём специальное сообщение-приглашение
                key_exchange_payload = {
                    'my_pubkey': my_pubkey,
                    'content': None,
                    'message': 'key_exchange_request',
                    'version': 'hybrid-v1'
                }

                with get_db_cursor(blockchain.db_path) as cursor:
                    tx_id = blockchain.new_transaction(
                        cursor, sender, recipient,
                        json.dumps(key_exchange_payload), None,
                        sender_pubkey=my_pubkey,
                        metadata={'encryption': 'key_exchange'}
                    )
                    last_proof = blockchain._last_block_raw(cursor)['proof']
                    proof = blockchain.proof_of_work(last_proof)
                    blockchain._new_block_raw(cursor, proof)

                # Кэшируем, что мы отправили ключ этому контакту
                cache_public_key(recipient, my_pubkey, source='outgoing')

                logger.info(f"Key exchange sent: {sender[:16]}... -> {recipient[:16]}...")
                return jsonify({
                    'message': 'Key exchange sent',
                    'tx_id': tx_id,
                    'recipient': recipient,
                    'key_exchange': True
                }), 201

        logger.info(f"Message sent: {sender[:16]}... -> {recipient[:16]}...")
        return jsonify({
            'message': 'Sent', 'tx_id': tx_id,
            'recipient': recipient, 'type': msg_type,
            'group_id': group_id, 'encryption': 'hybrid-v1' if msg_type == 'direct' else 'symmetric'
        }), 201

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Send message error: {e}")
        return jsonify({'error': 'Failed to send'}), 500


@app.route('/get_conversation', methods=['GET'])
def get_conversation():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        user_addr = session['address']
        mnemonic = session.get('mnemonic')
        if not mnemonic: return jsonify({'error': 'Session expired'}), 401

        chat_with = request.args.get('with')
        if not chat_with: return jsonify({'error': 'Missing "with" param'}), 400

        with get_db_cursor(blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                cursor.execute('''SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata
                    FROM transactions WHERE recipient = ? ORDER BY timestamp ASC''', (chat_with,))
            else:
                cursor.execute('''SELECT id, sender, recipient, content, image, timestamp, sender_pubkey, metadata
                    FROM transactions WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?) 
                    ORDER BY timestamp ASC''', (user_addr, chat_with, chat_with, user_addr))

            messages = [{'id': r[0], 'sender': r[1], 'recipient': r[2], 'content': r[3],
                         'image': r[4], 'timestamp': r[5], 'sender_pubkey': r[6], 'metadata': r[7]}
                        for r in cursor.fetchall()]

        decrypted = []
        for msg in messages:
            dec = process_message_decryption(msg, user_addr, mnemonic)
            dec['sender_name'] = get_contact_name_cached(user_addr, msg['sender']) or msg['sender']
            dec['recipient_name'] = get_contact_name_cached(user_addr, msg['recipient']) or msg['recipient']
            dec['is_mine'] = msg['sender'] == user_addr
            # Добавляем метаданные о типе шифрования для отладки
            if msg.get('metadata'):
                try:
                    meta = json.loads(msg['metadata']) if isinstance(msg['metadata'], str) else msg['metadata']
                    dec['encryption_type'] = meta.get('encryption', 'unknown')
                except:
                    pass
            decrypted.append(dec)

        return jsonify({'messages': decrypted}), 200
    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/get_conversations', methods=['GET'])
def get_conversations_route():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        return jsonify({'conversations': get_conversations_list(session['address'])}), 200
    except Exception as e:
        logger.error(f"Get conversations error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/add_contact', methods=['POST'])
def add_contact_route():
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    try:
        data = ContactSchema().load(request.get_json())
        if add_contact(session['address'], data['address'], data['name']):
            return jsonify({'message': 'Contact added'}), 201
        return jsonify({'error': 'Failed to add'}), 500
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Add contact error: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/get_contacts', methods=['GET'])
def get_contacts_route():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        contacts = get_contacts(session['address'])
        # Добавляем публичные ключи из кэша, если не указаны
        for contact in contacts:
            if not contact.get('pubkey'):
                contact['pubkey'] = get_cached_public_key(contact['address'])
        return jsonify({'contacts': contacts}), 200
    except Exception as e:
        logger.error(f"Get contacts API error: {e}")
        return jsonify({'error': 'Failed'}), 500


# === Остальные маршруты (upload, delete и т.д.) — без изменений ===

@app.route('/upload_file', methods=['POST'])
def upload_file():
    if 'address' not in session: return jsonify({'error': 'Unauthorized'}), 401
    try:
        if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
        file = request.files['file']
        if file.filename == '': return jsonify({'error': 'Empty filename'}), 400
        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(filepath)
        if file.content_type and file.content_type.startswith('image/'):
            with open(filepath, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
            os.remove(filepath)
            return jsonify({'file_url': f"{file.content_type};base64,{b64}"}), 200
        return jsonify({'file_url': f"/uploads/{unique_name}"}), 200
    except Exception as e:
        logger.error(f"Upload error: {e}")
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
            if not row or row[0] != user_addr:
                return jsonify({'error': 'Not found or permission denied'}), 403
            cursor.execute('DELETE FROM transactions WHERE id = ?', (data['message_id'],))
        logger.info(f"Message #{data['message_id']} deleted by {user_addr[:16]}...")
        return jsonify({'message': 'Deleted'}), 200
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Delete message error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.errorhandler(404)
def not_found(e): return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e): return jsonify({'error': 'Server error'}), 500


@app.errorhandler(413)
def file_too_large(e): return jsonify({'error': 'File too large (max 16MB)'}), 413


# =============================================================================
# === МАРШРУТ: Добавить контакт из чата ===
# =============================================================================
@app.route('/add_contact_from_chat', methods=['POST'])
def add_contact_from_chat():
    """API: Добавить собеседника из текущего чата в контакты."""
    if 'address' not in session:
        logger.warning("Unauthorized add_contact_from_chat attempt")
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        raw_data = request.get_json() or {}
        contact_address = raw_data.get('contact_address', '').strip()
        contact_name = raw_data.get('contact_name', '').strip()

        logger.info(f"add_contact_from_chat: address={contact_address[:16]}..., name={contact_name}")

        # Валидация
        if not contact_address or len(contact_address) != 64:
            return jsonify({'error': 'Invalid address format'}), 400
        if not contact_name:
            contact_name = contact_address[:10] + '...'

        # Добавляем контакт
        if add_contact(session['address'], contact_address, contact_name):
            logger.info(f"✅ Contact {contact_address[:16]}... added from chat")
            return jsonify({'message': 'Contact added'}), 201
        else:
            return jsonify({'error': 'Failed to add to database'}), 500

    except Exception as e:
        logger.error(f"💥 add_contact_from_chat error: {e}", exc_info=True)
        return jsonify({'error': f'Server error: {str(e)[:100]}'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)