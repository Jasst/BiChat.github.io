import sqlite3
import time
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
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio


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


def generate_address(phrase):
    return hashlib.sha256(phrase.encode()).hexdigest()


app = Flask(__name__)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)

# Инициализация бота
TOKEN = '7432096347:AAEdv_Of7JgHcDdIfPzBnEz2c_GhtugZTmY'
bot = Bot(token=TOKEN)
application = Application.builder().token(TOKEN).build()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    phrase = mnemonic.generate(256)
    logging.debug(f'Generated phrase: {phrase}')
    address = generate_address(phrase)
    logging.debug(f'Generated address: {address}')
    response = {
        'mnemonic_phrase': phrase,
        'address': address,
    }
    return jsonify(response), 200


async def create_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phrase = mnemonic.generate(256)
    logging.debug(f'Generated phrase: {phrase}')
    address = generate_address(phrase)
    logging.debug(f'Generated address: {address}')
    response = f'Mnemonic Phrase: {phrase}\nAddress: {address}'
    await update.message.reply_text(response)


@app.route('/login_wallet', methods=['POST'])
def login_wallet():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    if not phrase:
        return jsonify({'error': 'Mnemonic phrase is required'}), 400

    if not mnemonic.check(phrase):
        return jsonify({'error': 'Invalid mnemonic phrase'}), 400

    address = generate_address(phrase)
    response = {
        'address': address,
    }
    return jsonify(response), 200


async def login_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phrase = context.args[0] if context.args else None
    if not phrase:
        await update.message.reply_text('Mnemonic phrase is required.')
        return

    if not mnemonic.check(phrase):
        await update.message.reply_text('Invalid mnemonic phrase.')
        return

    address = generate_address(phrase)
    response = f'Address: {address}'
    await update.message.reply_text(response)


@app.route('/send_message', methods=['POST'])
def send_message():
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

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, encrypted_content, image)
            proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
            blockchain.new_block(cursor, proof=proof)

        return jsonify({'message': 'Message sent successfully'}), 200

    except Exception as e:
        logging.error(f"Failed to send message: {str(e)}")
        return jsonify({'error': 'Failed to send message'}), 500


async def send_message_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message_parts = update.message.text.split()
        if len(message_parts) < 3:
            await update.message.reply_text('Usage: /send <recipient> <content>')
            return

        phrase = context.args[0]
        recipient = context.args[1]
        content = ' '.join(context.args[2:])

        sender = generate_address(phrase)
        key = generate_key(sender, recipient)
        encrypted_content = encrypt_message(key, content)

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, encrypted_content, None)
            proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
            blockchain.new_block(cursor, proof)

        response = 'Transaction will be added to Block'
        await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"Error sending message: {e}")
        await update.message.reply_text('Internal server error')


@app.route('/get_messages', methods=['POST'])
def get_messages():
    try:
        data = request.get_json()
        address = data.get('address')

        if not address:
            return jsonify({'error': 'Address is required'}), 400

        messages = blockchain.get_messages(address)
        for message in messages:
            key = generate_key(message['sender'], message['recipient'])
            message['content'] = decrypt_message(key, message['content'])

        return jsonify(messages), 200

    except Exception as e:
        logging.error(f"Error getting messages: {e}")
        return jsonify({'error': 'Internal server error'}), 500


async def get_messages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        address = context.args[0]

        if not address:
            await update.message.reply_text('Address is required.')
            return

        messages = blockchain.get_messages(address)
        response = ""
        for message in messages:
            key = generate_key(message['sender'], message['recipient'])
            decrypted_content = decrypt_message(key, message['content'])
            response += f"From: {message['sender']}, To: {message['recipient']}, Message: {decrypted_content}\n"

        await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"Error getting messages: {e}")
        await update.message.reply_text('Internal server error')


@app.route('/mine', methods=['GET'])
def mine():
    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            last_block = blockchain.last_block(cursor)
            last_proof = last_block['proof']
            proof = blockchain.proof_of_work(last_proof)

            blockchain.new_block(cursor, proof)

        response = {
            'message': "New Block Forged",
            'index': last_block['index'] + 1,
            'transactions': last_block['transactions'],
            'proof': proof,
            'previous_hash': blockchain.hash_block(last_block),
        }
        return jsonify(response), 200

    except Exception as e:
        logging.error(f"Error mining block: {e}")
        return jsonify({'error': 'Internal server error'}), 500


async def mine_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            last_block = blockchain.last_block(cursor)
            last_proof = last_block['proof']
            proof = blockchain.proof_of_work(last_proof)

            blockchain.new_block(cursor, proof)

        response = f"New Block Forged\nIndex: {last_block['index'] + 1}\nProof: {proof}\nPrevious Hash: {blockchain.hash_block(last_block)}"
        await update.message.reply_text(response)

    except Exception as e:
        logging.error(f"Error mining block: {e}")
        await update.message.reply_text('Internal server error')


if __name__ == '__main__':
    async def set_webhook():
        await bot.set_webhook(url='https://715a-2a03-d000-1581-7056-1d4c-794b-7793-b31c.ngrok-free.app/webhook')
    asyncio.run(set_webhook())
    application.add_handler(CommandHandler('create', create_wallet_command))
    application.add_handler(CommandHandler('login', login_wallet_command))
    application.add_handler(CommandHandler('send', send_message_command))
    application.add_handler(CommandHandler('messages', get_messages_command))
    application.add_handler(CommandHandler('mine', mine_command))
    application.run_polling()
    app.run(host='0.0.0.0', port=5000, debug=True)
