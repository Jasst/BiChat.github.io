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
from blockchain import Blockchain  # Ensure Blockchain class is imported correctly
from translations import translations
from cripto_manager import CryptoManager, generate_key

app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)



@app.before_request
def before_request():
    g.db = sqlite3.connect('blockchain.db')


@app.teardown_request
def teardown_request(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def generate_key(sender, recipient):
    shared_secret = sender + recipient
    return base64.urlsafe_b64encode(hashlib.sha256(shared_secret.encode()).digest()[:32])


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
        return jsonify(
            {'error': gettext(translations.get(request.args.get('lang', 'en'), {}).get('missing_fields'))}), 400

    sender = blockchain.generate_address(phrase)
    key = generate_key(sender, recipient)
    crypto_manager = CryptoManager(base64.urlsafe_b64encode(key).decode())  # Encode key and decode with CryptoManager

    try:
        encrypted_content = crypto_manager.encrypt_message(content)
        encrypted_image = crypto_manager.encrypt_message(image) if image else None
    except ValueError as ve:
        logger.error(f'Encryption failed: {ve}')
        return jsonify({'error': str(ve)}), 500

    try:
        with blockchain as bc:
            bc.new_transaction(sender, recipient, encrypted_content, encrypted_image)
            proof = bc.proof_of_work(bc.last_block['proof'])
            bc.new_block(proof=proof)
    except Exception as e:
        logger.error(f'Failed to add transaction/block: {e}')
        return jsonify({'error': 'Failed to add transaction/block'}), 500

    return jsonify({'message': gettext(translations.get(request.args.get('lang', 'en'), {}).get('message_sent'))}), 201


@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')

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
        logger.error(f'Decryption failed: {ve}')
        return jsonify({'error': str(ve)}), 500

    return jsonify({'messages': messages}), 200


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
