import hashlib
from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext
from mnemonic import Mnemonic
from blockchain import Blockchain, CryptoManager
import requests
from translations import translations

app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
blockchain.load_chain()

# Создаем экземпляр CryptoManager с каким-то ключом
key = b'U_Urs-adepKN6SnJt1YI_JasstmeWtyyTNno2UeX_-0='
crypto_manager = CryptoManager(key)


# Функции для работы с блокчейном

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


# Эндпоинты для Flask приложения

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


# Новые эндпоинты для работы с блокчейном и пирами

@app.route('/register_peer', methods=['POST'])
def register_peer():
    data = request.get_json()
    peer_url = data.get('peer')
    if peer_url:
        blockchain.register_peer(peer_url)
        return jsonify({'message': f"Peer {peer_url} registered successfully."}), 200
    else:
        return jsonify({'error': 'Missing peer URL in request.'}), 400


@app.route('/update_chain', methods=['POST'])
def update_chain():
    data = request.get_json()
    new_chain = data.get('chain')
    if new_chain:
        blockchain.replace_chain(new_chain)
        return jsonify({'message': 'Chain updated successfully.'}), 200
    else:
        return jsonify({'error': 'Missing chain data in request.'}), 400


if __name__ == '__main__':
    # Публичный URL первого сервера
    server1_url = 'https://jasstme.pythonanywhere.com'
    # Публичный URL второго сервера
    server2_url = 'https://7567-2a03-d000-1690-b7d3-e491-48b2-6fb7-dcf5.ngrok-free.app'

    # Регистрация первого сервера на втором
    requests.post(f'{server2_url}/register_peer', json={'peer': server1_url})
    # Регистрация второго сервера на первом
    requests.post(f'{server1_url}/register_peer', json={'peer': server2_url})

    # Синхронизация цепочки первого сервера со вторым
    requests.post(f'{server1_url}/update_chain', json={'chain': blockchain.chain})
    # Синхронизация цепочки второго сервера с первым
    requests.post(f'{server2_url}/update_chain', json={'chain': blockchain.chain})

    port =5000
    app.run(host='0.0.0.0', port=port, debug=True)
