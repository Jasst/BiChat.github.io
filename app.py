from flask import Flask, jsonify, request, render_template
from mnemonic import Mnemonic
import logging
from blockchain import Blockchain
from crypto_manager import encrypt_message, decrypt_message, generate_key, generate_address
import sqlite3

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


@app.route('/get_messages', methods=['POST'])
def get_messages():
    try:
        data = request.get_json()
        phrase = data.get('mnemonic_phrase')

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


if __name__ == '__main__':
    app.run()
