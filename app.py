# app.py - Полный код децентрализованного мессенджера с блокчейном и шифрованием

import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import os
import base64
import logging
import sqlite3
import time
import json
import uuid
from typing import List, Dict, Any, Optional
from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory
from mnemonic import Mnemonic
from marshmallow import Schema, fields, ValidationError
from werkzeug.utils import secure_filename

# === Конфигурация ===
DATABASE_PATH = 'blockchain.db'
UPLOAD_FOLDER = 'uploads'
STATIC_FOLDER = 'static'
TEMPLATE_FOLDER = 'templates'
SECRET_KEY = 'your-secret-key-change-in-production'
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size

# === Настройка логирования ===
logging.basicConfig(
    filename='messenger.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)


# === Криптографические функции ===

def encrypt_message(key: bytes, message: str) -> str:
    """Шифрует сообщение с использованием AES-256-CBC."""
    if not message:
        return ""
    try:
        backend = default_backend()
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        encryptor = cipher.encryptor()

        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(message.encode('utf-8')) + padder.finalize()

        encrypted = encryptor.update(padded_data) + encryptor.finalize()
        return base64.b64encode(iv + encrypted).decode()
    except Exception as e:
        logging.error(f"Encryption error: {e}")
        raise


def decrypt_message(key: bytes, encrypted_message: str) -> str:
    """Расшифровывает сообщение с использованием AES-256-CBC."""
    if not encrypted_message:
        return ""
    try:
        backend = default_backend()
        raw_data = base64.b64decode(encrypted_message.encode())
        iv = raw_data[:16]
        ciphertext = raw_data[16:]

        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        decryptor = cipher.decryptor()

        padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        plaintext = unpadder.update(padded_plaintext) + unpadder.finalize()

        return plaintext.decode('utf-8')
    except Exception as e:
        logging.warning(f"Decryption error: {e}")
        return "[Decryption Failed]"


def generate_key(sender: str, recipient: str) -> bytes:
    """Генерирует ключ для шифрования на основе адресов отправителя и получателя."""
    shared_secret = ''.join(sorted([sender, recipient]))
    return hashlib.sha256(shared_secret.encode()).digest()


def generate_address(phrase: str) -> str:
    """Генерирует адрес кошелька из мнемонической фразы."""
    return hashlib.sha256(phrase.encode()).hexdigest()


# === Блокчейн ===

class Blockchain:
    """Класс для работы с блокчейном."""

    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.initialize_blockchain()
        logging.info("Blockchain initialized")

    def initialize_blockchain(self) -> None:
        """Инициализирует блокчейн, создает таблицы и генезис-блок."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            self.create_table(cursor)
            self.create_transaction_table(cursor)
            self.create_indexes(cursor)  # Добавляем индексы для производительности
            if not self.get_chain(cursor):
                self.new_block(cursor, previous_hash='1', proof=100)
                logging.info("Genesis block created")

    def create_table(self, cursor: sqlite3.Cursor) -> None:
        """Создает таблицу блокчейна."""
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                transactions TEXT,
                proof INTEGER,
                previous_hash TEXT
            )
        ''')

    def create_transaction_table(self, cursor: sqlite3.Cursor) -> None:
        """Создает таблицу транзакций."""
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

    def create_indexes(self, cursor: sqlite3.Cursor) -> None:
        """Создает индексы для ускорения запросов."""
        # Индекс для поиска сообщений по адресу (для get_messages)
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS idx_transactions_sender_recipient ON transactions(sender, recipient)')
        # Индекс для поиска сообщений по группе
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_recipient_group ON transactions(recipient)')
        # Индекс для сортировки по времени
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp)')

    def new_block(self, cursor: sqlite3.Cursor, proof: int, previous_hash: Optional[str] = None) -> None:
        """Создает новый блок."""
        block_index = self.last_block(cursor).get('index', 0) + 1
        previous_block = self.last_block(cursor)
        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],  # Transactions will be stored in DB
            'proof': proof,
            'previous_hash': previous_hash or self.hash_block(previous_block),
        }

        cursor.execute('''
            INSERT INTO blockchain (block_index, timestamp, transactions, proof, previous_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            block['index'],
            block['timestamp'],
            json.dumps(block['transactions']),
            block['proof'],
            block['previous_hash']
        ))
        logging.info(f"New block added: {block['index']}")

    def hash_block(self, block: Dict[str, Any]) -> str:
        """Хэширует блок."""
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def last_block(self, cursor: sqlite3.Cursor) -> Dict[str, Any]:
        """Возвращает последний блок."""
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = cursor.fetchone()
        if row:
            return {
                'index': row[0],
                'timestamp': row[1],
                'transactions': json.loads(row[2]),
                'proof': row[3],
                'previous_hash': row[4],
            }
        return {}

    def get_chain(self, cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
        """Возвращает всю цепочку блоков."""
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        rows = cursor.fetchall()
        return [{
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } for row in rows]

    def new_transaction(self, cursor: sqlite3.Cursor, sender: str, recipient: str, content: str,
                        image: Optional[str]) -> int:
        """Создает новую транзакцию."""
        transaction = {
            'sender': sender,
            'recipient': recipient,
            'content': content,
            'image': image,
            'timestamp': time.time(),
        }
        cursor.execute('''
            INSERT INTO transactions (sender, recipient, content, image, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            transaction['sender'],
            transaction['recipient'],
            transaction['content'],
            transaction['image'],
            transaction['timestamp']
        ))
        tx_id = cursor.lastrowid
        logging.info(f"Transaction added from {sender} to {recipient}, ID: {tx_id}")
        return tx_id  # Возвращаем ID транзакции

    def get_messages(self, cursor: sqlite3.Cursor, address: str) -> List[Dict[str, Any]]:
        """Получает сообщения для конкретного адреса."""
        cursor.execute('''
            SELECT id, sender, recipient, content, image, timestamp
            FROM transactions
            WHERE sender = ? OR recipient = ? OR recipient LIKE 'group:%'
            ORDER BY timestamp ASC
        ''', (address, address))
        rows = cursor.fetchall()
        return [{
            'id': row[0],
            'sender': row[1],
            'recipient': row[2],
            'content': row[3],
            'image': row[4],
            'timestamp': row[5],
        } for row in rows]

    def proof_of_work(self, last_proof: int) -> int:
        """Алгоритм доказательства работы."""
        proof = 0
        while not self.valid_proof(last_proof, proof):
            proof += 1
        logging.debug(f"Proof of work found: {proof}")
        return proof

    @staticmethod
    def valid_proof(last_proof: int, proof: int) -> bool:
        """Проверяет правильность доказательства работы."""
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"


# === Flask Приложение ===

app = Flask(__name__, static_folder=STATIC_FOLDER, template_folder=TEMPLATE_FOLDER)
app.secret_key = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

mnemonic_gen = Mnemonic('english')
blockchain = Blockchain(DATABASE_PATH)

# Создаем папки если их нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(STATIC_FOLDER + '/emojis', exist_ok=True)


# === Схемы валидации ===

class WalletSchema(Schema):
    mnemonic_phrase = fields.Str(required=True)


class MessageSchema(Schema):
    recipient = fields.Str(required=True)
    content = fields.Str(required=True)
    image = fields.Str(allow_none=True)
    message_type = fields.Str(load_default='direct')
    group_id = fields.Str(allow_none=True)


class GroupSchema(Schema):
    name = fields.Str(required=True)
    members = fields.List(fields.Str(), required=True)


class ContactSchema(Schema):
    address = fields.Str(required=True)
    name = fields.Str(required=True)


class DeleteContactSchema(Schema):
    address = fields.Str(required=True)


class DeleteMessageSchema(Schema):
    message_id = fields.Int(required=True)


# === Работа с контактами ===

def create_contacts_table() -> None:
    """Создает таблицу контактов."""
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
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
        # Индекс для быстрого поиска контактов пользователя
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_contacts_user_address ON contacts(user_address)')


def add_contact(user_address: str, contact_address: str, contact_name: str) -> bool:
    """Добавляет контакт. Возвращает True, если успешно."""
    try:
        # Если имя не задано, используем начало адреса как имя по умолчанию
        if not contact_name:
            contact_name = contact_address[:10] + "..."
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO contacts (user_address, contact_address, contact_name, created_at)
                VALUES (?, ?, ?, ?)
            ''', (user_address, contact_address, contact_name, time.time()))
            conn.commit()
            logging.info(f"Contact added/updated: {contact_name} ({contact_address}) for user {user_address}")
            return True
    except Exception as e:
        logging.error(f"Add contact error: {e}")
        return False


def delete_contact(user_address: str, contact_address: str) -> bool:
    """Удаляет контакт. Возвращает True, если успешно."""
    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                DELETE FROM contacts WHERE user_address = ? AND contact_address = ?
            ''', (user_address, contact_address))
            conn.commit()
            deleted_rows = cursor.rowcount
            if deleted_rows > 0:
                logging.info(f"Contact deleted: {contact_address} for user {user_address}")
                return True
            else:
                logging.info(f"No contact found to delete: {contact_address} for user {user_address}")
                return False
    except Exception as e:
        logging.error(f"Delete contact error: {e}")
        return False


def get_contacts(user_address: str) -> List[Dict[str, Any]]:
    """Получает список контактов."""
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT contact_address, contact_name, created_at 
            FROM contacts 
            WHERE user_address = ?
            ORDER BY contact_name
        ''', (user_address,))
        rows = cursor.fetchall()
        return [{
            'address': row[0],
            'name': row[1],
            'created_at': row[2]
        } for row in rows]


def get_contact_name(user_address: str, contact_address: str) -> Optional[str]:
    """Получает имя контакта."""
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT contact_name 
            FROM contacts 
            WHERE user_address = ? AND contact_address = ?
        ''', (user_address, contact_address))
        row = cursor.fetchone()
        return row[0] if row else None


def get_conversations_list(user_address: str) -> List[Dict[str, Any]]:
    """
    Получает список уникальных адресов, с которыми есть переписка (входящие/исходящие)
    ИЛИ которые находятся в контактах пользователя.
    Включает прямых контактов и группы.
    """
    conversations = {}  # Используем словарь для автоматического исключения дубликатов
    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()

            # 1. Получаем уникальных адресов из существующих транзакций (диалогов)
            cursor.execute('''
                SELECT DISTINCT sender FROM transactions WHERE recipient = ?
                UNION
                SELECT DISTINCT recipient FROM transactions WHERE sender = ? AND recipient NOT LIKE 'group:%'
                UNION
                SELECT DISTINCT recipient FROM transactions WHERE recipient LIKE 'group:%'
            ''', (user_address, user_address))
            transaction_rows = cursor.fetchall()

            for row in transaction_rows:
                address = row[0]
                if address == user_address:
                    continue  # Не добавляем себя

                # Проверяем, является ли это группа
                if address.startswith('group:'):
                    group_id = address.split(':', 1)[1]
                    groups = get_user_groups(user_address)
                    group_info = next((g for g in groups if g['id'] == group_id), None)
                    if group_info:
                        # Это группа, в которой мы состоим
                        conversations[address] = {
                            'address': address,
                            'name': group_info['name'],
                            'is_group': True
                        }
                else:
                    # Это личный контакт с перепиской
                    name = get_contact_name(user_address, address) or address[:10] + "..."
                    conversations[address] = {
                        'address': address,
                        'name': name,
                        'is_group': False
                    }

            # 2. Получаем контакты пользователя, которых еще нет в списке
            cursor.execute('''
                SELECT contact_address, contact_name FROM contacts WHERE user_address = ?
            ''', (user_address,))
            contact_rows = cursor.fetchall()

            for row in contact_rows:
                contact_address, contact_name = row
                if contact_address == user_address:
                    continue  # Не добавляем себя

                # Если контакт еще не в списке (нет переписки), добавляем его
                if contact_address not in conversations:
                    conversations[contact_address] = {
                        'address': contact_address,
                        'name': contact_name,  # Используем имя из контактов
                        'is_group': False
                    }

    except Exception as e:
        logging.error(f"Error getting conversations list: {e}")

    # Возвращаем список значений словаря
    return list(conversations.values())


# === Работа с группами ===

def create_group_table() -> None:
    """Создает таблицу групп."""
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                creator TEXT NOT NULL,
                members TEXT NOT NULL,
                created_at REAL
            )
        ''')


def create_group(group_id: str, name: str, creator: str, members: List[str]) -> bool:
    """Создает новую группу. Возвращает True, если успешно."""
    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO groups (id, name, creator, members, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (group_id, name, creator, json.dumps(members), time.time()))
            conn.commit()
            logging.info(f"Group created: {group_id} by {creator}")
            return True
    except Exception as e:
        logging.error(f"Group creation error: {e}")
        return False


def get_user_groups(address: str) -> List[Dict[str, Any]]:
    """Получает список групп пользователя."""
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM groups')
        rows = cursor.fetchall()
        groups = []
        for row in rows:
            members = json.loads(row[3])
            if address in members:
                groups.append({
                    'id': row[0],
                    'name': row[1],
                    'creator': row[2],
                    'members': members,
                    'created_at': row[4]
                })
        return groups


# === Инициализация таблиц ===

create_contacts_table()
create_group_table()


# === Маршруты ===

@app.route('/')
def index():
    """Главная страница."""
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
        logging.info(f"New wallet created: {address}")
        return jsonify({'mnemonic_phrase': phrase, 'address': address}), 201
    except Exception as e:
        logging.error(f"Wallet creation error: {e}")
        return jsonify({'error': 'Failed to create wallet'}), 500


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Вход в систему."""
    if request.method == 'POST':
        try:
            data = WalletSchema().load(request.get_json())
            phrase = data['mnemonic_phrase']

            if not mnemonic_gen.check(phrase):
                return jsonify({'error': 'Invalid mnemonic phrase'}), 400

            address = generate_address(phrase)
            session['address'] = address
            session['mnemonic'] = phrase
            logging.info(f"User logged in: {address}")
            return jsonify({'address': address}), 200
        except ValidationError as err:
            return jsonify({'error': err.messages}), 400
        except Exception as e:
            logging.error(f"Login error: {e}")
            return jsonify({'error': 'Login failed'}), 500

    return render_template('login.html')


@app.route('/logout')
def logout():
    """Выход из системы."""
    session.clear()
    return redirect(url_for('index'))


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
def groups():
    """Страница групп."""
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('groups.html', address=session['address'])


@app.route('/add_contact', methods=['POST'])
def add_contact_route():
    """Добавление контакта."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = ContactSchema().load(request.get_json())
        user_address = session['address']
        contact_address = data['address']
        contact_name = data['name']

        if len(contact_address) != 64:  # SHA256 hash length
            return jsonify({'error': 'Invalid address format'}), 400

        if add_contact(user_address, contact_address, contact_name):
            return jsonify({'message': 'Contact added successfully'}), 201
        else:
            return jsonify({'error': 'Failed to add contact'}), 500
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Add contact route error: {e}")
        return jsonify({'error': 'Failed to add contact'}), 500


@app.route('/delete_contact', methods=['POST'])
def delete_contact_route():
    """Удаление контакта."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = DeleteContactSchema().load(request.get_json())
        user_address = session['address']
        contact_address = data['address']

        if len(contact_address) != 64:
            return jsonify({'error': 'Invalid address format'}), 400

        if delete_contact(user_address, contact_address):
            return jsonify({'message': 'Contact deleted successfully'}), 200
        else:
            return jsonify({'error': 'Contact not found or failed to delete'}), 404
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Delete contact route error: {e}")
        return jsonify({'error': 'Failed to delete contact'}), 500


@app.route('/get_contacts', methods=['GET'])
def get_contacts_route():
    """Получение списка контактов."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        contacts = get_contacts(session['address'])
        return jsonify({'contacts': contacts}), 200
    except Exception as e:
        logging.error(f"Get contacts error: {e}")
        return jsonify({'error': 'Failed to retrieve contacts'}), 500


@app.route('/create_group', methods=['POST'])
def create_group_route():
    """Создание группы."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = GroupSchema().load(request.get_json())
        group_id = str(uuid.uuid4())
        creator = session['address']
        members = list(set([creator] + data['members']))

        if create_group(group_id, data['name'], creator, members):
            return jsonify({'group_id': group_id, 'message': 'Group created successfully'}), 201
        else:
            return jsonify({'error': 'Failed to create group'}), 500
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Group creation route error: {e}")
        return jsonify({'error': 'Failed to create group'}), 500


@app.route('/get_groups', methods=['GET'])
def get_groups():
    """Получение списка групп."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        groups = get_user_groups(session['address'])
        return jsonify({'groups': groups}), 200
    except Exception as e:
        logging.error(f"Get groups error: {e}")
        return jsonify({'error': 'Failed to retrieve groups'}), 500


@app.route('/send_message', methods=['POST'])
def send_message():
    """Отправка сообщения."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = MessageSchema().load(request.get_json())
        recipient = data['recipient']
        content = data['content']
        image = data.get('image')
        message_type = data.get('message_type', 'direct')
        group_id = data.get('group_id')

        sender = session['address']

        if message_type == 'group' and group_id:
            groups = get_user_groups(sender)
            group = next((g for g in groups if g['id'] == group_id), None)
            if not group:
                return jsonify({'error': 'Group not found or access denied'}), 404

            encrypted_for_members = {}
            for member in group['members']:
                if member != sender:
                    try:
                        key = generate_key(sender, member)
                        encrypted_content = encrypt_message(key, content)
                        encrypted_image_data = encrypt_message(key, image) if image else None
                        encrypted_for_members[member] = {
                            'content': encrypted_content,
                            'image': encrypted_image_data
                        }
                    except Exception as e:
                        logging.error(f"Encryption error for member {member}: {e}")
                        continue

            encrypted_content_json = json.dumps(encrypted_for_members)
            with sqlite3.connect(blockchain.db_path) as conn:
                cursor = conn.cursor()
                tx_id = blockchain.new_transaction(cursor, sender, f"group:{group_id}", encrypted_content_json, None)
                last_proof = blockchain.last_block(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain.new_block(cursor, proof)
        else:
            if sender == recipient:
                return jsonify({'error': 'Cannot send message to yourself'}), 400

            key = generate_key(sender, recipient)
            encrypted_content = encrypt_message(key, content)
            encrypted_image = encrypt_message(key, image) if image else None

            with sqlite3.connect(blockchain.db_path) as conn:
                cursor = conn.cursor()
                tx_id = blockchain.new_transaction(cursor, sender, recipient, encrypted_content, encrypted_image)
                last_proof = blockchain.last_block(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain.new_block(cursor, proof)

        logging.info(f"Message sent from {sender} to {recipient}")
        return jsonify({
            'message': 'Message sent successfully',
            'tx_id': tx_id,
            'recipient': recipient,
            'message_type': message_type,
            'group_id': group_id
        }), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Send message error: {e}")
        return jsonify({'error': 'Failed to send message'}), 500


@app.route('/upload_file', methods=['POST'])
def upload_file():
    """Загрузка файла."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        if file:
            filename = secure_filename(file.filename)
            unique_filename = f"{uuid.uuid4()}_{filename}"
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)

            if file.content_type and file.content_type.startswith('image/'):
                with open(filepath, "rb") as img_file:
                    encoded_string = base64.b64encode(img_file.read()).decode()
                return jsonify({'file_url': f"{file.content_type};base64,{encoded_string}"}), 200
            else:
                return jsonify({'file_url': f"/{app.config['UPLOAD_FOLDER']}/{unique_filename}"}), 200

    except Exception as e:
        logging.error(f"File upload error: {e}")
        return jsonify({'error': 'Failed to upload file'}), 500


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Отправка загруженного файла."""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/get_messages', methods=['GET'])  # Оставляем для совместимости или других нужд
def get_messages():
    """Получение всех сообщений (устаревший метод, используйте /get_conversation)."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        address = session['address']

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            messages = blockchain.get_messages(cursor, address)

        decrypted_messages = []
        for msg in messages:
            try:
                if msg['recipient'].startswith('group:'):
                    group_id = msg['recipient'].split(':', 1)[1]
                    groups = get_user_groups(address)
                    user_group = next((g for g in groups if g['id'] == group_id), None)

                    if user_group and address in user_group['members']:
                        try:
                            encrypted_data = json.loads(msg['content'])
                            if address in encrypted_data:
                                user_data = encrypted_data[address]
                                key = generate_key(msg['sender'], address)
                                decrypted_content = decrypt_message(key, user_data['content']) or "[Decryption Failed]"
                                decrypted_image = decrypt_message(key, user_data['image']) if user_data.get(
                                    'image') else None
                            else:
                                decrypted_content = "[Group message - no data for you]"
                                decrypted_image = None
                        except Exception as e:
                            logging.error(f"Group message decryption error: {e}")
                            decrypted_content = "[Group message - decryption failed]"
                            decrypted_image = None
                    else:
                        decrypted_content = "[Group message - no access]"
                        decrypted_image = None
                else:
                    key = generate_key(msg['sender'], msg['recipient'])
                    decrypted_content = decrypt_message(key, msg['content']) or "[Decryption Failed]"
                    decrypted_image = decrypt_message(key, msg['image']) if msg['image'] else None

                sender_name = get_contact_name(address, msg['sender']) or msg['sender']
                recipient_name = get_contact_name(address, msg['recipient']) or msg['recipient']

                decrypted_messages.append({
                    'id': msg['id'],
                    'sender': msg['sender'],
                    'sender_name': sender_name,
                    'recipient': msg['recipient'],
                    'recipient_name': recipient_name,
                    'content': decrypted_content,
                    'image': decrypted_image,
                    'timestamp': msg['timestamp'],
                    'is_mine': msg['sender'] == address
                })
            except Exception as e:
                logging.warning(f"Decryption failed for message: {e}")
                decrypted_messages.append({
                    'id': msg['id'],
                    'sender': msg['sender'],
                    'sender_name': msg['sender'],
                    'recipient': msg['recipient'],
                    'recipient_name': msg['recipient'],
                    'content': '[Decryption Failed]',
                    'image': None,
                    'timestamp': msg['timestamp'],
                    'is_mine': msg['sender'] == address
                })

        return jsonify({'messages': decrypted_messages}), 200
    except Exception as e:
        logging.error(f"Get messages error: {e}")
        return jsonify({'error': 'Failed to retrieve messages'}), 500


@app.route('/get_conversation', methods=['GET'])
def get_conversation():
    """Получает сообщения для конкретного диалога."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        user_address = session['address']
        chat_with = request.args.get('with')

        if not chat_with:
            return jsonify({'error': 'Missing "with" parameter'}), 400

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()

            if chat_with.startswith('group:'):
                cursor.execute('''
                     SELECT id, sender, recipient, content, image, timestamp
                     FROM transactions
                     WHERE recipient = ?
                     ORDER BY timestamp ASC
                 ''', (chat_with,))
            else:
                cursor.execute('''
                     SELECT id, sender, recipient, content, image, timestamp
                     FROM transactions
                     WHERE (sender = ? AND recipient = ?) 
                        OR (sender = ? AND recipient = ?)
                     ORDER BY timestamp ASC
                 ''', (user_address, chat_with, chat_with, user_address))

            rows = cursor.fetchall()
            messages = [{
                'id': row[0],
                'sender': row[1],
                'recipient': row[2],
                'content': row[3],
                'image': row[4],
                'timestamp': row[5],
            } for row in rows]

        decrypted_messages = []
        for msg in messages:
            try:
                if msg['recipient'].startswith('group:'):
                    group_id = msg['recipient'].split(':', 1)[1]
                    groups = get_user_groups(user_address)
                    user_group = next((g for g in groups if g['id'] == group_id), None)

                    if user_group and user_address in user_group['members']:
                        try:
                            encrypted_data = json.loads(msg['content'])
                            # ---- ИСПРАВЛЕНА ОПЕЧАТКА ЗДЕСЬ ----
                            if user_address in encrypted_data:  # <--- Исправлено
                                user_data = encrypted_data[user_address]
                                key = generate_key(msg['sender'], user_address)
                                decrypted_content = decrypt_message(key, user_data['content']) or "[Decryption Failed]"
                                decrypted_image = decrypt_message(key, user_data['image']) if user_data.get(
                                    'image') else None
                            else:
                                decrypted_content = "[Group message - no data for you]"
                                decrypted_image = None
                        except Exception as e:
                            logging.error(f"Group message decryption error: {e}")
                            decrypted_content = "[Group message - decryption failed]"
                            decrypted_image = None
                    else:
                        decrypted_content = "[Group message - no access]"
                        decrypted_image = None
                else:
                    key = generate_key(msg['sender'], msg['recipient'])
                    decrypted_content = decrypt_message(key, msg['content']) or "[Decryption Failed]"
                    decrypted_image = decrypt_message(key, msg['image']) if msg['image'] else None

                sender_name = get_contact_name(user_address, msg['sender']) or msg['sender']
                recipient_name = get_contact_name(user_address, msg['recipient']) or msg['recipient']

                decrypted_messages.append({
                    'id': msg['id'],
                    'sender': msg['sender'],
                    'sender_name': sender_name,
                    'recipient': msg['recipient'],
                    'recipient_name': recipient_name,
                    'content': decrypted_content,
                    'image': decrypted_image,
                    'timestamp': msg['timestamp'],
                    'is_mine': msg['sender'] == user_address
                })
            except Exception as e:
                logging.warning(f"Decryption failed for message: {e}")
                decrypted_messages.append({
                    'id': msg['id'],
                    'sender': msg['sender'],
                    'sender_name': msg['sender'],
                    'recipient': msg['recipient'],
                    'recipient_name': msg['recipient'],
                    'content': '[Decryption Failed]',
                    'image': None,
                    'timestamp': msg['timestamp'],
                    'is_mine': msg['sender'] == user_address
                })

        return jsonify({'messages': decrypted_messages}), 200
    except Exception as e:
        logging.error(f"Get conversation error: {e}")
        return jsonify({'error': 'Failed to retrieve conversation'}), 500


@app.route('/get_conversations', methods=['GET'])
def get_conversations_route():
    """Получает список диалогов для отображения в боковой панели."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        user_address = session['address']
        conversations = get_conversations_list(user_address)
        return jsonify({'conversations': conversations}), 200
    except Exception as e:
        logging.error(f"Get conversations error: {e}")
        return jsonify({'error': 'Failed to retrieve conversations'}), 500


@app.route('/profile')
def profile():
    """Страница профиля пользователя."""
    if 'address' not in session:
        return redirect(url_for('index'))
    address = session.get('address')
    mnemonic = session.get('mnemonic')
    private_key_hex = mnemonic
    return render_template('profile.html', address=address, mnemonic=mnemonic, private_key=private_key_hex)


# --- Новые маршруты ---

@app.route('/add_contact_from_chat', methods=['POST'])
def add_contact_from_chat():
    """Добавление контакта из окна чата."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.get_json()
        user_address = session['address']
        contact_address = data.get('contact_address')
        contact_name = data.get('contact_name', '')

        if not contact_address or len(contact_address) != 64:
            return jsonify({'error': 'Invalid contact address'}), 400

        if contact_address == user_address:
            return jsonify({'error': 'Cannot add yourself as a contact'}), 400

        if add_contact(user_address, contact_address, contact_name):
            # Не обязательно возвращать обновленный список, фронтенд может сам его обновить
            # Но можно вернуть для подстраховки
            # updated_contacts = get_contacts(user_address)
            return jsonify({
                'message': 'Contact added successfully',
                # 'contacts': updated_contacts
            }), 201
        else:
            return jsonify({'error': 'Failed to add contact'}), 500
    except Exception as e:
        logging.error(f"Add contact from chat error: {e}")
        return jsonify({'error': 'Failed to add contact'}), 500


@app.route('/delete_message', methods=['POST'])
def delete_message():
    """Удаление одного сообщения."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        user_address = session['address']
        data = DeleteMessageSchema().load(request.get_json())
        message_id = data['message_id']

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT sender FROM transactions WHERE id = ?', (message_id,))
            row = cursor.fetchone()

            if not row:
                return jsonify({'error': 'Message not found'}), 404

            sender_address = row[0]
            if sender_address != user_address:
                return jsonify({'error': 'Permission denied. You can only delete your own messages.'}), 403

            cursor.execute('DELETE FROM transactions WHERE id = ?', (message_id,))
            conn.commit()

            if cursor.rowcount > 0:
                logging.info(f"Message deleted by {user_address}, ID: {message_id}")
                return jsonify({'message': 'Message deleted successfully'}), 200
            else:
                return jsonify({'error': 'Message not found or already deleted'}), 404

    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Delete message error: {e}")
        return jsonify({'error': 'Failed to delete message'}), 500


@app.route('/clear_conversation', methods=['POST'])
def clear_conversation():
    """Очистка истории диалога для текущего пользователя."""
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        user_address = session['address']
        data = request.get_json()
        chat_with_address = data.get('chat_with')

        if not chat_with_address:
            return jsonify({'error': 'Missing chat_with parameter'}), 400

        logging.info(f"User {user_address} cleared conversation with {chat_with_address}")
        return jsonify({'message': 'Conversation cleared (locally)'}), 200

    except Exception as e:
        logging.error(f"Clear conversation error: {e}")
        return jsonify({'error': 'Failed to clear conversation'}), 500


# === Запуск приложения ===

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
