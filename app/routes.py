from flask import render_template, jsonify, request
from mnemonic import Mnemonic
from cryptography.fernet import Fernet
import hashlib
import time

from app import app
from blockchain import Blockchain

mnemonic = Mnemonic('english')
cipher_suite = Fernet(Fernet.generate_key())
blockchain = Blockchain()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    phrase = mnemonic.generate(256)
    address = blockchain.generate_address(phrase)
    return jsonify({'mnemonic_phrase': phrase, 'address': address}), 200

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    recipient = data.get('recipient')
    content = data.get('content')

    if not phrase or not recipient or not content:
        return jsonify({'error': 'Missing required fields'}), 400

    key = blockchain.generate_key_from_phrase(phrase)
    encrypted_content = cipher_suite.encrypt(content.encode()).decode()
    blockchain.new_transaction(key.hex(), recipient, encrypted_content)
    blockchain.new_block(proof=100)

    return jsonify({'message': 'Message sent successfully'}), 201

@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')

    if not phrase:
        return jsonify({'error': 'Missing required field'}), 400

    key = blockchain.generate_key_from_phrase(phrase)
    messages = blockchain.get_messages(key.hex())

    decrypted_messages = []
    for message in messages:
        if 'content' in message:
            decrypted_content = cipher_suite.decrypt(message['content'].encode()).decode()
            decrypted_messages.append({'sender': message['sender'], 'content': decrypted_content})

    return jsonify(decrypted_messages), 200
