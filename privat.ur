from cryptography.fernet import Fernet

# Генерация ключа на основе мнемонической фразы
def generate_key_from_mnemonic(mnemonic):
    return Fernet.generate_key()

# Шифрование сообщения
def encrypt_message(message, key):
    cipher_suite = Fernet(key)
    return cipher_suite.encrypt(message.encode())

# Дешифрование сообщения
def decrypt_message(encrypted_message, key):
    cipher_suite = Fernet(key)
    return cipher_suite.decrypt(encrypted_message).decode()


 from flask import Flask, request, jsonify
from mnemonic import Mnemonic

app = Flask(__name__)
mnemonic = Mnemonic('english')
users = {}  # Словарь для хранения пользователей и их мнемонических фраз

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    mnemonic_phrase = data.get('mnemonic_phrase')
    if not mnemonic_phrase:
        return jsonify({'error': 'Missing mnemonic_phrase'}), 400

    # Проверяем, существует ли пользователь с указанной мнемонической фразой
    if mnemonic_phrase not in users.values():
        return jsonify({'error': 'Invalid mnemonic_phrase'}), 401

    # Здесь вы можете создать сеанс для пользователя и вернуть его идентификатор
    session_id = generate_session_id()  # Эту функцию нужно реализовать
    return jsonify({'session_id': session_id}), 200

if __name__ == '__main__':
    app.run(debug=True)
