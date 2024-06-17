import base64
import hashlib
from cryptography.fernet import Fernet
import base64


class CryptoManager:
    def __init__(self, key):
<<<<<<< HEAD
        self.key = key
        self.cipher = Fernet(self.key)
=======
        self.key = base64.urlsafe_b64decode(key)
        self.cipher = Fernet(key)
>>>>>>> main

    def encrypt_message(self, message):
        if message is None:
            return None
        try:
            encrypted_message = self.cipher.encrypt(message.encode())
            return base64.urlsafe_b64encode(encrypted_message).decode()
        except Exception as e:
            raise ValueError(f'Encryption failed: {str(e)}')

    def decrypt_message(self, encrypted_message):
        if encrypted_message is None:
            return None
        try:
            decoded_encrypted_message = base64.urlsafe_b64decode(encrypted_message.encode())
            decrypted_message = self.cipher.decrypt(decoded_encrypted_message)
            return decrypted_message.decode()
        except Exception as e:
<<<<<<< HEAD
            raise ValueError(f'Decryption failed: {str(e)}')
=======
            raise ValueError(f'Decryption failed: {str(e)}')
>>>>>>> main
