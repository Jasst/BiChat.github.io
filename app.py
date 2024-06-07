import hashlib
from translations import translations
from mnemonic import Mnemonic
from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext
from blockchain import Blockchain
import os

import os
from cryptography.fernet import Fernet


class CryptoManager:
    def __init__(self, key):
        self.key = key
        self.cipher_suite = Fernet(key)

    def encrypt_message(self, message):
        encrypted_message = self.cipher_suite.encrypt(message.encode())
        return encrypted_message.decode()

    def decrypt_message(self, encrypted_message):
        decrypted_message = self.cipher_suite.decrypt(encrypted_message.encode())
        return decrypted_message.decode()

# Генерируем случайный ключ key = Fernet.generate_key()

key = b'U_Urs-adepKN6SnJt1YI_JasstmeWtyyTNno2UeX_-0='
crypto_manager = CryptoManager(key)  # Создаем экземпляр CryptoManager с каким-то ключом

app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
blockchain.load_chain()


def encrypt_message(content):
    return crypto_manager.encrypt_message(content)


def decrypt_message(encrypted_content):
    return crypto_manager.decrypt_message(encrypted_content)


def logout():
    return jsonify({'message': 'Logged out successfully.'})


def get_locale():
    return request.args.get('lang', 'en')


def generate_key_from_phrase(phrase):
    return hashlib.sha256(phrase.encode()).digest()


def generate_address(phrase):
    return hashlib.sha256(phrase.encode()).hexdigest()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    phrase = mnemonic.generate(256)
    address = generate_address(phrase)
    response = {
        'mnemonic_phrase': phrase,
        'address': address,
        'message': gettext(translations[get_locale()]['wallet_created'])
    }
    return jsonify(response), 200


@app.route('/login_wallet', methods=['POST'])
def login_wallet():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    if not phrase:
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_required'])}), 400, logout()

    # Validate the mnemonic phrase
    if not mnemonic.check(phrase):
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_invalid'])}), 400, logout()

    address = generate_address(phrase)
    key = generate_key_from_phrase(phrase)
    response = {
        'address': address,
        'message': gettext(translations[get_locale()]['wallet_created'])
    }
    return jsonify(response), 200


@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    recipient = data.get('recipient')
    content = data.get('content')

    if not phrase or not recipient or not content:
        return jsonify({'error': gettext(translations[get_locale()]['missing_fields'])}), 400

    key = generate_key_from_phrase(phrase)
    encrypted_content = encrypt_message(content)
    blockchain.new_transaction(key.hex(), recipient, encrypted_content)
    proof = blockchain.proof_of_work(blockchain.last_block['proof'])
    blockchain.new_block(proof=proof)

    return jsonify({'message': gettext(translations[get_locale()]['message_sent'])}), 201


@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')

    if not phrase:
        return jsonify({'error': 'Missing required field.'}), 400

    key = generate_key_from_phrase(phrase)
    messages = blockchain.get_messages(key.hex())

    decrypted_messages = []
    for message in messages:
        decrypted_content = decrypt_message(message['content'])
        decrypted_messages.append({
            'sender': message['sender'],
            'recipient': message['recipient'],
            'content': decrypted_content,
            'timestamp': message['timestamp']
        })

    return jsonify(decrypted_messages), 200


@app.route('/chain', methods=['GET'])
def full_chain():
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return jsonify(response), 200


if __name__ == '__main__':
    port = 5000
    app.run(host='0.0.0.0', port=port, debug=True)
