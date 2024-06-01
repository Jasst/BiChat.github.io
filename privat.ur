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