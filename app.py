from flask import Flask, jsonify, request, render_template
from mnemonic import Mnemonic
import logging
from blockchain import Blockchain
from crypto_manager import encrypt_message, decrypt_message, generate_key, generate_address
import sqlite3
from functools import wraps
from contextlib import closing

app = Flask(__name__)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)

# Middleware for error handling
def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            app.logger.error(f"Error: {str(e)}")
            return jsonify({'error': str(e)}), 500
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_wallet', methods=['POST'])
@handle_errors
def create_wallet():
    phrase = mnemonic.generate(256)
    logging.debug(f'Generated phrase: {phrase}')
    address = generate_address(phrase)
    logging.debug(f'Generated address: {address}')
    return jsonify({'mnemonic_phrase': phrase, 'address': address}), 200

@app.route('/login_wallet', methods=['POST'])
@handle_errors
def login_wallet():
    phrase = request.json.get('mnemonic_phrase')
    if not phrase:
        return jsonify({'error': 'Mnemonic phrase is required'}), 400

    if not mnemonic.check(phrase):
        return jsonify({'error': 'Invalid mnemonic phrase'}), 400

    address = generate_address(phrase)
    return jsonify({'address': address}), 200

@app.route('/send_message', methods=['POST'])
@handle_errors
def send_message():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    recipient = data.get('recipient')
    content = data.get('content')
    image = data.get('image')

    if not all([phrase, recipient, content]):
        return jsonify({'error': 'Missing fields'}), 400

    sender = generate_address(phrase)
    key = generate_key(sender, recipient)

    encrypted_content = encrypt_message(key, content)
    encrypted_image = encrypt_message(key, image) if image else ""

    with closing(sqlite3.connect(blockchain.db_path)) as conn:
        cursor = conn.cursor()
        blockchain.new_transaction(sender, recipient, encrypted_content, encrypted_image)
        proof = blockchain.proof_of_work(blockchain.last_block(cursor)['proof'])
        blockchain.new_block(cursor, proof=proof)

    return jsonify({'message': 'Message sent'}), 201

@app.route('/get_messages', methods=['POST'])
@handle_errors
def get_messages():
    phrase = request.json.get('mnemonic_phrase')
    if not phrase:
        return jsonify({'error': 'Mnemonic phrase is required'}), 400

    address = generate_address(phrase)

    with closing(sqlite3.connect(blockchain.db_path)) as conn:
        cursor = conn.cursor()
        messages = blockchain.get_messages(address)

    decrypted_messages = []
    for message in messages:
        key = generate_key(message['sender'], message['recipient'])
        decrypted_content = decrypt_message(key, message['content'])
        decrypted_image = decrypt_message(key, message['image']) if message['image'] else None

        decrypted_messages.append({
            **message,
            'content': decrypted_content if decrypted_content else "Failed to decrypt content",
            'image': decrypted_image
        })

    return jsonify({'messages': decrypted_messages}), 200

@app.route('/chain', methods=['GET'])
@handle_errors
def full_chain():
    with closing(sqlite3.connect(blockchain.db_path)) as conn:
        cursor = conn.cursor()
        chain = blockchain.get_chain(cursor)
    return jsonify({'chain': chain, 'length': len(chain)}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)