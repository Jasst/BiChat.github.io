import hashlib

import requests
import json
from translations import translations
from mnemonic import Mnemonic
from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext
from blockchain import Blockchain, CryptoManager
from flask_socketio import SocketIO

# Генерируем случайный ключ key = Fernet.generate_key()

key = b'U_Urs-adepKN6SnJt1YI_JasstmeWtyyTNno2UeX_-0='
crypto_manager = CryptoManager(key)  # Создаем экземпляр CryptoManager с каким-то ключом

app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
blockchain.load_chain()
peers = set()
socketio = SocketIO(app, cors_allowed_origins="*")


def encrypt_message(content):
    return crypto_manager.encrypt_message(content)


def decrypt_message(encrypted_content):
    return crypto_manager.decrypt_message(encrypted_content)


def logout():
    return jsonify({'message': 'Logged out successfully.'})


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
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_required'])}), 400, logout()

    # Validate the mnemonic phrase
    if not mnemonic.check(phrase):
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_invalid'])}), 400, logout()

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
    image = data.get('image')  # Новое поле для изображения

    if not phrase or not recipient or not content:
        return jsonify({'error': gettext(translations[get_locale()]['missing_fields'])}), 400

    key = generate_key_from_phrase(phrase)
    encrypted_content = encrypt_message(content)
    encrypted_image = encrypt_message(image) if image else None  # Шифрование изображения

    blockchain.new_transaction(key.hex(), recipient, encrypted_content, encrypted_image)
    proof = blockchain.proof_of_work(blockchain.last_block['proof'])
    blockchain.new_block(proof=proof)

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


@app.route('/sync_chain', methods=['POST'])
def sync_chain():
    try:
        data = request.get_json()
        peer_chain = data.get('chain')

        if not peer_chain:
            return jsonify({'error': 'Неверные данные цепочки'}), 400

        if len(peer_chain) > len(blockchain.chain) and blockchain.validate_chain(peer_chain):
            blockchain.chain = peer_chain
            blockchain.save_chain()
            return jsonify({'message': 'Цепочка успешно синхронизирована'}), 200
        else:
            return jsonify(
                {'message': 'Синхронизация цепочки не удалась. Входящая цепочка не длиннее или не допустима.'}), 400

    except Exception as e:
        return jsonify({'error': f'Внутренняя ошибка сервера: {str(e)}'}), 500


def notify_peers(new_block):
    for peer in peers:
        try:
            url = f"{peer}/new_block"
            headers = {'Content-Type': 'application/json'}
            data = json.dumps(new_block)
            response = requests.post(url, headers=headers, data=data)
            if response.status_code != 200:
                print(f"Failed to notify peer {peer}")
        except Exception as e:
            print(f"Error notifying peer {peer}: {e}")


@app.route('/register_peer', methods=['POST'])
def register_peer():
    data = request.get_json()
    peer = data.get('peer')
    if peer:
        peers.add(peer)
    return jsonify(list(peers)), 201


@socketio.on('connect')
def handle_connect():
    print(f"New connection: {request.sid}")


@socketio.on('disconnect')
def handle_disconnect():
    print(f"Disconnected: {request.sid}")


if __name__ == '__main__':
    port = 5000
    app.run(host='0.0.0.0', port=port, debug=True)
