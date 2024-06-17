import sqlite3
import time
<<<<<<< HEAD
import base64
import hashlib
import json
from flask import Flask, jsonify, request, render_template
from mnemonic import Mnemonic
import logging
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
import os
import base64


class Blockchain:
    def __init__(self, db_path='blockchain.db'):
        self.db_path = db_path
        self.initialize_blockchain()

    def initialize_blockchain(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            self.create_table(cursor)
            self.create_transaction_table(cursor)
            if len(self.get_chain(cursor)) == 0:
                self.new_block(cursor, previous_hash='1', proof=100)

    def create_table(self, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                transactions TEXT,
                proof INTEGER,
                previous_hash TEXT
            )
        ''')

    def create_transaction_table(self, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                sender TEXT,
                recipient TEXT,
                content TEXT,
                image TEXT,
                timestamp REAL
            )
        ''')

    def new_block(self, cursor, proof, previous_hash=None):
        block_index = self.last_block(cursor)['index'] + 1 if self.last_block(cursor) else 1
        previous_block = self.last_block(cursor)
        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],  # Placeholder for transactions
            'proof': proof,
            'previous_hash': previous_hash or self.hash_block(previous_block),
        }
        cursor.execute('''
            INSERT INTO blockchain (block_index, timestamp, transactions, proof, previous_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            block['index'], block['timestamp'], json.dumps(block['transactions']), block['proof'],
            block['previous_hash']))

    def hash_block(self, block):
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def last_block(self, cursor):
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = cursor.fetchone()
        return {
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } if row else {}

    def get_chain(self, cursor):
        cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        rows = cursor.fetchall()
        return [{
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } for row in rows]

    def new_transaction(self, sender, recipient, content, image):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
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
            ''', (sender, recipient, content, image, transaction['timestamp']))
            conn.commit()
            return self.last_block(cursor)['index'] + 1

    def get_messages(self, address):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM transactions
                WHERE sender = ? OR recipient = ?
            ''', (address, address))
            rows = cursor.fetchall()
            messages = []
            for row in rows:
                message = {
                    'sender': row[0],
                    'recipient': row[1],
                    'content': row[2],
                    'image': row[3],
                    'timestamp': row[4],
                }
                messages.append(message)
            return messages

    def proof_of_work(self, last_proof):
        proof = 0
        while self.valid_proof(last_proof, proof) is False:
            proof += 1
        return proof

    @staticmethod
    def valid_proof(last_proof, proof):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"



def encrypt_message(key, message):
    backend = default_backend()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
    encryptor = cipher.encryptor()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_message = padder.update(message.encode()) + padder.finalize()
    encrypted_message = encryptor.update(padded_message) + encryptor.finalize()
    return base64.b64encode(iv + encrypted_message).decode()


def decrypt_message(key, encrypted_message):
    if encrypted_message is None:
        return None

    backend = default_backend()
    encrypted_message = base64.b64decode(encrypted_message)
    iv = encrypted_message[:16]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
    decryptor = cipher.decryptor()
    decrypted_padded_message = decryptor.update(encrypted_message[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    decrypted_message = unpadder.update(decrypted_padded_message) + unpadder.finalize()
    return decrypted_message.decode()


def generate_key(sender, recipient):
    shared_secret = ''.join(sorted([sender, recipient]))
    return hashlib.sha256(shared_secret.encode()).digest()
=======
import json
import hashlib
import base64
from cryptography.fernet import Fernet
from flask import Flask, jsonify, request, render_template, g
from flask_babel import Babel, gettext
from mnemonic import Mnemonic
from translations import translations

app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')


class Blockchain:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.connect()

    def connect(self):
        if not self.conn:
            self.conn = sqlite3.connect('blockchain.db')
            self.cursor = self.conn.cursor()
            self.create_table()
            self.create_transaction_table()
            if len(self.get_chain()) == 0:
                self.new_block(previous_hash='1', proof=100)

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def create_table(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS blockchain (
                block_index INTEGER PRIMARY KEY,
                timestamp REAL,
                transactions TEXT,
                proof INTEGER,
                previous_hash TEXT
            )
        ''')
        self.conn.commit()

    def create_transaction_table(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                sender TEXT,
                recipient TEXT,
                content TEXT,
                image TEXT,
                timestamp REAL
            )
        ''')
        self.conn.commit()

    def new_block(self, proof, previous_hash=None):
        block_index = self.last_block['index'] + 1 if self.last_block else 1

        block = {
            'index': block_index,
            'timestamp': time.time(),
            'transactions': [],  # Placeholder for transactions
            'proof': proof,
            'previous_hash': previous_hash or self.hash(self.last_block),
        }
        self.cursor.execute('''
            INSERT INTO blockchain (block_index, timestamp, transactions, proof, previous_hash)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            block['index'], block['timestamp'], json.dumps(block['transactions']), block['proof'],
            block['previous_hash']))
        self.conn.commit()

    @property
    def last_block(self):
        self.cursor.execute('SELECT * FROM blockchain ORDER BY block_index DESC LIMIT 1')
        row = self.cursor.fetchone()
        return {
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } if row else {}

    def get_chain(self):
        self.cursor.execute('SELECT * FROM blockchain ORDER BY block_index ASC')
        rows = self.cursor.fetchall()
        return [{
            'index': row[0],
            'timestamp': row[1],
            'transactions': json.loads(row[2]),
            'proof': row[3],
            'previous_hash': row[4],
        } for row in rows]

    def new_transaction(self, sender, recipient, content, image):
        transaction = {
            'sender': sender,
            'recipient': recipient,
            'content': content,
            'image': image,
            'timestamp': time.time(),
        }
        self.cursor.execute('''
            INSERT INTO transactions (sender, recipient, content, image, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (sender, recipient, content, image, transaction['timestamp']))
        self.conn.commit()

        return self.last_block['index'] + 1

    def get_messages(self, address):
        self.cursor.execute('''
            SELECT * FROM transactions
            WHERE sender = ? OR recipient = ?
        ''', (address, address))
        rows = self.cursor.fetchall()
        messages = []
        for row in rows:
            message = {
                'sender': row[0],
                'recipient': row[1],
                'content': row[2],
                'image': row[3],
                'timestamp': row[4],
            }
            messages.append(message)
        return messages

    def generate_address(self, phrase):
        return hashlib.sha256(phrase.encode()).hexdigest()

    def proof_of_work(self, last_proof):
        proof = 0
        while self.valid_proof(last_proof, proof) is False:
            proof += 1
        return proof

    @staticmethod
    def valid_proof(last_proof, proof):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"


class CryptoManager:
    def __init__(self, key):
        self.key = self.decode_and_pad_key(key)
        self.cipher = Fernet(self.key)

    def decode_and_pad_key(self, key):
        # Function to add padding to base64 encoded key before decoding
        if len(key) % 4 != 0:
            key += '=' * (4 - len(key) % 4)
        return base64.urlsafe_b64decode(key)

    def encrypt_message(self, message):
        if message is None:
            return None
        try:
            encrypted_message = self.cipher.encrypt(message.encode())
            return base64.urlsafe_b64encode(encrypted_message).decode()
        except Exception as e:
            raise ValueError(f'Encryption failed: {str(e)}')

    def decrypt_message(self, encrypted_message):
        if encrypted_message is None:
            return None
        try:
            decoded_encrypted_message = base64.urlsafe_b64decode(encrypted_message.encode())
            decrypted_message = self.cipher.decrypt(decoded_encrypted_message)
            return decrypted_message.decode()
        except Exception as e:
            raise ValueError(f'Decryption failed: {str(e)}')
>>>>>>> main


@app.before_request
def before_request():
    g.db = sqlite3.connect('blockchain.db')


@app.teardown_request
def teardown_request(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


app = Flask(__name__)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    phrase = mnemonic.generate(256)
<<<<<<< HEAD
    logging.debug(f'Generated phrase: {phrase}')
    address = generate_address(phrase)
    logging.debug(f'Generated address: {address}')
    response = {
        'mnemonic_phrase': phrase,
        'address': address,
=======
    address = blockchain.generate_address(phrase)
    response = {
        'mnemonic_phrase': phrase,
        'address': address,
        'message': gettext(translations.get(request.args.get('lang', 'en'), {}).get('wallet_created'))
>>>>>>> main
    }
    return jsonify(response), 200


@app.route('/login_wallet', methods=['POST'])
def login_wallet():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    if not phrase:
<<<<<<< HEAD
        return jsonify({'error': 'Mnemonic phrase is required'}), 400

    if not mnemonic.check(phrase):
        return jsonify({'error': 'Invalid mnemonic phrase'}), 400
=======
        return jsonify(
            {'error': gettext(translations.get(request.args.get('lang', 'en'), {}).get('mnemonic_required'))}), 400

    if not mnemonic.check(phrase):
        return jsonify(
            {'error': gettext(translations.get(request.args.get('lang', 'en'), {}).get('mnemonic_invalid'))}), 400
>>>>>>> main

    address = blockchain.generate_address(phrase)
    response = {
        'address': address,
<<<<<<< HEAD
=======
        'message': gettext(translations.get(request.args.get('lang', 'en'), {}).get('wallet_created'))
>>>>>>> main
    }
    return jsonify(response), 200


@app.route('/send_message', methods=['POST'])
def send_message():
<<<<<<< HEAD
    try:
        data = request.get_json()
        phrase = data.get('mnemonic_phrase')
        recipient = data.get('recipient')
        content = data.get('content')
        image = data.get('image')

        if not phrase or not recipient or not content:
            return jsonify({'error': 'Missing fields'}), 400

        sender = generate_address(phrase)
        key = generate_key(sender, recipient)

        encrypted_content = encrypt_message(key, content)
        encrypted_image = encrypt_message(key, image) if image else ""

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, encrypted_content, encrypted_image)
            proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
            blockchain.new_block(cursor, proof=proof)

        return jsonify({'message': 'Message sent'}), 201

    except Exception as e:
        app.logger.error(f"Failed to send message: {str(e)}")
        return jsonify({'error': f'Failed to send message: {str(e)}'}), 500
=======
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    recipient = data.get('recipient')
    content = data.get('content')
    image = data.get('image')

    if not phrase or not recipient or not content:
        return jsonify(
            {'error': gettext(translations.get(request.args.get('lang', 'en'), {}).get('missing_fields'))}), 400

    sender = blockchain.generate_address(phrase)
    key = generate_key(sender, recipient)
    crypto_manager = CryptoManager(base64.urlsafe_b64encode(key).decode())  # Encode key and decode with CryptoManager

    try:
        encrypted_content = crypto_manager.encrypt_message(content)
        encrypted_image = crypto_manager.encrypt_message(image) if image else None
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 500

    with blockchain as bc:
        bc.new_transaction(sender, recipient, encrypted_content, encrypted_image)
        proof = bc.proof_of_work(bc.last_block['proof'])
        bc.new_block(proof=proof)

    return jsonify({'message': gettext(translations.get(request.args.get('lang', 'en'), {}).get('message_sent'))}), 201
>>>>>>> main


@app.route('/get_messages', methods=['POST'])
def get_messages():
    try:
        data = request.get_json()
        phrase = data.get('mnemonic_phrase')

<<<<<<< HEAD
        if not phrase:
            return jsonify({'error': 'Mnemonic phrase is required'}), 400

        address = generate_address(phrase)

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            messages = blockchain.get_messages(address)

        decrypted_messages = []
        for message in messages:
            key = generate_key(message['sender'], message['recipient'])
            decrypted_content = decrypt_message(key, message['content'])
            try:
                decrypted_image = decrypt_message(key, message['image']) if message['image'] else None
            except Exception as e:
                app.logger.error(f"Failed to decrypt image: {str(e)}")
                decrypted_image = None

            if decrypted_content is None:
                decrypted_content = "Failed to decrypt content"

            decrypted_message = message.copy()
            decrypted_message['content'] = decrypted_content
            decrypted_message['image'] = decrypted_image
            decrypted_messages.append(decrypted_message)

        return jsonify({'messages': decrypted_messages}), 200

    except Exception as e:
        app.logger.error(f"Failed to retrieve messages: {str(e)}")
        return jsonify({'error': f'Failed to retrieve messages: {str(e)}'}), 500



@app.route('/chain', methods=['GET'])
def full_chain():
    with blockchain:
        chain = blockchain.get_chain(blockchain.cursor)
    response = {
        'chain': chain,
        'length': len(chain),
    }
    return jsonify(response), 200
=======
    if not phrase:
        return jsonify(
            {'error': gettext(translations.get(request.args.get('lang', 'en'), {}).get('mnemonic_required'))}), 400

    address = blockchain.generate_address(phrase)
    key = generate_key(address, address)
    crypto_manager = CryptoManager(base64.urlsafe_b64encode(key).decode())  # Encode key and decode with CryptoManager

    with blockchain as bc:
        messages = bc.get_messages(address)

    try:
        for message in messages:
            message['content'] = crypto_manager.decrypt_message(message['content'])
            message['image'] = crypto_manager.decrypt_message(message['image']) if message['image'] else None
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 500

    return jsonify({'messages': messages}), 200
>>>>>>> main


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
