# app.py - Оптимизированный децентрализованный мессенджер
# Версия: 2.1 (с кэшированием, оптимизацией БД и PoW)

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
    encrypt_message,
    decrypt_message,
    generate_key,
    generate_address,
    clear_key_cache,
    get_cache_info
)

# === Конфигурация производительности ===
CONFIG = {
    'POW_DIFFICULTY': 3,  # Сложность PoW: 3 = "000" (быстро), 4 = "0000" (медленно)
    'POW_MAX_ITERATIONS': 50000,  # Макс. итераций PoW для защиты от зависания
    'CACHE_SIZE_KEYS': 128,  # Кэш ключей шифрования
    'CACHE_SIZE_GROUPS': 32,  # Кэш групп пользователя
    'CACHE_SIZE_CONTACTS': 64,  # Кэш имён контактов
    'DB_TIMEOUT': 30.0,  # Таймаут блокировки БД (сек)
    'SESSION_LIFETIME': 3600,  # Время жизни сессии (сек)
    'LOG_MAX_BYTES': 10 * 1024 * 1204,  # 10 MB
    'LOG_BACKUP_COUNT': 5,  # Количество архивных логов
}

# === Пути и настройки ===
DATABASE_PATH = 'blockchain.db'
UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
TEMPLATE_FOLDER = 'templates'
SECRET_KEY = os.getenv('SECRET_KEY', 'CHANGE_THIS_IN_PRODUCTION_Jasstme666')
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload


# === Настройка логирования с ротацией ===
def setup_logging():
    """Настраивает логирование с ротацией файлов."""
    # Создаём хендлер с ротацией
    file_handler = logging.handlers.RotatingFileHandler(
        'messenger.log',
        maxBytes=CONFIG['LOG_MAX_BYTES'],
        backupCount=CONFIG['LOG_BACKUP_COUNT'],
        encoding='utf-8',
        delay=True
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # Консольный хендлер для разработки
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    # Базовая конфигурация
    log_level = logging.INFO if os.getenv('FLASK_ENV') != 'production' else logging.WARNING
    logging.basicConfig(
        level=log_level,
        handlers=[file_handler] + ([console_handler] if os.getenv('FLASK_ENV') != 'production' else [])
    )

    # Снижаем шум от сторонних библиотек
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlite3').setLevel(logging.ERROR)
    logging.getLogger('cryptography').setLevel(logging.WARNING)


setup_logging()
logger = logging.getLogger(__name__)


# === Утилиты БД ===
@contextmanager
def get_db_cursor(db_path: str):
    """
    Контекстный менеджер для безопасной работы с БД.
    Автоматически коммитит/откатывает транзакции и закрывает соединение.
    """
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


# === Кэширующие декораторы ===
def timed_cache(duration: int):
    """
    Декоратор для кэширования результата функции на заданное время (в секундах).
    """

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
                # Очистка устаревших записей
                expired = [k for k, (_, t) in cache.items() if now - t >= duration]
                for k in expired:
                    del cache[k]
                cache[key] = (result, now)

            return result

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator


# === Создание таблиц БД ===
def create_contacts_table(cursor: sqlite3.Cursor) -> None:
    """Создаёт таблицу контактов (вызывать внутри транзакции)."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_address TEXT NOT NULL,
            contact_address TEXT NOT NULL,
            contact_name TEXT NOT NULL,
            created_at REAL,
            UNIQUE(user_address, contact_address)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_address)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_pair ON contacts(user_address, contact_address)')


def create_group_table(cursor: sqlite3.Cursor) -> None:
    """Создаёт таблицу групп (вызывать внутри транзакции)."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            creator TEXT NOT NULL,
            members TEXT NOT NULL,
            created_at REAL
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_groups_creator ON groups(creator)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_groups_members ON groups(members)')


# === Класс Блокчейн ===
class Blockchain:
    """Класс для работы с локальным блокчейном на SQLite."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self._init_lock = threading.Lock()
        self.initialize_blockchain()
        logger.info("Blockchain initialized")

    def initialize_blockchain(self) -> None:
        """Инициализирует БД: создаёт таблицы, индексы и генезис-блок."""
        with self._init_lock:
            with get_db_cursor(self.db_path) as cursor:
                self._create_tables(cursor)
                self._create_indexes(cursor)

                # Создаём генезис-блок если цепочка пуста
                if not self._get_chain_raw(cursor):
                    self._new_block_raw(cursor, previous_hash='1', proof=100)
                    logger.info("Genesis block created")

    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Создаёт все необходимые таблицы."""
        # Таблица блоков
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                transactions TEXT,
                proof INTEGER,
                previous_hash TEXT
            )
        ''')

        # Таблица транзакций
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT,
                image TEXT,
                timestamp REAL
            )
        ''')

        # Таблицы контактов и групп
        create_contacts_table(cursor)
        create_group_table(cursor)

    def _create_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Создаёт индексы для ускорения запросов."""
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_tx_sender ON transactions(sender)',
            'CREATE INDEX IF NOT EXISTS idx_tx_recipient ON transactions(recipient)',
            'CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_tx_sender_recipient ON transactions(sender, recipient)',
        ]
        for sql in indexes:
            cursor.execute(sql)

    def _new_block_raw(self, cursor: sqlite3.Cursor, proof: int, previous_hash: Optional[str] = None) -> None:
        """Создаёт новый блок (внутренний метод, без логирования)."""
        last = self._last_block_raw(cursor)
        block_index = last.get('index', 0) + 1

        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],
            'proof': proof,
            'previous_hash': previous_hash or self._hash_block(last),
        }

        cursor.execute('''
            INSERT INTO blockchain (block_index, timestamp, transactions, proof, previous_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            block['index'], block['timestamp'],
            json.dumps(block['transactions']),
            block['proof'], block['previous_hash']
        ))

    def _hash_block(self, block: Dict[str, Any]) -> str:
        """Вычисляет SHA256-хэш блока."""
        if not block:
            return '0' * 64
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def _last_block_raw(self, cursor: sqlite3.Cursor) -> Dict[str, Any]:
        """Возвращает последний блок как dict (внутренний метод)."""
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            return {
                'index': row[0], 'timestamp': row[1],
                'transactions': json.loads(row[2]),
                'proof': row[3], 'previous_hash': row[4],
            }
        return {}

    def _get_chain_raw(self, cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        """Возвращает всю цепочку блоков (внутренний метод)."""
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        return [{
            'index': r[0], 'timestamp': r[1],
            'transactions': json.loads(r[2]),
            'proof': r[3], 'previous_hash': r[4],
        } for r in cursor.fetchall()]

    def new_transaction(self, cursor: sqlite3.Cursor, sender: str, recipient: str,
                        content: str, image: Optional[str]) -> int:
        """Создаёт новую транзакцию и возвращает её ID."""
        cursor.execute('''
            INSERT INTO transactions (sender, recipient, content, image, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (sender, recipient, content, image, time.time()))
        tx_id = cursor.lastrowid
        logger.debug(f"Transaction #{tx_id}: {sender} -> {recipient}")
        return tx_id

    def get_messages(self, cursor: sqlite3.Cursor, address: str) -> List[Dict[str, Any]]:
        """Получает все сообщения для адреса (для обратной совместимости)."""
        cursor.execute('''
            SELECT id, sender, recipient, content, image, timestamp
            FROM transactions
            WHERE sender = ? OR recipient = ? OR recipient LIKE 'group:%'
            ORDER BY timestamp ASC
        ''', (address, address))

        return [{
            'id': r[0], 'sender': r[1], 'recipient': r[2],
            'content': r[3], 'image': r[4], 'timestamp': r[5],
        } for r in cursor.fetchall()]

    def proof_of_work(self, last_proof: int) -> int:
        """Оптимизированный PoW с настраиваемой сложностью."""
        proof = 0
        difficulty = CONFIG['POW_DIFFICULTY']
        target = "0" * difficulty
        max_iter = CONFIG['POW_MAX_ITERATIONS']

        while proof < max_iter:
            guess = f'{last_proof}{proof}'.encode()
            if hashlib.sha256(guess).hexdigest()[:difficulty] == target:
                logger.debug(f"PoW solved: {proof} iterations")
                return proof
            proof += 1

        logger.warning(f"PoW failed after {max_iter} iterations")
        return proof  # Fallback

    @staticmethod
    def valid_proof(last_proof: int, proof: int) -> bool:
        """Проверка PoW (для совместимости, использует CONFIG)."""
        difficulty = CONFIG['POW_DIFFICULTY']
        guess = f'{last_proof}{proof}'.encode()
        return hashlib.sha256(guess).hexdigest()[:difficulty] == "0" * difficulty


# === Flask приложение ===
app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.config.update(
    SECRET_KEY=SECRET_KEY,
    UPLOAD_FOLDER=UPLOAD_FOLDER,
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=CONFIG['SESSION_LIFETIME'],
)

# Глобальные объекты
mnemonic_gen = Mnemonic('english')
blockchain = Blockchain(DATABASE_PATH)

# Создаём папки
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.join(STATIC_FOLDER, 'emojis'), exist_ok=True)


# === Схемы валидации (Marshmallow) ===
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


class DeleteContactSchema(Schema):
    address = fields.Str(required=True, validate=lambda x: len(x) == 64)


class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True, validate=lambda x: x > 0)


# === Кэшируемые функции работы с данными ===
@timed_cache(duration=300)  # 5 минут
@lru_cache(maxsize=CONFIG['CACHE_SIZE_CONTACTS'])
def get_contact_name_cached(user_address: str, contact_address: str) -> Optional[str]:
    """Кэшированное получение имени контакта."""
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('''
            SELECT contact_name FROM contacts 
            WHERE user_address = ? AND contact_address = ?
        ''', (user_address, contact_address))
        row = cursor.fetchone()
        return row[0] if row else None


@timed_cache(duration=300)
def get_user_groups_cached(address: str) -> List[Dict[str, Any]]:
    """Кэшированное получение групп пользователя."""
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


# === Функции работы с контактами ===
def add_contact(user_address: str, contact_address: str, contact_name: str) -> bool:
    """Добавляет или обновляет контакт."""
    if not contact_name:
        contact_name = contact_address[:10] + "..."

    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('''
                INSERT OR REPLACE INTO contacts 
                (user_address, contact_address, contact_name, created_at)
                VALUES (?, ?, ?, ?)
            ''', (user_address, contact_address, contact_name, time.time()))

        # Инвалидируем кэш
        get_contact_name_cached.cache_clear()
        logger.info(f"Contact: {contact_name} ({contact_address[:10]}...)")
        return True
    except Exception as e:
        logger.error(f"Add contact error: {e}")
        return False


def delete_contact(user_address: str, contact_address: str) -> bool:
    """Удаляет контакт."""
    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('''
                DELETE FROM contacts 
                WHERE user_address = ? AND contact_address = ?
            ''', (user_address, contact_address))
            deleted = cursor.rowcount > 0

        if deleted:
            get_contact_name_cached.cache_clear()
            logger.info(f"Contact deleted: {contact_address[:10]}...")
        return deleted
    except Exception as e:
        logger.error(f"Delete contact error: {e}")
        return False


def get_contacts(user_address: str) -> List[Dict[str, Any]]:
    """Получает список контактов пользователя."""
    with get_db_cursor(blockchain.db_path) as cursor:
        cursor.execute('''
            SELECT contact_address, contact_name, created_at 
            FROM contacts 
            WHERE user_address = ? 
            ORDER BY contact_name COLLATE NOCASE
        ''', (user_address,))

        return [{
            'address': row[0], 'name': row[1], 'created_at': row[2]
        } for row in cursor.fetchall()]


# === Утилита расшифровки сообщений ===
def decrypt_message_safe(key: bytes, encrypted_data: Optional[str],
                         fallback: str = "[Decryption Failed]") -> Optional[str]:
    """Безопасная расшифровка с обработкой всех ошибок."""
    if not encrypted_data:
        return None
    try:
        result = decrypt_message(key, encrypted_data)
        return result if result else fallback
    except Exception as e:
        logger.warning(f"Decryption failed: {e}")
        return fallback


def process_message_decryption(msg: Dict, user_address: str) -> Dict:
    """
    Универсальная функция расшифровки сообщения (личного или группового).
    Возвращает сообщение с расшифрованным content/image.
    """
    result = msg.copy()

    try:
        # === Групповое сообщение ===
        if msg['recipient'].startswith('group:'):
            group_id = msg['recipient'].split(':', 1)[1]
            groups = get_user_groups_cached(user_address)
            user_group = next((g for g in groups if g['id'] == group_id), None)

            if not user_group or user_address not in user_group['members']:
                result.update({'content': "[No access]", 'image': None})
                return result

            try:
                encrypted_data = json.loads(msg['content'])
                if user_address not in encrypted_data:  # ← здесь тоже было encrypted_ без двоеточия
                    result.update({'content': "[No data]", 'image': None})
                    return result

                user_data = encrypted_data[user_address]
                key = generate_key(msg['sender'], user_address)

                result['content'] = decrypt_message_safe(key, user_data['content'])
                result['image'] = decrypt_message_safe(key, user_data.get('image'))

            except json.JSONDecodeError:
                result.update({'content': "[Invalid JSON]", 'image': None})

        # === Личное сообщение ===
        else:
            key = generate_key(msg['sender'], msg['recipient'])
            result['content'] = decrypt_message_safe(key, msg['content'])
            result['image'] = decrypt_message_safe(key, msg['image'])

    except Exception as e:
        logger.error(f"Message processing error: {e}")
        result.update({'content': '[Error]', 'image': None})

    return result

# === Список диалогов (оптимизированный) ===
def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    """
    Получает список диалогов с кэшированием и оптимизированными запросами.
    Включает личные чаты и группы.
    """
    conversations = {}

    try:
        with get_db_cursor(blockchain.db_path) as cursor:
            # Запрос 1: Партнёры по переписке
            cursor.execute('''
                SELECT DISTINCT 
                    CASE WHEN sender = ? THEN recipient ELSE sender END as partner
                FROM transactions 
                WHERE sender = ? OR recipient = ?
            ''', (user_address, user_address, user_address))

            for row in cursor.fetchall():
                partner = row[0]
                if partner == user_address:
                    continue

                if partner.startswith('group:'):
                    # Обработка группы
                    group_id = partner.split(':', 1)[1]
                    groups = get_user_groups_cached(user_address)
                    group = next((g for g in groups if g['id'] == group_id), None)
                    if group:
                        conversations[partner] = {
                            'address': partner, 'name': group['name'], 'is_group': True
                        }
                else:
                    # Личный контакт
                    name = get_contact_name_cached(user_address, partner) or partner[:10] + "..."
                    conversations[partner] = {
                        'address': partner, 'name': name, 'is_group': False
                    }

            # Запрос 2: Контакты без переписки
            cursor.execute('''
                SELECT contact_address, contact_name 
                FROM contacts 
                WHERE user_address = ?
            ''', (user_address,))

            for contact_addr, contact_name in cursor.fetchall():
                if contact_addr == user_address or contact_addr in conversations:
                    continue
                conversations[contact_addr] = {
                    'address': contact_addr, 'name': contact_name, 'is_group': False
                }

    except Exception as e:
        logger.error(f"Get conversations error: {e}")

    return list(conversations.values())


# === Маршруты: Аутентификация ===
@app.before_request
def log_request():
    """Логирование запросов (только в debug)."""
    if app.debug:
        logger.debug(f"{request.method} {request.path}")


@app.route('/')
def index():
    """Главная: редирект в чат если авторизован."""
    if 'address' in session:
        return redirect(url_for('chat'))
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    """Создание нового кошелька."""
    try:
        phrase = mnemonic_gen.generate(256)
        address = generate_address(phrase)

        session['address'] = address
        session['mnemonic'] = phrase
        session.permanent = True

        logger.info(f"Wallet created: {address[:16]}...")
        return jsonify({'mnemonic_phrase': phrase, 'address': address}), 201

    except Exception as e:
        logger.error(f"Create wallet error: {e}")
        return jsonify({'error': 'Wallet creation failed'}), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход по мнемонической фразе."""
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

            logger.info(f"Login: {address[:16]}...")
            return jsonify({'address': address}), 200

        except ValidationError as err:
            return jsonify({'error': err.messages}), 400
        except Exception as e:
            logger.error(f"Login error: {e}")
            return jsonify({'error': 'Login failed'}), 500

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Выход: очистка сессии и кэшей."""
    clear_key_cache()
    get_contact_name_cached.cache_clear()
    get_user_groups_cached.cache_clear()
    session.clear()
    return redirect(url_for('index'))


# === Маршруты: Страницы ===
@app.route('/chat')
def chat():
    """Страница чата."""
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('chat.html', address=session['address'])


@app.route('/contacts')
def contacts():
    """Страница контактов."""
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('contacts.html', address=session['address'])


@app.route('/groups')
def groups_page():
    """Страница групп."""
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('groups.html', address=session['address'])


@app.route('/profile')
def profile():
    """Страница профиля."""
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template(
        'profile.html',
        address=session.get('address'),
        mnemonic=session.get('mnemonic'),
        cache_stats=get_cache_info() if app.debug else None
    )


# === Маршруты: Контакты ===
@app.route('/add_contact', methods=['POST'])
def add_contact_route():
    """API: Добавление контакта."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = ContactSchema().load(request.get_json())
        user_addr = session['address']

        if add_contact(user_addr, data['address'], data['name']):
            return jsonify({'message': 'Contact added'}), 201
        return jsonify({'error': 'Failed to add'}), 500

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Add contact API error: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/delete_contact', methods=['POST'])
def delete_contact_route():
    """API: Удаление контакта."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = DeleteContactSchema().load(request.get_json())
        if delete_contact(session['address'], data['address']):
            return jsonify({'message': 'Contact deleted'}), 200
        return jsonify({'error': 'Not found'}), 404

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Delete contact API error: {e}")
        return jsonify({'error': 'Server error'}), 500


@app.route('/get_contacts', methods=['GET'])
def get_contacts_route():
    """API: Список контактов."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        contacts = get_contacts(session['address'])
        return jsonify({'contacts': contacts}), 200
    except Exception as e:
        logger.error(f"Get contacts API error: {e}")
        return jsonify({'error': 'Failed'}), 500


# === Маршруты: Группы ===
@app.route('/create_group', methods=['POST'])
def create_group_route():
    """API: Создание группы."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = GroupSchema().load(request.get_json())
        creator = session['address']
        group_id = str(uuid.uuid4())
        members = list(set([creator] + data['members']))  # Уникальные + создатель

        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('''
                INSERT INTO groups (id, name, creator, members, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (group_id, data['name'], creator, json.dumps(members), time.time()))

        # Инвалидируем кэш групп для всех участников
        get_user_groups_cached.cache_clear()

        logger.info(f"Group created: {group_id[:8]}... by {creator[:16]}...")
        return jsonify({'group_id': group_id, 'message': 'Group created'}), 201

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Create group error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/get_groups', methods=['GET'])
def get_groups_route():
    """API: Список групп пользователя."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        groups = get_user_groups_cached(session['address'])
        return jsonify({'groups': groups}), 200
    except Exception as e:
        logger.error(f"Get groups error: {e}")
        return jsonify({'error': 'Failed'}), 500


# === Маршруты: Сообщения ===
@app.route('/send_message', methods=['POST'])
def send_message():
    """API: Отправка сообщения (личного или группового)."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = MessageSchema().load(request.get_json())
        sender = session['address']
        recipient = data['recipient']
        content = data['content']
        image = data.get('image')
        msg_type = data.get('message_type', 'direct')
        group_id = data.get('group_id')

        # === Групповое сообщение ===
        if msg_type == 'group' and group_id:
            groups = get_user_groups_cached(sender)
            group = next((g for g in groups if g['id'] == group_id), None)

            if not group:
                return jsonify({'error': 'Group not found'}), 404

            # Шифруем для каждого участника
            encrypted_map = {}
            for member in group['members']:
                if member == sender:
                    continue
                try:
                    key = generate_key(sender, member)  # Использует кэш!
                    encrypted_map[member] = {
                        'content': encrypt_message(key, content),
                        'image': encrypt_message(key, image) if image else None
                    }
                except Exception as e:
                    logger.warning(f"Encrypt for {member[:10]}... failed: {e}")
                    continue

            if not encrypted_map:
                return jsonify({'error': 'Encryption failed'}), 500

            # Одна транзакция на всё групповое сообщение
            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(
                    cursor, sender, f"group:{group_id}",
                    json.dumps(encrypted_map), None
                )
                last_proof = blockchain._last_block_raw(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain._new_block_raw(cursor, proof)

        # === Личное сообщение ===
        else:
            if sender == recipient:
                return jsonify({'error': 'Cannot message yourself'}), 400

            key = generate_key(sender, recipient)
            enc_content = encrypt_message(key, content)
            enc_image = encrypt_message(key, image) if image else None

            with get_db_cursor(blockchain.db_path) as cursor:
                tx_id = blockchain.new_transaction(cursor, sender, recipient, enc_content, enc_image)
                last_proof = blockchain._last_block_raw(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain._new_block_raw(cursor, proof)

        logger.info(f"Message sent: {sender[:16]}... -> {recipient[:16]}...")
        return jsonify({
            'message': 'Sent', 'tx_id': tx_id,
            'recipient': recipient, 'type': msg_type, 'group_id': group_id
        }), 201

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Send message error: {e}")
        return jsonify({'error': 'Failed to send'}), 500


@app.route('/get_conversation', methods=['GET'])
def get_conversation():
    """API: Получение сообщений конкретного диалога."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        user_addr = session['address']
        chat_with = request.args.get('with')

        if not chat_with:
            return jsonify({'error': 'Missing "with" param'}), 400

        with get_db_cursor(blockchain.db_path) as cursor:
            if chat_with.startswith('group:'):
                cursor.execute('''
                    SELECT id, sender, recipient, content, image, timestamp
                    FROM transactions WHERE recipient = ?
                    ORDER BY timestamp ASC
                ''', (chat_with,))
            else:
                cursor.execute('''
                    SELECT id, sender, recipient, content, image, timestamp
                    FROM transactions 
                    WHERE (sender = ? AND recipient = ?) OR (sender = ? AND recipient = ?)
                    ORDER BY timestamp ASC
                ''', (user_addr, chat_with, chat_with, user_addr))

            messages = [{
                'id': r[0], 'sender': r[1], 'recipient': r[2],
                'content': r[3], 'image': r[4], 'timestamp': r[5],
            } for r in cursor.fetchall()]

        # Расшифровываем через универсальную функцию
        decrypted = []
        for msg in messages:
            dec = process_message_decryption(msg, user_addr)
            dec['sender_name'] = get_contact_name_cached(user_addr, msg['sender']) or msg['sender']
            dec['recipient_name'] = get_contact_name_cached(user_addr, msg['recipient']) or msg['recipient']
            dec['is_mine'] = msg['sender'] == user_addr
            decrypted.append(dec)

        return jsonify({'messages': decrypted}), 200

    except Exception as e:
        logger.error(f"Get conversation error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/get_conversations', methods=['GET'])
def get_conversations_route():
    """API: Список диалогов для боковой панели."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        convos = get_conversations_list(session['address'])
        return jsonify({'conversations': convos}), 200
    except Exception as e:
        logger.error(f"Get conversations error: {e}")
        return jsonify({'error': 'Failed'}), 500


# === Маршруты: Файлы ===
@app.route('/upload_file', methods=['POST'])
def upload_file():
    """API: Загрузка файла (возвращает base64 для изображений)."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty filename'}), 400

        filename = secure_filename(file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(UPLOAD_FOLDER, unique_name)
        file.save(filepath)

        # Для изображений возвращаем base64 прямо
        if file.content_type and file.content_type.startswith('image/'):
            with open(filepath, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode()
            os.remove(filepath)  # Не храним дубликаты
            return jsonify({'file_url': f"{file.content_type};base64,{b64}"}), 200

        return jsonify({'file_url': f"/uploads/{unique_name}"}), 200

    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': 'Upload failed'}), 500


@app.route('/uploads/<filename>')
def serve_upload(filename):
    """Раздача загруженных файлов."""
    return send_from_directory(UPLOAD_FOLDER, filename)


# === Маршруты: Управление ===
@app.route('/add_contact_from_chat', methods=['POST'])
def add_contact_from_chat():
    """API: Быстрое добавление контакта из чата."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = request.get_json()
        contact_addr = data.get('contact_address', '').strip()
        contact_name = data.get('contact_name', '').strip()

        if len(contact_addr) != 64 or contact_addr == session['address']:
            return jsonify({'error': 'Invalid address'}), 400

        if add_contact(session['address'], contact_addr, contact_name):
            return jsonify({'message': 'Added'}), 201
        return jsonify({'error': 'Failed'}), 500

    except Exception as e:
        logger.error(f"Quick add contact error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/delete_message', methods=['POST'])
def delete_message():
    """API: Удаление своего сообщения."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        data = DeleteMessageSchema().load(request.get_json())
        user_addr = session['address']

        with get_db_cursor(blockchain.db_path) as cursor:
            cursor.execute('SELECT sender FROM transactions WHERE id = ?', (data['message_id'],))
            row = cursor.fetchone()

            if not row or row[0] != user_addr:
                return jsonify({'error': 'Not found or permission denied'}), 403 / 404

            cursor.execute('DELETE FROM transactions WHERE id = ?', (data['message_id'],))

        logger.info(f"Message #{data['message_id']} deleted by {user_addr[:16]}...")
        return jsonify({'message': 'Deleted'}), 200

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logger.error(f"Delete message error: {e}")
        return jsonify({'error': 'Failed'}), 500


@app.route('/clear_conversation', methods=['POST'])
def clear_conversation():
    """API: Очистка истории (локальная, не удаляет из блокчейна)."""
    if 'address' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        chat_with = request.get_json().get('chat_with')
        if not chat_with:
            return jsonify({'error': 'Missing param'}), 400

        # В реальной децентрализованной системе это очищает только локальный кэш
        logger.info(f"Conversation cleared (local): {session['address'][:16]}... <-> {chat_with[:16]}...")
        return jsonify({'message': 'Cleared (local)'}), 200

    except Exception as e:
        logger.error(f"Clear conversation error: {e}")
        return jsonify({'error': 'Failed'}), 500


# === Обработчики ошибок ===
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def server_error(e):
    logger.error(f"Internal error: {e}")
    return jsonify({'error': 'Server error'}), 500


@app.errorhandler(413)
def file_too_large(e):
    return jsonify({'error': 'File too large (max 16MB)'}), 413


# === Запуск ===
if __name__ == '__main__':
    # Для разработки
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)