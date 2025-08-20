from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_from_directory
from mnemonic import Mnemonic
import logging
import sqlite3
import os
import uuid
import json
import time
from marshmallow import Schema, fields, ValidationError
from werkzeug.utils import secure_filename
import base64

from blockchain import Blockchain
from crypto_manager import encrypt_message, decrypt_message, generate_key, generate_address

# Инициализация
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

mnemonic_gen = Mnemonic('english')
blockchain = Blockchain()

# Создаем папки если их нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/emojis', exist_ok=True)

# Настройка логирования
logging.basicConfig(
    filename='messenger.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s'
)


# Валидация
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


# Функции для работы с контактами
def create_contacts_table():
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contacts (
                user_address TEXT NOT NULL,
                contact_address TEXT NOT NULL,
                contact_name TEXT NOT NULL,
                created_at REAL,
                PRIMARY KEY (user_address, contact_address)
            )
        ''')


def add_contact(user_address, contact_address, contact_name):
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO contacts (user_address, contact_address, contact_name, created_at)
            VALUES (?, ?, ?, ?)
        ''', (user_address, contact_address, contact_name, time.time()))
        conn.commit()


def get_contacts(user_address):
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


def get_contact_name(user_address, contact_address):
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT contact_name 
            FROM contacts 
            WHERE user_address = ? AND contact_address = ?
        ''', (user_address, contact_address))
        row = cursor.fetchone()
        return row[0] if row else None


# Функции для работы с группами
def create_group_table():
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


def create_group(group_id, name, creator, members):
    with sqlite3.connect(blockchain.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO groups (id, name, creator, members, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (group_id, name, creator, json.dumps(members), time.time()))
        conn.commit()


def get_user_groups(address):
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


# Инициализация таблиц
create_contacts_table()
create_group_table()


# Маршруты
@app.route('/')
def index():
    if 'address' in session:
        return redirect(url_for('chat'))
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
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
    session.clear()
    return redirect(url_for('index'))


@app.route('/chat')
def chat():
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('chat.html', address=session['address'])


@app.route('/contacts')
def contacts():
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('contacts.html', address=session['address'])


@app.route('/groups')
def groups():
    if 'address' not in session:
        return redirect(url_for('index'))
    return render_template('groups.html', address=session['address'])


@app.route('/add_contact', methods=['POST'])
def add_contact_route():
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = ContactSchema().load(request.get_json())
        user_address = session['address']
        contact_address = data['address']
        contact_name = data['name']

        # Проверяем, что адрес валидный
        if len(contact_address) != 64:  # SHA256 hash length
            return jsonify({'error': 'Invalid address format'}), 400

        add_contact(user_address, contact_address, contact_name)
        logging.info(f"Contact added: {contact_name} ({contact_address}) for user {user_address}")
        return jsonify({'message': 'Contact added successfully'}), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Add contact error: {e}")
        return jsonify({'error': 'Failed to add contact'}), 500


@app.route('/get_contacts', methods=['GET'])
def get_contacts_route():
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
    if 'address' not in session:
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = GroupSchema().load(request.get_json())
        group_id = str(uuid.uuid4())
        creator = session['address']
        members = list(set([creator] + data['members']))  # Уникальные участники

        create_group(group_id, data['name'], creator, members)
        logging.info(f"Group created: {group_id} by {creator}")
        return jsonify({'group_id': group_id, 'message': 'Group created successfully'}), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Group creation error: {e}")
        return jsonify({'error': 'Failed to create group'}), 500


@app.route('/get_groups', methods=['GET'])
def get_groups():
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
            # Отправка в группу
            groups = get_user_groups(sender)
            group = next((g for g in groups if g['id'] == group_id), None)
            if not group:
                return jsonify({'error': 'Group not found or access denied'}), 404

            # Шифруем для каждого участника группы
            encrypted_for_members = {}
            for member in group['members']:
                if member != sender:  # Не шифруем для отправителя
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

            # Сохраняем как групповое сообщение
            encrypted_content_json = json.dumps(encrypted_for_members)
            with sqlite3.connect(blockchain.db_path) as conn:
                cursor = conn.cursor()
                blockchain.new_transaction(cursor, sender, f"group:{group_id}", encrypted_content_json, None)
                last_proof = blockchain.last_block(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain.new_block(cursor, proof)
        else:
            # Обычное сообщение
            if sender == recipient:
                return jsonify({'error': 'Cannot send message to yourself'}), 400

            key = generate_key(sender, recipient)
            encrypted_content = encrypt_message(key, content)
            encrypted_image = encrypt_message(key, image) if image else None

            with sqlite3.connect(blockchain.db_path) as conn:
                cursor = conn.cursor()
                blockchain.new_transaction(cursor, sender, recipient, encrypted_content, encrypted_image)
                last_proof = blockchain.last_block(cursor)['proof']
                proof = blockchain.proof_of_work(last_proof)
                blockchain.new_block(cursor, proof)

        logging.info(f"Message sent from {sender}")
        return jsonify({'message': 'Message sent successfully'}), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Send message error: {e}")
        return jsonify({'error': 'Failed to send message'}), 500


@app.route('/upload_file', methods=['POST'])
def upload_file():
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

            # Если это изображение, конвертируем в base64 для передачи
            if file.content_type and file.content_type.startswith('image/'):
                with open(filepath, "rb") as img_file:
                    encoded_string = base64.b64encode(img_file.read()).decode()
                return jsonify({'file_url': f"{file.content_type};base64,{encoded_string}"}), 200
            else:
                return jsonify({'file_url': f"/uploads/{unique_filename}"}), 200

    except Exception as e:
        logging.error(f"File upload error: {e}")
        return jsonify({'error': 'Failed to upload file'}), 500


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/get_messages', methods=['GET'])
def get_messages():
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
                # Проверяем, является ли это групповым сообщением
                if msg['recipient'].startswith('group:'):
                    group_id = msg['recipient'].split(':', 1)[1]
                    # Проверяем, имеет ли пользователь доступ к этой группе
                    groups = get_user_groups(address)
                    user_group = next((g for g in groups if g['id'] == group_id), None)

                    if user_group and address in user_group['members']:
                        # Расшифровываем данные для текущего пользователя
                        try:
                            encrypted_data = json.loads(msg['content'])
                            if address in encrypted_:
                                user_data = encrypted_data[address]
                                decrypted_content = decrypt_message(generate_key(msg['sender'], address),
                                                                    user_data['content']) or "[Decryption Failed]"
                                decrypted_image = decrypt_message(generate_key(msg['sender'], address),
                                                                  user_data['image']) if user_data['image'] else None
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
                    # Обычное сообщение
                    key = generate_key(msg['sender'], msg['recipient'])
                    decrypted_content = decrypt_message(key, msg['content']) or "[Decryption Failed]"
                    decrypted_image = decrypt_message(key, msg['image']) if msg['image'] else None

                # Получаем имена контактов
                sender_name = get_contact_name(address, msg['sender']) or msg['sender']
                recipient_name = get_contact_name(address, msg['recipient']) or msg['recipient']

                decrypted_messages.append({
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


@app.route('/get_mnemonic')
def get_mnemonic():
    if 'mnemonic' in session:
        return jsonify({'mnemonic': session['mnemonic']}), 200
    return jsonify({'error': 'Not available'}), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)