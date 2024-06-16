import hashlib
import json
import os
import time
import threading
import base64
from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext
from mnemonic import Mnemonic
from cryptography.fernet import Fernet
from translations import translations
from blockchain import Blockchain, CryptoManager


def generate_key(sender, recipient):
    shared_secret = sender + recipient
    return base64.urlsafe_b64encode(hashlib.sha256(shared_secret.encode()).digest()[:32])


app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
blockchain = Blockchain()


def get_locale():
    return request.args.get('lang', 'en')


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
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_required'])}), 400

    if not mnemonic.check(phrase):
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_invalid'])}), 400

    address = generate_address(phrase)
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
    image = data.get('image')

    if not phrase or not recipient or not content:
        return jsonify({'error': gettext(translations[get_locale()]['missing_fields'])}), 400

    sender = generate_address(phrase)
    key = generate_key(sender, recipient)
    crypto_manager = CryptoManager(key)

    try:
        encrypted_content = crypto_manager.encrypt_message(content)
        encrypted_image = crypto_manager.encrypt_message(image) if image else None
    except Exception as e:
        return jsonify({'error': f'Encryption failed: {str(e)}'}), 500

    blockchain.new_transaction(sender, recipient, encrypted_content, encrypted_image)
    proof = blockchain.proof_of_work(blockchain.last_block['proof'])
    blockchain.new_block(proof=proof)

    return jsonify({'message': gettext(translations[get_locale()]['message_sent'])}), 201


@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')

    if not phrase:
        return jsonify({'error': 'Missing required field.'}), 400

    address = generate_address(phrase)
    messages = blockchain.get_messages(address)

    decrypted_messages = []
    for message in messages:
        sender = message['sender']
        recipient = message['recipient']

        if address == sender or address == recipient:
            key = generate_key(sender, recipient)
            crypto_manager = CryptoManager(key)

            try:
                decrypted_content = crypto_manager.decrypt_message(message['content'])
                decrypted_image = crypto_manager.decrypt_message(message['image']) if message.get('image') else None
                decrypted_messages.append({
                    'sender': sender,
                    'recipient': recipient,
                    'content': decrypted_content,
                    'image': decrypted_image,
                    'timestamp': message['timestamp']
                })
            except Exception as e:
                return jsonify({'error': f'Decryption failed: {str(e)}'}), 500

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
