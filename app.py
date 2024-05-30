from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from blockchain import blockchain  # Ваш модуль блокчейна

app = Flask(__name__)
CORS(app)

blockchain = blockchain()  # Инициализация блокчейна

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_wallet', methods=['POST'])
def create_wallet():
    wallet = blockchain.create_wallet()
    return jsonify(wallet)

@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.get_json()
    mnemonic = data['mnemonic_phrase']
    recipient = data['recipient']
    content = data['content']
    message = blockchain.send_message(mnemonic, recipient, content)
    return jsonify({'message': 'Message sent successfully'})

@app.route('/get_messages', methods=['POST'])
def get_messages():
    data = request.get_json()
    mnemonic = data['mnemonic_phrase']
    messages = blockchain.get_messages(mnemonic)
    return jsonify(messages)

if __name__ == '__main__':
    app.run()
