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

class CryptoManager:
    def __init__(self, key):
        self.cipher_suite = Fernet(key)

    def encrypt_message(self, message):
        encrypted_message = self.cipher_suite.encrypt(message.encode())
        return encrypted_message.decode()

    def decrypt_message(self, encrypted_message):
        decrypted_message = self.cipher_suite.decrypt(encrypted_message.encode())
        return decrypted_message.decode()

def generate_key(sender, recipient):
    shared_secret = sender + recipient
    return base64.urlsafe_b64encode(hashlib.sha256(shared_secret.encode()).digest()[:32])

class Blockchain:
    def __init__(self):
        self.chain = []
        self.current_transactions = []
        self.lock = threading.Lock()
        self.data_file = 'blockchain.json'
        self.load_chain()
        if len(self.chain) == 0:
            self.new_block(previous_hash='1', proof=100)

    def new_block(self, proof, previous_hash=None):
        with self.lock:
            block = {
                'index': len(self.chain) + 1,
                'timestamp': time.time(),
                'transactions': self.current_transactions,
                'proof': proof,
                'previous_hash': previous_hash or self.hash(self.chain[-1]),
            }
            self.current_transactions = []
            self.chain.append(block)
            self.save_chain()
        return block

    def new_transaction(self, sender, recipient, content, image=None):
        with self.lock:
            self.current_transactions.append({
                'sender': sender,
                'recipient': recipient,
                'content': content,
                'image': image,
                'timestamp': time.time(),
            })
        return self.last_block['index'] + 1

    @property
    def last_block(self):
        with self.lock:
            return self.chain[-1]

    @staticmethod
    def hash(block):
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self, last_proof):
        proof = 0
        while self.valid_proof(last_proof, proof) is False:
            proof += 1
        return proof

    @staticmethod
    def valid_proof(last_proof, proof):
        guess = f'{last_proof}{proof}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"

    def get_messages(self, address):
        messages = []
        with self.lock:
            for block in self.chain:
                for transaction in block['transactions']:
                    if transaction['sender'] == address or transaction['recipient'] == address:
                        messages.append(transaction)
        return messages

    def save_chain(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.chain, f, indent=4)

    def load_chain(self):
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r') as f:
                self.chain = json.load(f)
        else:
            self.chain = []

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
