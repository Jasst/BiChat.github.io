import hashlib
import time
import threading
from translations import translations
from mnemonic import Mnemonic
from cryptography.fernet import Fernet
from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext


class Blockchain:
    def __init__(self):
        self.chain = []
        self.current_transactions = []
        self.lock = threading.Lock()  # Создаем блокировку
        self.new_block(previous_hash='1', proof=100)  # Создаем блок генезис

    def new_block(self, proof, previous_hash=None):
        with self.lock:  # Используем блокировку
            block = {
                'index': len(self.chain) + 1,
                'timestamp': time.time(),
                'transactions': self.current_transactions,
                'proof': proof,
                'previous_hash': previous_hash or self.hash(self.chain[-1]),
            }
            self.current_transactions = []
            self.chain.append(block)
        return block

    def new_transaction(self, sender, recipient, content):
        with self.lock:  # Используем блокировку
            self.current_transactions.append({
                'sender': sender,
                'recipient': recipient,
                'content': content,
                'timestamp': time.time(),
            })
        return self.last_block['index'] + 1

    @property
    def last_block(self):
        with self.lock:  # Используем блокировку
            return self.chain[-1]

    @staticmethod
    def hash(block):
        block_string = f"{block['index']}{block['timestamp']}{block['transactions']}{block['proof']}{block['previous_hash']}"
        return hashlib.sha256(block_string.encode()).hexdigest()

    def get_messages(self, key_hex):
        messages = []
        with self.lock:  # Используем блокировку
            for block in self.chain:
                for transaction in block['transactions']:
                    if transaction['sender'] == key_hex or transaction['recipient'] == key_hex:
                        messages.append(transaction)
        return messages


app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
cipher_key = Fernet.generate_key()
cipher_suite = Fernet(cipher_key)
# app: Flask = Flask(__name__, static_folder='/home/jasstme/BiChat.github.io/static')
blockchain = Blockchain()


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


@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    recipient = data.get('recipient')
    content = data.get('content')

    if not phrase or not recipient or not content:
        return jsonify({'error': gettext(translations[get_locale()]['missing_fields'])}), 400

    key = generate_key_from_phrase(phrase)
    encrypted_content = cipher_suite.encrypt(content.encode()).decode()
    blockchain.new_transaction(key.hex(), recipient, encrypted_content)
    blockchain.new_block(proof=100)

    return jsonify({'message': gettext(translations[get_locale()]['message_sent'])}), 201


@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')

    if not phrase:
        return jsonify({'error': 'Отсутствует обязательное поле'}), 400

    key = generate_key_from_phrase(phrase)
    messages = blockchain.get_messages(key.hex())

    decrypted_messages = []
    for message in messages:
        if 'content' in message:
            decrypted_content = cipher_suite.decrypt(message['content'].encode()).decode()
            decrypted_messages.append({'sender': message['sender'], 'content': decrypted_content})

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
