from flask import Flask, jsonify, request, render_template
from blockchain import Blockchain
from mnemonic import Mnemonic
import hashlib
import json
import base64
from cripto_manager import CryptoManager
from translations import translations
import logging
import sqlite3


app = Flask(__name__)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)

def generate_key(sender, recipient):
    shared_secret = sender + recipient
    return base64.urlsafe_b64encode(hashlib.sha256(shared_secret.encode()).digest()[:32])



def generate_address(phrase):
    return hashlib.sha256(phrase.encode()).hexdigest()


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

        crypto_manager = CryptoManager(base64.urlsafe_b64encode(key).decode())

        encrypted_content = crypto_manager.encrypt_message(content)
        encrypted_image = crypto_manager.encrypt_message(image) if image else None

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, encrypted_content, encrypted_image)
            proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
            blockchain.new_block(cursor, proof=proof)

        return jsonify({'message': 'Message sent'}), 201

    except Exception as e:
        app.logger.error(f"Failed to send message: {str(e)}")
        return jsonify({'error': f'Failed to send message: {str(e)}'}), 500


@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')

    if not phrase:
        return jsonify({'error': 'Mnemonic phrase is required'}), 400

    address = generate_address(phrase)
    key = generate_key(address, address)

    crypto_manager = CryptoManager(base64.urlsafe_b64encode(key).decode())

    try:
        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            messages = blockchain.get_messages(address)
    except Exception as e:
        return jsonify({'error': f'Failed to retrieve messages: {str(e)}'}), 500

    try:
        for message in messages:
            message['content'] = crypto_manager.decrypt_message(message['content'])
            message['image'] = crypto_manager.decrypt_message(message['image']) if message['image'] else None
    except ValueError as ve:
        return jsonify({'error': f'Decryption failed: {str(ve)}'}), 500

    return jsonify({'messages': messages}), 200




@app.route('/chain', methods=['GET'])
def full_chain():
    with blockchain:
        chain = blockchain.get_chain(blockchain.cursor)
    response = {
        'chain': chain,
        'length': len(chain),
    }
    return jsonify(response), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
