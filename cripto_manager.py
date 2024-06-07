from cryptography.fernet import Fernet


class CryptoManager:
    def __init__(self, key):
        self.key = key
        self.cipher_suite = Fernet(key)

    def encrypt_message(self, message):
        encrypted_message = self.cipher_suite.encrypt(message.encode())
        return encrypted_message.decode()

    def decrypt_message(self, encrypted_message):
        decrypted_message = self.cipher_suite.decrypt(encrypted_message.encode())
        return decrypted_message.decode()
