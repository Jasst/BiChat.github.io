from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext
from flask_socketio import SocketIO, emit
import hashlib
import threading
import requests
from mnemonic import Mnemonic
from blockchain import Blockchain, CryptoManager

app = Flask(__name__)
babel = Babel(app)
socketio = SocketIO(app, cors_allowed_origins="*")
mnemonic = Mnemonic('english')
blockchain = Blockchain()
blockchain.load_chain()

key = Fernet.generate_key()
crypto_manager = CryptoManager(key)
peers = set()

translations = {
    'en': {
        'wallet_created': 'Wallet created successfully!',
        'mnemonic_required': 'Mnemonic phrase is required.',
        'mnemonic_invalid': 'Invalid mnemonic phrase.',
        'missing_fields': 'Missing required fields.',
        'message_sent': 'Message sent successfully.'
    }
}

def encrypt_message(content):
    return crypto_manager.encrypt_message(content)

def decrypt_message(encrypted_content):
    return crypto_manager.decrypt_message(encrypted_content)

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
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_required'])}), 400

    if not mnemonic.check(phrase):
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_invalid'])}), 400

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
    image = data.get('image')

    if not phrase or not recipient or not content:
        return jsonify({'error': gettext(translations[get_locale()]['missing_fields'])}), 400

    key = generate_key_from_phrase(phrase)
    encrypted_content = encrypt_message(content)
    encrypted_image = encrypt_message(image) if image else None

    blockchain.new_transaction(key.hex(), recipient, encrypted_content, encrypted_image)
    proof = blockchain.proof_of_work(blockchain.last_block['proof'])
    block = blockchain.new_block(proof=proof)

    for peer in peers:
        try:
            socketio.emit('new_block', block, namespace=f'/{peer}')
        except Exception as e:
            print(f"Error notifying peer {peer}: {e}")

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
        decrypted_image = decrypt_message(message['image']) if message.get('image') else None
        decrypted_messages.append({
            'sender': message['sender'],
            'recipient': message['recipient'],
            'content': decrypted_content,
            'image': decrypted_image,
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

@app.route('/register_peer', methods=['POST'])
def register_peer():
    data = request.get_json()
    peer = data.get('peer')
    if peer:
        peers.add(peer)
    return jsonify(list(peers)), 201

@socketio.on('connect')
def on_connect():
    emit('blockchain', blockchain.chain)

@socketio.on('new_block')
def on_new_block(data):
    block_string = json.dumps(data, sort_keys=True)
    signature = bytes.fromhex(data['signature'])
    if blockchain.verify_signature(blockchain.public_key, block_string, signature):
        blockchain.chain.append(data)
        blockchain.save_chain()
    else:
        print("Invalid block signature")

def sync_with_peers():
    while True:
        for peer in peers:
            try:
                response = requests.get(f"https://{peer}/chain", verify='cert.pem')
                if response.status_code == 200:
                    peer_chain = response.json()['chain']
                    if len(peer_chain) > len(blockchain.chain):
                        blockchain.chain = peer_chain
                        blockchain.save_chain()
            except Exception as e:
                print(f"Error syncing with peer {peer}: {e}")
        time.sleep(10)

threading.Thread(target=sync_with_peers).start()

if __name__ == '__main__':
    port = 5000
    socketio.run(app, host='0.0.0.0', port=port, debug=True, ssl_context=('cert.pem', 'key.pem'))
