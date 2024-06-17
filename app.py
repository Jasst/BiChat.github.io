from blockchain import Blockchain
from mnemonic import Mnemonic
import hashlib
import json
import logging
import sqlite3
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
logging.basicConfig(level=logging.DEBUG)


def generate_key(sender, recipient):
    shared_secret = ''.join(sorted([sender, recipient]))
    return hashlib.sha256(shared_secret.encode()).digest()


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

        with sqlite3.connect(blockchain.db_path) as conn:
            cursor = conn.cursor()
            blockchain.new_transaction(sender, recipient, content, image)
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

        return jsonify({'messages': messages}), 200

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
    app.run(host='0.0.0.0', port=5000, debug=True)
