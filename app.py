import hashlib
from flask import Flask, jsonify, request, render_template
from flask_babel import Babel, gettext
from mnemonic import Mnemonic
from blockchain import Blockchain, CryptoManager

app = Flask(__name__)
babel = Babel(app)
mnemonic = Mnemonic('english')
blockchain = Blockchain()
crypto_manager = CryptoManager()
blockchain.load_chain()

@babel.localeselector
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
    try:
        phrase = mnemonic.generate(256)
        address = generate_address(phrase)
        public_key_pem = crypto_manager.get_public_key_pem()
        response = {
            'mnemonic_phrase': phrase,
            'address': address,
            'public_key': public_key_pem.decode(),
            'message': gettext(translations[get_locale()]['wallet_created'])
        }
        return jsonify(response), 200
    except Exception as e:
        print(f"Error creating wallet: {e}")
        return jsonify({'error': 'Error creating wallet'}), 500

@app.route('/login_wallet', methods=['POST'])
def login_wallet():
    data = request.get_json()
    phrase = data.get('mnemonic_phrase')
    if not phrase:
        return jsonify({'error': gettext(translations[get_locale()]['mnemonic_required'])}), 400

    # Validate the mnemonic phrase
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
    image = data.get('image')  # Новое поле для изображения
    recipient_public_key = data.get('recipient_public_key').encode()

    if not phrase or not recipient or not content or not recipient_public_key:
        return jsonify({'error': gettext(translations[get_locale()]['missing_fields'])}), 400

    encrypted_content = crypto_manager.encrypt_message(recipient_public_key, content)
    encrypted_image = crypto_manager.encrypt_message(recipient_public_key, image) if image else None  # Шифрование изображения

    blockchain.new_transaction(generate_key_from_phrase(phrase).hex(), recipient, encrypted_content, encrypted_image)
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
        decrypted_content = crypto_manager.decrypt_message(message['content'])
        decrypted_image = crypto_manager.decrypt_message(message['image']) if message.get('image') else None
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

if __name__ == '__main__':
    port = 5000
    app.run(host='0.0.0.0', port=port, debug=True)
