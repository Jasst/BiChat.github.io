import base64
import hashlib
from cryptography.fernet import Fernet


class CryptoManager:
    def __init__(self, key):
        self.key = self.decode_and_pad_key(key)
        self.cipher = Fernet(self.key)

    def decode_and_pad_key(self, key):
        # Function to add padding to base64 encoded key before decoding
        if len(key) % 4 != 0:
            key += '=' * (4 - len(key) % 4)
        return base64.urlsafe_b64decode(key)

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
            raise ValueError(f'Decryption failed: {str(e)}')


def generate_key(sender, recipient):
    combined_string = f"{sender}{recipient}"
    key = hashlib.sha256(combined_string.encode()).digest()
    return base64.urlsafe_b64encode(key[:32])
