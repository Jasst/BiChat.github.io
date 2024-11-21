from flask import Flask, jsonify, request, render_template
from mnemonic import Mnemonic
import logging
from blockchain import Blockchain
from crypto_manager import encrypt_message, decrypt_message, generate_key, generate_address
import sqlite3
import subprocess
import os
from werkzeug.exceptions import BadRequest
from marshmallow import Schema, fields, ValidationError

# Инициализация приложения и компонентов
app = Flask(__name__)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.INFO)

# Валидация входных данных с помощью Marshmallow
class WalletSchema(Schema):
    mnemonic_phrase = fields.Str(required=True)

class MessageSchema(Schema):
    mnemonic_phrase = fields.Str(required=True)
    recipient = fields.Str(required=True)
    content = fields.Str(required=True)
    image = fields.Str(allow_none=True)


@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    """Создание нового кошелька"""
    try:
        phrase = mnemonic.generate(256)
        logging.info(f'Generated mnemonic phrase: {phrase}')
        address = generate_address(phrase)
        logging.info(f'Generated address: {address}')
        return jsonify({'mnemonic_phrase': phrase, 'address': address}), 200
    except Exception as e:
        logging.error(f"Error creating wallet: {str(e)}")
        return jsonify({'error': 'Failed to create wallet'}), 500


@app.route('/login_wallet', methods=['POST'])
def login_wallet():
    """Вход в существующий кошелёк"""
    try:
        data = WalletSchema().load(request.get_json())
        phrase = data['mnemonic_phrase']

        if not mnemonic.check(phrase):
            return jsonify({'error': 'Invalid mnemonic phrase'}), 400

        address = generate_address(phrase)
        return jsonify({'address': address}), 200
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Error logging in wallet: {str(e)}")
        return jsonify({'error': 'Failed to login wallet'}), 500


@app.route('/send_message', methods=['POST'])
def send_message():
    """Отправка зашифрованного сообщения"""
    try:
        data = MessageSchema().load(request.get_json())
        phrase = data['mnemonic_phrase']
        recipient = data['recipient']
        content = data['content']
        image = data.get('image')

        sender = generate_address(phrase)
        key = generate_key(sender, recipient)
        encrypted_content = encrypt_message(key, content)
        encrypted_image = encrypt_message(key, image) if image else None

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, encrypted_content, encrypted_image)
            proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
            blockchain.new_block(cursor, proof=proof)

        return jsonify({'message': 'Message sent successfully'}), 201
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Error sending message: {str(e)}")
        return jsonify({'error': 'Failed to send message'}), 500


@app.route('/get_messages', methods=['POST'])
def get_messages():
    """Получение сообщений для пользователя"""
    try:
        data = WalletSchema().load(request.get_json())
        phrase = data['mnemonic_phrase']

        address = generate_address(phrase)

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            messages = blockchain.get_messages(address)

        decrypted_messages = []
        for message in messages:
            key = generate_key(message['sender'], message['recipient'])
            decrypted_content = decrypt_message(key, message['content']) or "Failed to decrypt content"
            decrypted_image = decrypt_message(key, message['image']) if message['image'] else None

            decrypted_message = {
                'sender': message['sender'],
                'recipient': message['recipient'],
                'content': decrypted_content,
                'image': decrypted_image,
            }
            decrypted_messages.append(decrypted_message)

        return jsonify({'messages': decrypted_messages}), 200
    except ValidationError as err:
        return jsonify({'error': err.messages}), 400
    except Exception as e:
        logging.error(f"Error retrieving messages: {str(e)}")
        return jsonify({'error': 'Failed to retrieve messages'}), 500


@app.route('/chain', methods=['GET'])
def full_chain():
    """Получение полной цепочки блоков"""
    try:
        with blockchain:
            chain = blockchain.get_chain(blockchain.cursor)
        return jsonify({'chain': chain, 'length': len(chain)}), 200
    except Exception as e:
        logging.error(f"Error retrieving blockchain: {str(e)}")
        return jsonify({'error': 'Failed to retrieve blockchain'}), 500


if __name__ == '__main__':
    script_path = os.path.abspath('bot_script.py')
    logging.info(f'Script path: {script_path}')

    if os.path.exists(script_path):
        try:
            subprocess.Popen(['python', script_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logging.info('bot_script.py started successfully')
        except Exception as e:
            logging.error(f"Failed to start bot script: {str(e)}")
    else:
        logging.error(f"Script path does not exist: {script_path}")

    app.run(host='0.0.0.0', port=5000)
